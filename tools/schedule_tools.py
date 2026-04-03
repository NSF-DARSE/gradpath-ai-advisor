"""Tools for reading semester schedule / term offerings."""

import json
from pathlib import Path
from typing import Any, Dict, List


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SCHEDULES_DIR = DATA_DIR / "schedules"


def _term_to_filename(term: str) -> str:
    """Convert a term like 'Fall 2026' to 'fall_2026.json'."""
    return term.lower().replace(" ", "_") + ".json"


def load_semester_offerings(term: str) -> Dict[str, Any]:
    """Load schedule JSON for a given term.

    Example: 'Fall 2026' -> data/schedules/fall_2026.json
    Returns an empty offerings dict if the semester file does not exist.
    """
    file_path = SCHEDULES_DIR / _term_to_filename(term)
    if not file_path.exists():
        return {"term": term, "offerings": []}
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_offered_course_ids(term: str) -> List[str]:
    """Return the list of course IDs offered in a given term."""
    schedule = load_semester_offerings(term)
    offerings = schedule.get("offerings", [])
    return [item["course_id"] for item in offerings]
