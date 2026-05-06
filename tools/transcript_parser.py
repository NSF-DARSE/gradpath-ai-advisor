"""Deterministic transcript extraction helpers shared by the backend and ADK tools."""

from __future__ import annotations

import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .transcript_schema import (
    AcademicSummary,
    CompletedCourseRecord,
    TranscriptCourse,
    TranscriptDocument,
    TranscriptStudent,
    TranscriptTerm,
)


LOGGER = logging.getLogger(__name__)
DEFAULT_TRANSCRIPT_LLM_MODEL = os.getenv("GRADPATH_TRANSCRIPT_LLM_MODEL", "gemini-2.5-flash")

TERM_PATTERN = re.compile(r"\b(Fall|Spring|Summer|Winter)\s+20\d{2}\b", re.IGNORECASE)
YEAR_TERM_PATTERN = re.compile(r"\b(20\d{2})\s+(Fall|Spring|Summer|Winter)\b", re.IGNORECASE)
GRADE_PATTERN = re.compile(
    r"^(A\+|A-|A|B\+|B-|B|C\+|C-|C|D\+|D|F|P|NP|S|U|CR|NC|W|I|IP)$",
    re.IGNORECASE,
)
COURSE_CODE_PATTERN = re.compile(r"\b([A-Z]{2,5})[- ]?(\d{3,4}[A-Z]?)\b")
INCOMPLETE_GRADES = {"W", "I", "IP", "AU", "CIP"}
FAILED_GRADES = {"F", "NP", "NC", "U"}
COLUMN_SPLIT_PATTERN = re.compile(r"\s{10,}")


@dataclass
class TranscriptParseResult:
    """A rich parse result with enough metadata for UI and ADK flows."""

    status: str
    message: str
    transcript: Optional[TranscriptDocument]
    raw_text: str
    warnings: List[str] = field(default_factory=list)
    extraction_method: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        """Return a JSON-safe dictionary for tools and APIs."""

        return {
            "status": self.status,
            "message": self.message,
            "warnings": list(self.warnings),
            "extraction_method": self.extraction_method,
            "transcript": self.transcript.model_dump() if self.transcript else None,
            "raw_text_excerpt": self.transcript.raw_text_excerpt if self.transcript else _excerpt(self.raw_text),
        }


def extract_text_from_pdf_bytes(content: bytes) -> Tuple[str, str]:
    """Extract text from a PDF using pdfplumber first, then a pypdf fallback."""

    if not content:
        raise ValueError("The uploaded PDF is empty.")

    methods: Sequence[Tuple[str, Any]] = (
        ("pdfplumber", _extract_with_pdfplumber),
        ("pypdf", _extract_with_pypdf),
    )
    extraction_errors: List[str] = []
    for method_name, extractor in methods:
        try:
            text = extractor(content)
        except Exception as exc:  # pragma: no cover - defensive logging for runtime PDFs
            extraction_errors.append(f"{method_name}: {exc}")
            LOGGER.warning("Transcript PDF extraction failed with %s: %s", method_name, exc)
            continue
        if text.strip():
            return text, method_name

    error_details = "; ".join(extraction_errors) or "No extractor returned text."
    raise ValueError(f"Unable to extract text from transcript PDF. {error_details}")


def extract_text_from_pdf_path(pdf_path: Path | str) -> Tuple[str, str]:
    """Read a local PDF path and extract its text."""

    path = Path(pdf_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Transcript PDF not found: {path}")
    return extract_text_from_pdf_bytes(path.read_bytes())


def parse_transcript_pdf(content: bytes) -> TranscriptParseResult:
    """Extract text from a text-based PDF and then parse it into structured JSON."""

    text, method_name = extract_text_from_pdf_bytes(content)
    return parse_transcript_text(text, extraction_method=method_name)


def parse_transcript_text(text: str, extraction_method: Optional[str] = None) -> TranscriptParseResult:
    """Parse transcript text into the normalized GradPath schema."""

    raw_lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines()]
    normalized_text = normalize_text(text)
    if not normalized_text:
        raise ValueError("Transcript text is empty after normalization.")

    lines = [line for line in normalized_text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Transcript text does not contain any readable lines.")

    student = _extract_student_fields(raw_lines, lines)
    summary = _extract_academic_summary(raw_lines, lines)
    terms = _extract_terms(raw_lines, lines)
    completed_courses = _build_completed_courses(terms)

    transcript = TranscriptDocument(
        student=student,
        academic_summary=summary,
        terms=terms,
        completed_courses=completed_courses,
        raw_text_excerpt=_excerpt(normalized_text),
    )

    warnings: List[str] = []
    if not terms:
        warnings.append("No transcript terms were detected from the extracted text.")
    if not completed_courses:
        warnings.append("No completed course rows were detected from the extracted text.")

    if not normalized_text.strip():
        return TranscriptParseResult(
            status="error",
            message="Transcript parsing failed because no readable text was available.",
            transcript=None,
            raw_text=normalized_text,
            warnings=warnings,
            extraction_method=extraction_method,
        )

    if not completed_courses and _looks_like_scanned_pdf_text(normalized_text):
        warnings.append("The PDF appears to be image-based or OCR is required.")
        return TranscriptParseResult(
            status="ocr_required",
            message="The transcript PDF does not appear to contain machine-readable text yet. OCR support is required.",
            transcript=transcript,
            raw_text=normalized_text,
            warnings=warnings,
            extraction_method=extraction_method,
        )

    if _should_try_llm_fallback(transcript):
        llm_transcript = _try_llm_transcript_fallback(
            text=normalized_text,
            existing_transcript=transcript,
        )
        if llm_transcript is not None:
            transcript = _merge_transcript_documents(transcript, llm_transcript)
            warnings.append(
                "Used the transcript LLM fallback to fill gaps from an unfamiliar transcript layout."
            )

    return TranscriptParseResult(
        status="success",
        message="Transcript parsed successfully.",
        transcript=transcript,
        raw_text=normalized_text,
        warnings=warnings,
        extraction_method=extraction_method,
    )


def transcript_from_json(payload: Dict[str, Any]) -> TranscriptParseResult:
    """Validate a transcript JSON payload against the shared schema."""

    transcript = TranscriptDocument.model_validate(payload)
    warnings = []
    if not transcript.completed_courses:
        warnings.append("Transcript JSON validated, but it does not contain completed courses yet.")
    return TranscriptParseResult(
        status="success",
        message="Transcript JSON validated successfully.",
        transcript=transcript,
        raw_text=json.dumps(payload, indent=2),
        warnings=warnings,
        extraction_method="json",
    )


def normalize_text(text: str) -> str:
    """Normalize whitespace while keeping one meaningful line per transcript row."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    normalized_lines = []
    for raw_line in normalized.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if line:
            normalized_lines.append(line)
    return "\n".join(normalized_lines)


def _extract_student_fields(raw_lines: Sequence[str], normalized_lines: Sequence[str]) -> TranscriptStudent:
    institution = _search_value(
        normalized_lines,
        (
            r"(?:institution|college|university)\s*[:\-]\s*(.+)",
            r"^(.+?(?:University|College|Institute))$",
        ),
    )
    top_name = None
    for line in raw_lines[:6]:
        stripped = line.strip()
        if not stripped or ":" in stripped or "Page:" in stripped or "Date:" in stripped:
            continue
        if re.fullmatch(r"[A-Za-z ,.'-]+", stripped):
            top_name = re.sub(r"\s{2,}", " ", stripped)
            break
    return TranscriptStudent(
        name=_search_value(
            normalized_lines,
            (
                r"(?:student name|birth name|name)\s*[:\-]\s*(.+)",
            ),
        )
        or top_name,
        student_id=_search_value(
            normalized_lines,
            (
                r"(?:id number|student id|student number)\s*[:#\- ]+\s*([A-Za-z0-9-]+)",
            ),
        ),
        institution=institution,
        program=_search_value(normalized_lines, (r"(?:program|major|degree|plan)\s*[:\-]\s*(.+)",)),
    )


def _extract_academic_summary(raw_lines: Sequence[str], normalized_lines: Sequence[str]) -> AcademicSummary:
    cumulative_gpa = _search_float(
        normalized_lines,
        (
            r"(?:cumulative gpa|cum gpa|overall gpa)\s*[:\-]?\s*(\d+\.\d+)",
            r"(?:gpa)\s*[:\-]?\s*(\d+\.\d+)",
        ),
    )
    total_credits_completed = _search_float(
        normalized_lines,
        (
            r"(?:total credits completed|credits completed|credits earned|earned credits)\s*[:\-]?\s*(\d+(?:\.\d+)?)",
        ),
    )
    if cumulative_gpa is None or total_credits_completed is None:
        cum_line = _find_last_cumulative_line(raw_lines)
        if cum_line:
            parsed_credits, parsed_gpa = _parse_cumulative_line(cum_line)
            total_credits_completed = total_credits_completed if total_credits_completed is not None else parsed_credits
            cumulative_gpa = cumulative_gpa if cumulative_gpa is not None else parsed_gpa
    return AcademicSummary(
        cumulative_gpa=cumulative_gpa,
        total_credits_completed=total_credits_completed,
    )


def _extract_terms(raw_lines: Sequence[str], normalized_lines: Sequence[str]) -> List[TranscriptTerm]:
    column_terms = _extract_terms_from_columns(raw_lines)
    standard_terms: List[TranscriptTerm] = []
    current_term: Optional[str] = None
    current_term_lines: List[str] = []

    for line in normalized_lines:
        detected_term = _extract_term_name(line)
        if detected_term:
            if current_term and current_term_lines:
                standard_terms.append(_build_term(current_term, current_term_lines))
            current_term = detected_term
            current_term_lines = []
            continue
        if current_term:
            current_term_lines.append(line)

    if current_term and current_term_lines:
        standard_terms.append(_build_term(current_term, current_term_lines))

    column_terms = [term for term in column_terms if term.courses]
    standard_terms = [term for term in standard_terms if term.courses]
    if _term_course_count(column_terms) > _term_course_count(standard_terms):
        return column_terms
    return standard_terms



def _build_term(term_name: str, lines: Sequence[str]) -> TranscriptTerm:
    merged_lines = _merge_wrapped_course_lines(lines)
    term_gpa = _search_float(lines, (r"(?:term gpa|semester gpa)\s*[:\-]?\s*(\d+\.\d+)",))
    courses: List[TranscriptCourse] = []
    seen = set()

    for line in merged_lines:
        parsed = _parse_course_line(line)
        if not parsed:
            continue
        key = parsed.dedupe_key(term_name)
        if key in seen:
            continue
        seen.add(key)
        courses.append(parsed)

    return TranscriptTerm(term=term_name, term_gpa=term_gpa, courses=courses)


def _merge_wrapped_course_lines(lines: Sequence[str]) -> List[str]:
    """Join transcript rows that wrap titles across multiple lines."""

    merged: List[str] = []
    buffer: Optional[str] = None
    for line in lines:
        if COURSE_CODE_PATTERN.search(line):
            if buffer:
                merged.append(buffer)
            buffer = line
            continue

        if buffer and not _looks_like_metadata_line(line):
            buffer = f"{buffer} {line}"
            if _parse_course_line(buffer):
                merged.append(buffer)
                buffer = None
            continue

        if buffer:
            merged.append(buffer)
            buffer = None

    if buffer:
        merged.append(buffer)
    return merged


def _parse_course_line(line: str) -> Optional[TranscriptCourse]:
    """Extract a course row using a deterministic, transcript-friendly regex."""

    cleaned = re.sub(r"\s+", " ", line).strip()
    return _parse_course_chunk(cleaned)


def _build_completed_courses(terms: Iterable[TranscriptTerm]) -> List[CompletedCourseRecord]:
    completed: List[CompletedCourseRecord] = []
    seen = set()
    for term in terms:
        for course in term.courses:
            grade_upper = (course.grade or "").upper()
            if grade_upper in INCOMPLETE_GRADES or grade_upper in FAILED_GRADES:
                continue
            if course.credits == 0:
                continue
            key = course.dedupe_key(term.term)
            if key in seen:
                continue
            seen.add(key)
            completed.append(
                CompletedCourseRecord(
                    term=term.term,
                    course_code=course.course_code,
                    course_title=course.course_title,
                    credits=course.credits,
                    grade=course.grade,
                )
            )
    return completed


def _extract_term_name(line: str) -> Optional[str]:
    if re.match(r"^(Fall|Spring|Summer|Winter)\s+20\d{2}$", line, re.IGNORECASE):
        parts = line.split()
        return f"{parts[0].title()} {parts[1]}"

    if re.match(r"^20\d{2}\s+(Fall|Spring|Summer|Winter)$", line, re.IGNORECASE):
        parts = line.split()
        return f"{parts[1].title()} {parts[0]}"

    match = re.search(r"(?:term|semester)\s*[:\-]?\s*(Fall|Spring|Summer|Winter)\s+(20\d{2})", line, re.IGNORECASE)
    if match:
        return f"{match.group(1).title()} {match.group(2)}"
    match = YEAR_TERM_PATTERN.search(line)
    if match:
        return f"{match.group(2).title()} {match.group(1)}"
    return None


def _looks_like_metadata_line(line: str) -> bool:
    lowered = line.lower()
    metadata_tokens = ("gpa", "credit", "standing", "institution", "student", "program", "major")
    return any(token in lowered for token in metadata_tokens)


def _looks_like_scanned_pdf_text(text: str) -> bool:
    letters = sum(char.isalpha() for char in text)
    return letters < 40


def _extract_with_pdfplumber(content: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        pages = [(page.extract_text() or "").strip() for page in pdf.pages]
    return "\n".join(page for page in pages if page).strip()


def _extract_with_pypdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    return "\n".join(page for page in pages if page).strip()


def _search_value(lines: Sequence[str], patterns: Sequence[str]) -> Optional[str]:
    for line in lines:
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return match.group(1).strip()
    return None


def _search_float(lines: Sequence[str], patterns: Sequence[str]) -> Optional[float]:
    value = _search_value(lines, patterns)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _normalize_course_code(raw_code: str) -> str:
    code_match = COURSE_CODE_PATTERN.search(raw_code.upper())
    if not code_match:
        return raw_code.upper().strip()
    return f"{code_match.group(1)} {code_match.group(2)}"


def _excerpt(text: str, limit: int = 500) -> str:
    return text[:limit].strip()


def _extract_terms_from_columns(raw_lines: Sequence[str]) -> List[TranscriptTerm]:
    """Parse transcripts that are printed in two side-by-side columns."""

    active_terms = [None, None]
    term_courses: Dict[str, List[TranscriptCourse]] = {}
    term_gpas: Dict[str, float] = {}
    # Keyed by column index — stores (term, fragment_text) for a course whose title
    # was wrapped across two PDF lines (e.g. "Operating Systems W/" / "Linux 4.00 B- 10.80").
    pending_fragments: Dict[int, Tuple[Optional[str], str]] = {}

    for raw_line in raw_lines:
        normalized_line = re.sub(r"\s+", " ", raw_line).strip()
        if not normalized_line:
            pending_fragments.clear()
            continue

        compact_courses = _extract_course_chunks(normalized_line)
        term_occurrences = _extract_term_occurrences(normalized_line)
        line_starts_with_summary = normalized_line.startswith(("Att Cred", "Term ", "Cum "))

        if compact_courses:
            # A new course starts here — any saved fragments can't be continued.
            pending_fragments.clear()

            if len(compact_courses) >= 2 and active_terms[0] and active_terms[1]:
                _append_course(term_courses, active_terms[0], compact_courses[0])
                _append_course(term_courses, active_terms[1], compact_courses[1])
                continue

            if len(compact_courses) == 1:
                course = compact_courses[0]
                if line_starts_with_summary and active_terms[1]:
                    _append_course(term_courses, active_terms[1], course)
                elif active_terms[0]:
                    _append_course(term_courses, active_terms[0], course)
                elif active_terms[1]:
                    _append_course(term_courses, active_terms[1], course)

            for side, term_name, _ in term_occurrences:
                active_terms[side] = term_name
                term_courses.setdefault(term_name, [])
            continue

        segments = _split_transcript_columns(raw_line)
        if not any(segments):
            pending_fragments.clear()
            continue

        for index, segment in enumerate(segments):
            if not segment:
                continue
            term_name = _extract_term_name(segment)
            if term_name:
                active_terms[index] = term_name
                term_courses.setdefault(term_name, [])
                pending_fragments.pop(index, None)
                continue

            parsed_gpa = _parse_term_gpa(segment)
            if parsed_gpa is not None and active_terms[index]:
                term_gpas[active_terms[index]] = parsed_gpa
                continue

            current_term = active_terms[index]
            if current_term is None:
                continue

            # Try to complete a pending fragment for this column.
            if index in pending_fragments:
                frag_term, frag_text = pending_fragments[index]
                if not COURSE_CODE_PATTERN.search(segment):
                    merged = f"{frag_text} {segment}"
                    merged_courses = _parse_course_entries(merged)
                    if merged_courses:
                        for course in merged_courses:
                            _append_course(term_courses, frag_term, course)
                        del pending_fragments[index]
                        continue
                del pending_fragments[index]

            courses = _parse_course_entries(segment)
            if courses:
                for course in courses:
                    _append_course(term_courses, current_term, course)
            elif COURSE_CODE_PATTERN.search(segment) and not _extract_term_name(segment):
                # Course code present but no grade — likely a wrapped title; save fragment.
                pending_fragments[index] = (current_term, segment)

    ordered_terms = []
    for term_name, courses in term_courses.items():
        if courses:
            ordered_terms.append(
                TranscriptTerm(
                    term=term_name,
                    term_gpa=term_gpas.get(term_name),
                    courses=courses,
                )
            )
    return ordered_terms


def _parse_course_entries(segment: str) -> List[TranscriptCourse]:
    cleaned = re.sub(r"\s+", " ", segment).strip()
    courses: List[TranscriptCourse] = []
    matches = list(COURSE_CODE_PATTERN.finditer(cleaned))
    if not matches:
        return courses

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        chunk = cleaned[start:end].strip()
        parsed = _parse_course_chunk(chunk)
        if parsed is not None:
            courses.append(parsed)
    return courses


def _parse_term_gpa(segment: str) -> Optional[float]:
    match = re.search(r"Term\s+\(.*?\)\s+\(.*?\)\s+\(.*?\)\s+\(.*?\)\s+\(\s*(\d+\.\d+)\)", segment, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def _find_last_cumulative_line(raw_lines: Sequence[str]) -> Optional[str]:
    cumulative_lines = [line for line in raw_lines if "Cum" in line and "(" in line and ")" in line]
    return cumulative_lines[-1] if cumulative_lines else None


def _parse_cumulative_line(line: str) -> Tuple[Optional[float], Optional[float]]:
    numbers = re.findall(r"\(\s*([0-9]+(?:\.[0-9]+)?)\s*\)", line)
    if len(numbers) < 2:
        return None, None
    credits = float(numbers[1])
    gpa = float(numbers[-1])
    return credits, gpa


def _split_transcript_columns(raw_line: str) -> List[str]:
    """Split one PDF text line into left/right transcript columns when present."""

    line = raw_line.rstrip("\n")
    if not line.strip():
        return []

    split_index = _find_column_split_index(line)
    if split_index is not None:
        return [line[:split_index].strip(), line[split_index:].strip()]

    segments = [segment.strip() for segment in COLUMN_SPLIT_PATTERN.split(line) if segment.strip()]
    if not segments:
        return []
    if len(segments) == 1:
        return [segments[0], ""]
    return segments[:2]


def _parse_course_chunk(chunk: str) -> Optional[TranscriptCourse]:
    """Parse one transcript course chunk using token rules instead of one rigid regex."""

    code_match = re.match(r"^(?P<code>[A-Z]{2,5}[- ]?\d{3,4}[A-Z]?)\s+(?P<rest>.+)$", chunk, re.IGNORECASE)
    if not code_match:
        return None

    code = _normalize_course_code(code_match.group("code"))
    tokens = code_match.group("rest").split()
    if not tokens:
        return None

    grade_index = None
    grade = None
    trailing_start = max(len(tokens) - 3, 0)
    for index in range(len(tokens) - 1, trailing_start - 1, -1):
        token = tokens[index].upper()
        if GRADE_PATTERN.match(token) or token == "CIP":
            grade_index = index
            grade = token
            break
    if grade_index is None or grade is None:
        return None

    credits = 0.0
    title_tokens = tokens[:grade_index]
    if grade_index > 0 and re.fullmatch(r"\d+(?:\.\d+)?", tokens[grade_index - 1]):
        credits = float(tokens[grade_index - 1])
        title_tokens = tokens[: grade_index - 1]

    course_title = " ".join(title_tokens).strip(" -")
    if not course_title:
        return None

    return TranscriptCourse(
        course_code=code,
        course_title=course_title,
        credits=credits,
        grade=grade,
    )


def _term_course_count(terms: Sequence[TranscriptTerm]) -> int:
    return sum(len(term.courses) for term in terms)


def _append_course(
    term_courses: Dict[str, List[TranscriptCourse]],
    term_name: Optional[str],
    course: TranscriptCourse,
) -> None:
    if not term_name:
        return
    bucket = term_courses.setdefault(term_name, [])
    if course.dedupe_key(term_name) in {existing.dedupe_key(term_name) for existing in bucket}:
        return
    bucket.append(course)


def _find_column_split_index(line: str) -> Optional[int]:
    """Find the true start of the right column from the raw PDF line."""

    candidate_positions: List[int] = []

    course_matches = list(COURSE_CODE_PATTERN.finditer(line))
    if len(course_matches) >= 2:
        candidate_positions.extend(
            match.start() for match in course_matches[1:] if match.start() >= 45
        )

    for pattern in (YEAR_TERM_PATTERN, TERM_PATTERN):
        for match in pattern.finditer(line):
            if match.start() >= 45:
                candidate_positions.append(match.start())

    for token in ("Att Cred", "Term  (", "Cum   (", "End of official record."):
        index = line.find(token)
        if index >= 45:
            candidate_positions.append(index)

    if candidate_positions:
        return min(candidate_positions)

    gap_matches = [match for match in re.finditer(r"\s{8,}", line) if match.start() >= 45]
    if gap_matches:
        return gap_matches[0].end()

    return None


def _extract_course_chunks(line: str) -> List[TranscriptCourse]:
    """Extract course rows from a compact line that may contain left and right columns."""

    matches = list(COURSE_CODE_PATTERN.finditer(line))
    if not matches:
        return []

    term_starts = [start for _, _, start in _extract_term_occurrences(line)]
    chunks: List[TranscriptCourse] = []
    for index, match in enumerate(matches):
        start = match.start()
        next_course_start = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        future_term_starts = [position for position in term_starts if position > start]
        next_term_start = min(future_term_starts) if future_term_starts else len(line)
        end = min(next_course_start, next_term_start)
        parsed = _parse_course_chunk(line[start:end].strip())
        if parsed is not None:
            chunks.append(parsed)
    return chunks


def _extract_term_occurrences(line: str) -> List[Tuple[int, str, int]]:
    """Return detected terms with side hints and their start position."""

    occurrences: List[Tuple[int, str, int]] = []
    for pattern in (YEAR_TERM_PATTERN, TERM_PATTERN):
        for match in pattern.finditer(line):
            term_name = _extract_term_name(match.group(0))
            if term_name is None:
                continue
            side = 1 if match.start() >= max(len(line) // 2, 24) else 0
            occurrences.append((side, term_name, match.start()))
    occurrences.sort(key=lambda item: item[2])
    return occurrences


def _should_try_llm_fallback(transcript: TranscriptDocument) -> bool:
    """Decide whether the deterministic parser left enough gaps to justify an LLM assist."""

    generic_programs = {"unknown", "undergraduate", "graduate", "student"}
    program = (transcript.student.program or "").strip().lower()
    has_generic_program = program in generic_programs
    too_few_courses = len(transcript.completed_courses) < 4
    missing_terms = not transcript.terms
    missing_identity = not transcript.student.name or not transcript.student.student_id
    return too_few_courses or missing_terms or missing_identity or has_generic_program


def _try_llm_transcript_fallback(
    *,
    text: str,
    existing_transcript: TranscriptDocument,
) -> Optional[TranscriptDocument]:
    """Use Gemini as a fallback helper when deterministic parsing is incomplete.

    This is intentionally optional. If the model is not configured or the call
    fails, GradPath keeps the deterministic result instead of failing the upload.
    """

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # pragma: no cover - import depends on runtime env
        LOGGER.warning("Transcript LLM fallback is unavailable: %s", exc)
        return None

    schema_hint = TranscriptDocument.model_json_schema()
    prompt = f"""
Extract a student transcript into strict JSON.

Rules:
- Return only valid JSON matching the provided schema.
- Keep unavailable values as null or [].
- Parse terms and courses from the transcript text.
- Exclude in-progress courses like CIP/IP unless a final grade exists.
- Preserve original course codes and course titles from the transcript.
- Do not invent data.

Existing deterministic extraction:
{json.dumps(existing_transcript.model_dump(), indent=2)}

Target JSON schema:
{json.dumps(schema_hint, indent=2)}

Transcript text:
{text[:18000]}
""".strip()

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=DEFAULT_TRANSCRIPT_LLM_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=TranscriptDocument,
            ),
        )
        candidate_text = getattr(response, "text", "") or ""
        if not candidate_text.strip():
            parsed = getattr(response, "parsed", None)
            if parsed is not None:
                return TranscriptDocument.model_validate(parsed)
            return None
        return TranscriptDocument.model_validate(json.loads(candidate_text))
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        LOGGER.warning("Transcript LLM fallback failed: %s", exc)
        return None


def _merge_transcript_documents(
    deterministic: TranscriptDocument,
    llm_result: TranscriptDocument,
) -> TranscriptDocument:
    """Merge deterministic extraction with an LLM fallback, preferring solid local data."""

    merged_student = TranscriptStudent(
        name=deterministic.student.name or llm_result.student.name,
        student_id=deterministic.student.student_id or llm_result.student.student_id,
        institution=deterministic.student.institution or llm_result.student.institution,
        program=_pick_preferred_program(deterministic.student.program, llm_result.student.program),
    )
    merged_summary = AcademicSummary(
        cumulative_gpa=(
            deterministic.academic_summary.cumulative_gpa
            if deterministic.academic_summary.cumulative_gpa is not None
            else llm_result.academic_summary.cumulative_gpa
        ),
        total_credits_completed=(
            deterministic.academic_summary.total_credits_completed
            if deterministic.academic_summary.total_credits_completed is not None
            else llm_result.academic_summary.total_credits_completed
        ),
    )
    merged_terms = _merge_terms(deterministic.terms, llm_result.terms)
    merged_completed = _build_completed_courses(merged_terms)
    if not merged_completed:
        merged_completed = _merge_completed_courses(deterministic.completed_courses, llm_result.completed_courses)

    return TranscriptDocument(
        student=merged_student,
        academic_summary=merged_summary,
        terms=merged_terms,
        completed_courses=merged_completed,
        raw_text_excerpt=deterministic.raw_text_excerpt or llm_result.raw_text_excerpt,
    )


def _pick_preferred_program(deterministic_program: Optional[str], llm_program: Optional[str]) -> Optional[str]:
    generic_programs = {"undergraduate", "graduate", "student", "unknown", ""}
    deterministic_value = (deterministic_program or "").strip()
    llm_value = (llm_program or "").strip()
    if deterministic_value.lower() not in generic_programs:
        return deterministic_value
    return llm_value or deterministic_value or None


def _merge_terms(
    deterministic_terms: Sequence[TranscriptTerm],
    llm_terms: Sequence[TranscriptTerm],
) -> List[TranscriptTerm]:
    merged_by_term: Dict[str, TranscriptTerm] = {}

    for term in llm_terms:
        merged_by_term[term.term] = term.model_copy(deep=True)

    for term in deterministic_terms:
        if term.term not in merged_by_term:
            merged_by_term[term.term] = term.model_copy(deep=True)
            continue

        current = merged_by_term[term.term]
        course_map = {
            course.dedupe_key(term.term): course.model_copy(deep=True)
            for course in current.courses
        }
        for course in term.courses:
            course_map[course.dedupe_key(term.term)] = course.model_copy(deep=True)
        merged_by_term[term.term] = TranscriptTerm(
            term=term.term,
            term_gpa=term.term_gpa if term.term_gpa is not None else current.term_gpa,
            courses=list(course_map.values()),
        )

    return list(merged_by_term.values())


def _merge_completed_courses(
    deterministic_courses: Sequence[CompletedCourseRecord],
    llm_courses: Sequence[CompletedCourseRecord],
) -> List[CompletedCourseRecord]:
    merged: Dict[Tuple[str, Optional[str], str], CompletedCourseRecord] = {}
    for course in llm_courses:
        key = (course.course_code, course.term, course.course_title.lower())
        merged[key] = course.model_copy(deep=True)
    for course in deterministic_courses:
        key = (course.course_code, course.term, course.course_title.lower())
        merged[key] = course.model_copy(deep=True)
    return list(merged.values())
