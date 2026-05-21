"""Build registry files for source PDFs and normalized JSON data.

This script does not OCR transcripts. Instead, it records which transcript PDFs
already have normalized JSON and which ones still require OCR before runtime use.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


PACKAGE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PACKAGE_DIR / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
CATALOGS_DIR = DATA_DIR / "catalogs"
SCHEDULES_DIR = DATA_DIR / "schedules"
REGISTRY_DIR = DATA_DIR / "registry"
STUDENT_INDEX_FILE = REGISTRY_DIR / "student_index.json"
SOURCE_MANIFEST_FILE = REGISTRY_DIR / "source_manifest.json"


TRANSCRIPT_ALIAS_OVERRIDES = {
    "T1": {
        "aliases": ["T1", "s1", "s1001"],
        "transcript_file": "student_s1001.json",
    },
    "T2": {
        "aliases": ["T2", "s2", "s1002"],
        "transcript_file": "student_s1002.json",
    },
}


def _catalog_entries() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for path in sorted(CATALOGS_DIR.glob("*")):
        entries.append(
            {
                "file": path.name,
                "kind": "pdf" if path.suffix.lower() == ".pdf" else "json",
            }
        )
    return entries


def _schedule_entries() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for path in sorted(SCHEDULES_DIR.glob("*")):
        entries.append(
            {
                "file": path.name,
                "kind": "pdf" if path.suffix.lower() == ".pdf" else "json",
            }
        )
    return entries


def _transcript_records() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    for path in sorted(TRANSCRIPTS_DIR.glob("T*.pdf")):
        match = re.fullmatch(r"T(\d+)\.pdf", path.name)
        if not match:
            continue

        transcript_number = match.group(1)
        canonical_key = f"T{transcript_number}"
        default_record = {
            "student_key": f"s{transcript_number}",
            "aliases": [canonical_key, f"s{transcript_number}"],
            "status": "ocr_required",
            "message": "Transcript PDF is present, but OCR/normalization has not been completed.",
            "source_pdf": path.name,
            "transcript_file": None,
        }

        override = TRANSCRIPT_ALIAS_OVERRIDES.get(canonical_key)
        if override:
            default_record["aliases"] = override["aliases"]
            default_record["transcript_file"] = override["transcript_file"]
            default_record["status"] = "ready"
            default_record["message"] = "Normalized transcript JSON is available."

        records.append(default_record)

    return records


def build_student_index() -> Dict[str, Any]:
    return {
        "version": 1,
        "students": _transcript_records(),
    }


def build_source_manifest() -> Dict[str, Any]:
    student_index = build_student_index()
    return {
        "version": 1,
        "catalogs": _catalog_entries(),
        "schedules": _schedule_entries(),
        "transcripts": student_index["students"],
    }


def write_registry_files() -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

    student_index = build_student_index()
    source_manifest = build_source_manifest()

    STUDENT_INDEX_FILE.write_text(
        json.dumps(student_index, indent=2),
        encoding="utf-8",
    )
    SOURCE_MANIFEST_FILE.write_text(
        json.dumps(source_manifest, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_registry_files()
