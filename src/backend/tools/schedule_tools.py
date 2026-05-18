"""Tools for reading semester schedule / term offerings."""

import json
from pathlib import Path
from typing import Any, Dict, List


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SCHEDULES_DIR = DATA_DIR / "schedules"


def _term_to_filename(term: str) -> str:
    """Convert a term like 'Spring 2026' to 'spring_2026.json'."""
    return term.lower().replace(" ", "_") + ".json"


def load_semester_offerings(term: str) -> List[Dict[str, Any]]:
    """Load schedule JSON for a given term.

    Returns a flat list of section dicts.
    Returns empty list if no schedule file exists for that term.
    """
    file_path = SCHEDULES_DIR / _term_to_filename(term)
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Support both flat list and old {"offerings": [...]} format
    if isinstance(data, list):
        return data
    return data.get("offerings", [])


def get_offered_course_ids(term: str) -> List[str]:
    """Return unique course IDs offered in a given term (deduplicated across sections)."""
    sections = load_semester_offerings(term)
    seen = set()
    result = []
    for item in sections:
        cid = item.get("course_id")
        if cid and cid not in seen:
            seen.add(cid)
            result.append(cid)
    return result
