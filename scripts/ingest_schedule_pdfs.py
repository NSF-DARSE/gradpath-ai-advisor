"""Convert text-based schedule PDFs into normalized JSON files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from .pdf_text import extract_pdf_text


PACKAGE_DIR = Path(__file__).resolve().parent.parent
SCHEDULES_DIR = PACKAGE_DIR / "data" / "schedules"

SCHEDULE_FILES = [
    "COURSE_SCHEDULE2026SPNEW.pdf",
    "COURSE_SCHEDULE2026SU_GCNEW.pdf",
    "COURSE_SCHEDULE2026SU_OLNEW.pdf",
]

COURSE_LINE_RE = re.compile(r"^(?P<course_id>[A-Z]{2,4}-\d{4})\s+(?P<section>[A-Z0-9]+)\b")
TERM_RE = re.compile(r"^(?P<term>(Spring|Summer|Fall)\s+\d{4})\s+Course Schedule$", re.MULTILINE)


def parse_schedule_pdf(pdf_path: Path) -> Dict[str, Any]:
    """Parse a text-based schedule PDF into a simple offerings JSON structure."""
    text = extract_pdf_text(pdf_path)
    term_match = TERM_RE.search(text)
    term = term_match.group("term") if term_match else pdf_path.stem

    offerings: List[Dict[str, str]] = []
    seen = set()

    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        match = COURSE_LINE_RE.match(line)
        if not match:
            continue

        course_id = match.group("course_id")
        section = match.group("section")
        dedupe_key = (course_id, section)
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        offerings.append(
            {
                "course_id": course_id,
                "section": section,
                "source_line": line,
            }
        )

    output_name = term.lower().replace(" ", "_") + ".json"
    return {
        "term": term,
        "source_pdf": pdf_path.name,
        "offerings": offerings,
        "output_name": output_name,
    }


def write_schedule_json(parsed_schedule: Dict[str, Any]) -> Path:
    """Write one parsed schedule to data/schedules/<term>.json."""
    output_path = SCHEDULES_DIR / parsed_schedule["output_name"]
    payload = {
        "term": parsed_schedule["term"],
        "source_pdf": parsed_schedule["source_pdf"],
        "offerings": parsed_schedule["offerings"],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def ingest_all_schedule_pdfs() -> List[Path]:
    """Parse all configured schedule PDFs and write normalized JSON outputs."""
    written_files: List[Path] = []
    for filename in SCHEDULE_FILES:
        pdf_path = SCHEDULES_DIR / filename
        if not pdf_path.exists():
            continue
        parsed_schedule = parse_schedule_pdf(pdf_path)
        written_files.append(write_schedule_json(parsed_schedule))
    return written_files


if __name__ == "__main__":
    for path in ingest_all_schedule_pdfs():
        print(path)
