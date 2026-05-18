"""Tools for reading catalog, requirements, and prerequisites."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List


def _normalize(cid: str) -> str:
    """Normalize course IDs to uppercase hyphenated format e.g. CSC-1058."""
    cid = cid.strip().upper()
    if re.match(r'^[A-Z]{2,5}-\d{3,4}', cid):
        return cid
    cid = re.sub(r'\s+', '-', cid)
    cid = re.sub(r'^([A-Z]{2,5})(\d{3,4})', r'\1-\2', cid)
    return cid

from .schedule_tools import get_offered_course_ids


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CATALOGS_DIR = DATA_DIR / "catalogs"

CATALOG_FILE = CATALOGS_DIR / "catalog_2026.json"
MAJOR_REQUIREMENTS_FILE = CATALOGS_DIR / "major_requirements.json"


def load_catalog_data() -> List[Dict[str, Any]]:
    """Load the flat course catalog list from catalog_2026.json."""
    with CATALOG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_major_requirements() -> Dict[str, Any]:
    """Load major -> required courses mapping."""
    with MAJOR_REQUIREMENTS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_required_courses(major: str) -> List[str]:
    """Return required course IDs for a given major key (e.g. 'CS')."""
    requirements = load_major_requirements()
    return requirements.get(major, {}).get("required_courses", [])


def get_total_credits_required(major: str, student_type: str = "undergraduate") -> int:
    """Return total degree credits required for a major and student type."""
    requirements = load_major_requirements()
    catalog_value = requirements.get(major, {}).get("total_credits_required")
    if catalog_value:
        return int(catalog_value)
    return {"undergraduate": 120, "graduate": 36, "phd": 60}.get(student_type.lower(), 120)


def get_course_prerequisites(course_id: str) -> List[str]:
    """Return prerequisite course IDs for one course, normalized to hyphen format."""
    catalog = load_catalog_data()
    for course in catalog:
        if course.get("course_id") == course_id:
            return [_normalize(p) for p in course.get("prerequisites", [])]
    return []


def load_major_planning_context(major: str, target_semester: str) -> Dict[str, Any]:
    """Return only the catalog data needed for one major and one term."""
    catalog = load_catalog_data()
    required_courses = get_required_courses(major)

    course_lookup = {c["course_id"]: c for c in catalog}

    course_details: Dict[str, Dict[str, Any]] = {}
    for course_id in required_courses:
        course = course_lookup.get(course_id, {})
        course_details[course_id] = {
            "title": course.get("title", "Unknown"),
            "credits": course.get("credits", 4),
            "prerequisites": course.get("prerequisites", []),
        }

    return {
        "major": major,
        "target_semester": target_semester,
        "required_courses": required_courses,
        "course_details": course_details,
        "offered_in_target_semester": get_offered_course_ids(target_semester),
    }
