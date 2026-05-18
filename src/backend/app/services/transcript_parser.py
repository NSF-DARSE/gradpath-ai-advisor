"""Backend adapter for transcript uploads that reuses the shared GradPath parser."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.transcript_parser import parse_transcript_pdf, parse_transcript_text, transcript_from_json

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
REGISTRY_FILE = DATA_DIR / "registry" / "student_index.json"


@dataclass
class ParsedTranscript:
    filename: str
    raw_text: str
    profile: Optional[Dict[str, Any]]
    warnings: List[str]
    transcript_json: Optional[Dict[str, Any]]
    status: str
    message: str
    content_bytes: Optional[bytes] = None


def parse_upload(filename: str, content: bytes) -> ParsedTranscript:
    """Parse an uploaded transcript file into the shared normalized schema."""

    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        return _parse_json_upload(filename, content)
    if suffix in {".txt", ".md"}:
        return _parse_text_upload(filename, content)
    if suffix == ".pdf":
        return _parse_pdf_upload(filename, content)
    raise ValueError("Unsupported transcript file type. Upload JSON, TXT, MD, or PDF.")


def _parse_json_upload(filename: str, content: bytes) -> ParsedTranscript:
    payload = json.loads(content.decode("utf-8"))
    result = transcript_from_json(payload)
    return _build_parsed_transcript(
        filename=filename,
        result=result,
        content_bytes=content,
    )


def _parse_text_upload(filename: str, content: bytes) -> ParsedTranscript:
    text = content.decode("utf-8", errors="ignore")
    result = parse_transcript_text(text, extraction_method="text")
    return _build_parsed_transcript(
        filename=filename,
        result=result,
        content_bytes=content,
    )


def _parse_pdf_upload(filename: str, content: bytes) -> ParsedTranscript:
    result = parse_transcript_pdf(content)
    return _build_parsed_transcript(
        filename=filename,
        result=result,
        content_bytes=content,
    )


def _build_parsed_transcript(filename: str, result: Any, content_bytes: bytes) -> ParsedTranscript:
    transcript_json = result.transcript.model_dump() if result.transcript else None
    profile = result.transcript.to_planner_profile() if result.transcript else None

    if result.status == "success" and profile is not None:
        profile = _auto_register_student(profile, filename)

    return ParsedTranscript(
        filename=filename,
        raw_text=result.raw_text,
        profile=profile,
        warnings=list(result.warnings),
        transcript_json=transcript_json,
        status=result.status,
        message=result.message,
        content_bytes=content_bytes,
    )


def _auto_register_student(profile: Dict[str, Any], source_filename: str) -> Dict[str, Any]:
    """Save the parsed profile as a JSON file and register in the student index."""

    student_id = profile.get("student_id", "").strip()
    if not student_id or student_id in {"chat-history", "uploaded-transcript", ""}:
        return profile

    # Generate a safe filename from the student ID
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", student_id)
    json_filename = f"student_{safe_id}.json"
    json_path = TRANSCRIPTS_DIR / json_filename

    # Add status and source fields to the profile
    profile_to_save = {
        "student_id": student_id,
        "student_name": profile.get("student_name", "Unknown"),
        "major": profile.get("major", "Unknown"),
        "student_type": profile.get("student_type", "undergraduate"),
        "gpa": profile.get("gpa"),
        "current_semester": profile.get("current_semester", "Unknown"),
        "expected_graduation": profile.get("expected_graduation"),
        "career_goal": profile.get("career_goal"),
        "preferences": profile.get("preferences", "balanced"),
        "completed_courses": profile.get("completed_courses", []),
        "in_progress_courses": profile.get("in_progress_courses", []),
    }

    # Save JSON file
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(profile_to_save, f, indent=2)

    # Register in student index
    _register_in_index(student_id, json_filename, source_filename)

    # Return enriched profile with status=ready so planner can use it
    return {**profile_to_save, "status": "ready", "source": "uploaded_transcript"}


def _register_in_index(student_id: str, json_filename: str, source_pdf: str) -> None:
    """Add or update the student entry in student_index.json."""

    if not REGISTRY_FILE.exists():
        index = {"version": 1, "students": []}
    else:
        with REGISTRY_FILE.open("r", encoding="utf-8") as f:
            index = json.load(f)

    students = index.get("students", [])

    # Check if already registered
    for record in students:
        if student_id.lower() in [a.lower() for a in record.get("aliases", [])]:
            # Update existing record
            record["status"] = "ready"
            record["transcript_file"] = json_filename
            record["message"] = "Normalized transcript JSON is available."
            with REGISTRY_FILE.open("w", encoding="utf-8") as f:
                json.dump(index, f, indent=2)
            return

    # Add new record
    student_key = re.sub(r"[^a-zA-Z0-9]", "", student_id).lower()
    students.append({
        "student_key": student_key,
        "aliases": [student_id, student_key],
        "status": "ready",
        "message": "Normalized transcript JSON is available.",
        "source_pdf": source_pdf,
        "transcript_file": json_filename,
    })
    index["students"] = students

    with REGISTRY_FILE.open("w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
