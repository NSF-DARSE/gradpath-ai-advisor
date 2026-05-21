"""Tools for resolving student aliases and loading normalized transcript data."""

import json
from pathlib import Path
from typing import Any, Dict, List


DATA_DIR = Path(__file__).resolve().parents[3] / "data"
REGISTRY_DIR = DATA_DIR / "registry"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
STUDENT_INDEX_FILE = REGISTRY_DIR / "student_index.json"


def load_student_index() -> Dict[str, Any]:
    """Load the student alias/index registry."""
    with STUDENT_INDEX_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_student_records() -> List[Dict[str, Any]]:
    """Return all known student records from the index."""
    index = load_student_index()
    return index.get("students", [])


def resolve_student_record(student_ref: str) -> Dict[str, Any]:
    """Resolve a user-provided student ref like 's1', 'T1', or 's1001'."""
    normalized = student_ref.strip().lower()

    for record in list_student_records():
        aliases = {alias.lower() for alias in record.get("aliases", [])}
        if normalized in aliases:
            return record

    raise ValueError(f"Unknown student reference: {student_ref}")


def load_student_profile(student_ref: str) -> Dict[str, Any]:
    """Load one normalized student transcript if it is ready for runtime use."""
    try:
        record = resolve_student_record(student_ref)
    except ValueError:
        return {
            "student_ref": student_ref,
            "status": "not_found",
            "message": f"Student '{student_ref}' is not in the GradPath registry. Use transcript data from session state instead.",
        }
    transcript_file = record.get("transcript_file")

    if record.get("status") != "ready" or not transcript_file:
        return {
            "student_ref": student_ref,
            "status": record.get("status", "unavailable"),
            "message": record.get(
                "message",
                "Transcript data is not available yet for this student.",
            ),
            "source_pdf": record.get("source_pdf"),
            "aliases": record.get("aliases", []),
        }

    file_path = TRANSCRIPTS_DIR / transcript_file
    with file_path.open("r", encoding="utf-8") as f:
        profile = json.load(f)

    profile["status"] = "ready"
    profile["student_ref"] = student_ref
    profile["aliases"] = record.get("aliases", [])
    profile["source_pdf"] = record.get("source_pdf")
    return profile
