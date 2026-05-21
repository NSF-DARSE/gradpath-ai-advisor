"""
Parse Lincoln University PDFs into structured JSON files.

Outputs:
  data/catalogs/catalog_2026.json
  data/schedules/spring_2026.json
  data/schedules/summer_2026_gc.json
  data/schedules/summer_2026_ol.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import pdfplumber
except ImportError:
    print("Installing pdfplumber...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pdfplumber"])
    import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CATALOGS_DIR = DATA / "catalogs"
SCHEDULES_DIR = DATA / "schedules"

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DAY_CODES = {"M", "T", "W", "R", "F", "S", "U"}

def normalize_time(raw: str) -> Optional[str]:
    """Convert '10:00 AM' -> '10:00', '01:40 PM' -> '13:40'."""
    if not raw or raw.strip() in ("", "TBA", "TBD"):
        return None
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", raw.strip(), re.IGNORECASE)
    if not m:
        return None
    h, mn, period = int(m.group(1)), m.group(2), m.group(3).upper()
    if period == "PM" and h != 12:
        h += 12
    if period == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mn}"


def parse_day_string(raw: str) -> List[str]:
    """Parse 'MTWF' or 'MW' or 'TR' into list of day codes."""
    if not raw or raw.strip() in ("", "TBA", "TBD", "ONLINE"):
        return []
    days = []
    i = 0
    s = raw.strip()
    while i < len(s):
        if s[i] in DAY_CODES:
            days.append(s[i])
            i += 1
        else:
            i += 1
    return days


def safe_int(val: Any) -> Optional[int]:
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Schedule parser (Spring + Summer GC)
# ---------------------------------------------------------------------------

# Pattern: COURSE_ID SECTION CREDITS TITLE LOCATION DAYS START END FACULTY BLDG ROOM TYPE
# Example: ACC-2005 01 4 Principles of Accounting MC MW 04:00 PM 05:40 PM S. Duncan DHAL 253 LEC
SCHEDULE_ROW = re.compile(
    r"^([A-Z]{2,4}-\d{3,4}[A-Z]?)\s+"   # course_id  e.g. ACC-2005
    r"(\S+)\s+"                            # section    e.g. 01, G1, W1
    r"(\d+)\s+"                            # credits    e.g. 4
    r"(.+?)\s+"                            # title      (greedy, trimmed below)
    r"(MC|GC|OL|ONLINE|TBA)\s+"           # location
    r"([MTWRFSU]+|TBA)?\s*"               # days       optional
    r"(\d{1,2}:\d{2}\s*(?:AM|PM))?\s*"   # start_time optional
    r"(\d{1,2}:\d{2}\s*(?:AM|PM))?\s*"   # end_time   optional
    r"(.+?)\s+"                            # faculty
    r"([A-Z]{2,6})\s+"                    # building   e.g. DHAL
    r"(\S+)\s+"                            # room
    r"(LEC|LAB|SEM|INT|STU|WRK|IND)$",   # type
    re.IGNORECASE,
)

# Simpler fallback for rows where building/room may be absent
SCHEDULE_ROW_SHORT = re.compile(
    r"^([A-Z]{2,4}-\d{3,4}[A-Z]?)\s+"
    r"(\S+)\s+"
    r"(\d+)\s+"
    r"(.+?)\s+"
    r"(MC|GC|OL|ONLINE|TBA)\s*"
    r"([MTWRFSU]+|TBA)?\s*"
    r"(\d{1,2}:\d{2}\s*(?:AM|PM))?\s*"
    r"(\d{1,2}:\d{2}\s*(?:AM|PM))?\s*"
    r"(.*)$",
    re.IGNORECASE,
)


def parse_schedule_line(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None

    # Try full pattern first
    m = SCHEDULE_ROW.match(line)
    if m:
        cid, sec, cr, title, loc, days, start, end, faculty, bldg, room, typ = m.groups()
        faculty = faculty.strip()
        if faculty.lower() in ("to be announced", "tba", ""):
            faculty = None
        return {
            "course_id": cid.upper(),
            "section": sec,
            "credits": safe_int(cr),
            "title": title.strip(),
            "location": loc.upper(),
            "days": parse_day_string(days or ""),
            "start_time": normalize_time(start or ""),
            "end_time": normalize_time(end or ""),
            "faculty": faculty or None,
            "building": bldg.upper() if bldg else None,
            "room": room.strip() if room else None,
            "type": typ.upper() if typ else "LEC",
        }

    # Try shorter pattern
    m2 = SCHEDULE_ROW_SHORT.match(line)
    if m2:
        cid, sec, cr, title, loc, days, start, end, rest = m2.groups()
        # Try to extract type from end of rest
        typ = None
        if rest:
            type_match = re.search(r"\b(LEC|LAB|SEM|INT|STU|WRK|IND)\b", rest)
            if type_match:
                typ = type_match.group(1).upper()

        faculty = rest.strip() if rest else None
        if faculty:
            faculty = re.sub(r"\b(LEC|LAB|SEM|INT|STU|WRK|IND)\b", "", faculty).strip()
            if faculty.lower() in ("to be announced", "tba", ""):
                faculty = None

        return {
            "course_id": cid.upper(),
            "section": sec,
            "credits": safe_int(cr),
            "title": title.strip(),
            "location": loc.upper(),
            "days": parse_day_string(days or ""),
            "start_time": normalize_time(start or ""),
            "end_time": normalize_time(end or ""),
            "faculty": faculty or None,
            "building": None,
            "room": None,
            "type": typ or "LEC",
        }

    return None


def parse_schedule_pdf(pdf_path: Path, term: str) -> List[Dict[str, Any]]:
    courses: List[Dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                # Skip headers and blank lines
                if not line:
                    continue
                if re.match(r"^(COURSE|Spring|Summer|Fall|Winter|Page)", line, re.IGNORECASE):
                    continue
                entry = parse_schedule_line(line)
                if entry and entry["course_id"]:
                    courses.append(entry)
    return courses


# ---------------------------------------------------------------------------
# Summer Online parser (different format: no days, uses date ranges)
# ---------------------------------------------------------------------------

ONLINE_ROW = re.compile(
    r"^([A-Z]{2,4}-\d{3,4}[A-Z]?)\s+"   # course_id
    r"(\S+)\s+"                            # section
    r"(\d+)\s+"                            # credits
    r"(.+?)\s+"                            # title
    r"(ONLINE|OL)\s+"                      # location
    r"(\d{2}/\d{2}/\d{4})\s+"             # start_date
    r"(\d{2}/\d{2}/\d{4})\s+"             # end_date
    r"(.*)$",                              # faculty + rest
    re.IGNORECASE,
)


def parse_online_schedule_pdf(pdf_path: Path, term: str) -> List[Dict[str, Any]]:
    courses: List[Dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if re.match(r"^(COURSE|Spring|Summer|Fall|Session|Page|Winter)", line, re.IGNORECASE):
                    continue
                m = ONLINE_ROW.match(line)
                if m:
                    cid, sec, cr, title, loc, start_date, end_date, rest = m.groups()
                    faculty = rest.strip() or None
                    if faculty and faculty.lower() in ("to be announced", "tba"):
                        faculty = None
                    courses.append({
                        "course_id": cid.upper(),
                        "section": sec,
                        "credits": safe_int(cr),
                        "title": title.strip(),
                        "location": "ONLINE",
                        "days": [],
                        "start_date": start_date,
                        "end_date": end_date,
                        "start_time": None,
                        "end_time": None,
                        "faculty": faculty,
                        "building": None,
                        "room": None,
                        "type": "LEC",
                    })
    return courses


# ---------------------------------------------------------------------------
# Catalog parser
# ---------------------------------------------------------------------------

# Course description header: "CSC 1058 Computer Programming I  4 credits"
CATALOG_COURSE_HEADER = re.compile(
    r"^([A-Z]{2,4})\s+(\d{3,4}[A-Z]?)\s+(.+?)\s+(\d+(?:\.\d+)?)\s+credits?$",
    re.IGNORECASE,
)

PREREQ_LINE = re.compile(
    r"(?:Prerequisite|Corequisite|Pre-?req)[s]?\s*[:;]\s*(.+)",
    re.IGNORECASE,
)

OFFERED_TERMS_MAP = {
    "fall": "Fall",
    "spring": "Spring",
    "summer": "Summer",
}


def parse_prereqs(text: str) -> List[str]:
    """Extract prerequisite course codes from a prerequisite line."""
    codes = re.findall(r"[A-Z]{2,4}\s*[-]?\s*\d{3,4}[A-Z]?", text, re.IGNORECASE)
    return [re.sub(r"\s+", " ", c.strip().upper()) for c in codes]


def normalize_catalog_course_id(dept: str, num: str) -> str:
    return f"{dept.upper()}-{num.upper()}"


def parse_catalog_pdf(pdf_path: Path) -> List[Dict[str, Any]]:
    """
    Parse the LU catalog PDF for course descriptions.
    Returns a list of course dicts.
    """
    courses: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    desc_lines: List[str] = []

    def flush():
        nonlocal current, desc_lines
        if current:
            description = " ".join(desc_lines).strip()
            current["description"] = description if description else None
            courses.append(current)
        current = None
        desc_lines = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Skip page numbers and headers
                if re.match(r"^\d+$", line):
                    continue
                if re.match(r"LINCOLN UNIVERSITY\s*\d*", line, re.IGNORECASE):
                    continue

                m = CATALOG_COURSE_HEADER.match(line)
                if m:
                    flush()
                    dept, num, title, credits = m.groups()
                    current = {
                        "course_id": normalize_catalog_course_id(dept, num),
                        "title": title.strip(),
                        "credits": safe_int(credits),
                        "prerequisites": [],
                        "offered_semesters": ["Fall", "Spring"],  # default
                        "description": None,
                    }
                    desc_lines = []
                    continue

                if current:
                    prereq_m = PREREQ_LINE.search(line)
                    if prereq_m:
                        current["prerequisites"] = parse_prereqs(prereq_m.group(1))
                        continue

                    # Check for offered terms
                    lower = line.lower()
                    found_terms = [v for k, v in OFFERED_TERMS_MAP.items() if k in lower]
                    if found_terms and len(line) < 80:
                        current["offered_semesters"] = list(set(found_terms))
                        continue

                    desc_lines.append(line)

    flush()
    return courses


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_schedule(schedule: List[Dict], catalog: List[Dict], schedule_name: str):
    catalog_ids = {c["course_id"] for c in catalog}
    warnings = []
    null_ids = [e for e in schedule if not e.get("course_id")]
    if null_ids:
        warnings.append(f"  WARNING: {len(null_ids)} entries with null course_id")

    null_credits = [e for e in schedule if e.get("credits") is None]
    if null_credits:
        warnings.append(f"  WARNING: {len(null_credits)} entries with null credits")

    unmatched = {e["course_id"] for e in schedule if e.get("course_id") and e["course_id"] not in catalog_ids}
    if unmatched:
        warnings.append(f"  INFO: {len(unmatched)} schedule course_ids not in catalog (expected for labs/special sections)")

    if warnings:
        print(f"\nValidation [{schedule_name}]:")
        for w in warnings:
            print(w)
    else:
        print(f"  [{schedule_name}] Validation passed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("GradPath PDF Parser")
    print("=" * 60)

    # --- Parse catalog ---
    catalog_pdf = CATALOGS_DIR / "2025_26-Catalog_1282026.pdf"
    print(f"\n[1/4] Parsing catalog: {catalog_pdf.name}")
    catalog = parse_catalog_pdf(catalog_pdf)
    # Deduplicate by course_id (keep last — later descriptions win)
    seen: Dict[str, Dict] = {}
    for c in catalog:
        seen[c["course_id"]] = c
    catalog = list(seen.values())
    catalog_out = CATALOGS_DIR / "catalog_2026.json"
    with catalog_out.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)
    print(f"  -> {len(catalog)} courses written to {catalog_out.name}")

    # --- Parse Spring 2026 ---
    spring_pdf = SCHEDULES_DIR / "COURSE_SCHEDULE2026SPNEW.pdf"
    print(f"\n[2/4] Parsing spring schedule: {spring_pdf.name}")
    spring = parse_schedule_pdf(spring_pdf, "Spring 2026")
    spring_out = SCHEDULES_DIR / "spring_2026.json"
    with spring_out.open("w", encoding="utf-8") as f:
        json.dump(spring, f, indent=2)
    print(f"  -> {len(spring)} sections written to {spring_out.name}")
    validate_schedule(spring, catalog, "spring_2026")

    # --- Parse Summer 2026 GC ---
    summer_gc_pdf = SCHEDULES_DIR / "COURSE_SCHEDULE2026SU_GCNEW.pdf"
    print(f"\n[3/4] Parsing summer GC schedule: {summer_gc_pdf.name}")
    summer_gc = parse_schedule_pdf(summer_gc_pdf, "Summer 2026 GC")
    summer_gc_out = SCHEDULES_DIR / "summer_2026_gc.json"
    with summer_gc_out.open("w", encoding="utf-8") as f:
        json.dump(summer_gc, f, indent=2)
    print(f"  -> {len(summer_gc)} sections written to {summer_gc_out.name}")
    validate_schedule(summer_gc, catalog, "summer_2026_gc")

    # --- Parse Summer 2026 Online ---
    summer_ol_pdf = SCHEDULES_DIR / "COURSE_SCHEDULE2026SU_OLNEW.pdf"
    print(f"\n[4/4] Parsing summer online schedule: {summer_ol_pdf.name}")
    summer_ol = parse_online_schedule_pdf(summer_ol_pdf, "Summer 2026 Online")
    summer_ol_out = SCHEDULES_DIR / "summer_2026_ol.json"
    with summer_ol_out.open("w", encoding="utf-8") as f:
        json.dump(summer_ol, f, indent=2)
    print(f"  -> {len(summer_ol)} sections written to {summer_ol_out.name}")
    validate_schedule(summer_ol, catalog, "summer_2026_ol")

    # --- Final summary ---
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  catalog_2026.json      : {len(catalog):>4} courses")
    print(f"  spring_2026.json       : {len(spring):>4} sections")
    print(f"  summer_2026_gc.json    : {len(summer_gc):>4} sections")
    print(f"  summer_2026_ol.json    : {len(summer_ol):>4} sections")
    print()
    print("Note: COURSE_SCHEDULE2025FA.pdf was not found in data/schedules/.")
    print("      Fall 2026 schedule was NOT generated — no source PDF available.")
    print("      Add the PDF to data/schedules/ and re-run to generate fall_2026.json.")


if __name__ == "__main__":
    main()
