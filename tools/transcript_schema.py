"""Pydantic schemas for normalized transcript extraction results."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


PLANNER_COURSE_EQUIVALENTS = {
    # Variant/abbreviated codes found on real LU transcripts -> canonical catalog IDs
    "CSC158": "CSC1058",
    "CSC159": "CSC1059",
    "ENG101": "ENG1001",
    "ENG102": "ENG1002",
    "MAT101": "MAT1010",
    "MAT110": "MAT1010",
    "MAT102": "MAT1014",
    "BIO101": "BIO1001",
    "BIO102": "BIO1002",
    "SOC101": "SOC1001",
    "PSY101": "PSY1001",
    "HIS103": "HIS1003",
}

PLANNER_TITLE_EQUIVALENTS = {
    # Title-based fallback -> canonical catalog IDs
    "computer programming i": "CSC1058",
    "computer program i": "CSC1058",
    "intro to programming": "CSC1052",
    "computer programming ii": "CSC1059",
    "data structures": "CSC2054",
    "web design and development": "CSC2001",
    "web programming": "CSC2001",
    "database design & development": "CSC3054",
    "database design and development": "CSC3054",
    "database systems": "CSC3054",
    "computer organization and assembly language": "CSC3053",
    "computer orgnztn & archictr": "CSC3053",
    "computer organization": "CSC3053",
    "operating systems with linux": "CSC3055",
    "operating systems w/ linux": "CSC3055",
    "software engineering": "CSC4054",
    "computer networking and security": "CSC4057",
    "elementary statistics i": "MAT1014",
    "elementary statistics": "MAT1014",
    "discrete mathematics": "MAT2013",
    "college algebra": "MAT1010",
    "english composition i": "ENG1001",
    "english comp i": "ENG1001",
    "english composition ii": "ENG1002",
    "english comp ii": "ENG1002",
    "intro to sociology": "SOC1001",
    "introduction to sociology": "SOC1001",
    "general psychology": "PSY1001",
    "world history": "HIS1003",
}


class TranscriptStudent(BaseModel):
    """Core student identity fields extracted from a transcript."""

    name: Optional[str] = None
    student_id: Optional[str] = None
    institution: Optional[str] = None
    program: Optional[str] = None


class AcademicSummary(BaseModel):
    """Roll-up academic values that are commonly printed on transcripts."""

    cumulative_gpa: Optional[float] = None
    total_credits_completed: Optional[float] = None


class TranscriptCourse(BaseModel):
    """One normalized course row."""

    course_code: str
    course_title: str
    credits: float
    grade: Optional[str] = None

    def dedupe_key(self, term: Optional[str] = None) -> tuple[str, Optional[str], str, float, Optional[str]]:
        """Return a stable key so repeated transcript rows can be removed safely."""

        return (
            self.course_code.upper(),
            term,
            self.course_title.strip().lower(),
            float(self.credits),
            self.grade,
        )


class TranscriptTerm(BaseModel):
    """A term block and its courses."""

    term: str
    term_gpa: Optional[float] = None
    courses: List[TranscriptCourse] = Field(default_factory=list)


class CompletedCourseRecord(BaseModel):
    """Flattened course view used by downstream planning."""

    term: Optional[str] = None
    course_code: str
    course_title: str
    credits: float
    grade: Optional[str] = None


class TranscriptDocument(BaseModel):
    """Fully normalized transcript payload shared across GradPath agents."""

    student: TranscriptStudent = Field(default_factory=TranscriptStudent)
    academic_summary: AcademicSummary = Field(default_factory=AcademicSummary)
    terms: List[TranscriptTerm] = Field(default_factory=list)
    completed_courses: List[CompletedCourseRecord] = Field(default_factory=list)
    raw_text_excerpt: Optional[str] = None

    def to_planner_profile(self) -> Dict[str, Any]:
        """Adapt transcript JSON into the profile shape already used by GradPath."""

        current_semester = self.terms[-1].term if self.terms else "Unknown"
        completed_courses = [
            {
                "course_id": _map_course_to_planner_id(course.course_code, course.course_title),
                "source_course_code": course.course_code,
                "source_course_title": course.course_title,
                "term": course.term,
                "grade": course.grade,
                "credits": int(course.credits) if float(course.credits).is_integer() else course.credits,
            }
            for course in self.completed_courses
        ]
        return {
            "student_id": self.student.student_id or "uploaded-transcript",
            "student_name": self.student.name or "Uploaded Student",
            "major": _normalize_major(self.student.program, self.completed_courses),
            "current_semester": current_semester,
            "completed_courses": completed_courses,
            "status": "ready",
            "source": "uploaded_transcript",
        }


_PROGRAM_TO_MAJOR = {
    "computer science": "CS",
    "cs": "CS",
    "biology": "BIO",
    "bio": "BIO",
    "chemistry": "CHE",
    "biochemistry": "BIOCHEM",
    "biochemistry and molecular biology": "BIOCHEM",
    "health science": "HSC",
    "health sciences": "HSC",
    "accounting": "ACC",
    "finance": "FIN",
    "management": "MGT",
    "information systems management": "ISM",
    "information systems": "ISM",
    "criminal justice": "CRJ",
    "anthropology": "ANT",
}

_PREFIX_TO_MAJOR = {
    ("CSC", "CISC"): "CS",
    ("BIO",): "BIO",
    ("CHE",): "CHE",
    ("HSC",): "HSC",
    ("ACC",): "ACC",
    ("FIN",): "FIN",
    ("MGT",): "MGT",
    ("INF",): "ISM",
    ("CRJ",): "CRJ",
    ("ANT",): "ANT",
}


_GENERIC_PROGRAM_LABELS = {
    "undergraduate", "undergrad", "undeclared", "general", "n/a", "unknown", "",
}


def _normalize_major(program: Optional[str], completed_courses: List[CompletedCourseRecord]) -> str:
    if program:
        key = program.strip().lower()
        if key in _PROGRAM_TO_MAJOR:
            return _PROGRAM_TO_MAJOR[key]

    # Try inferring from course prefixes before giving up
    course_codes = [course.course_code.replace(" ", "").upper() for course in completed_courses]
    for prefixes, major in _PREFIX_TO_MAJOR.items():
        if any(code.startswith(prefixes) for code in course_codes):
            return major

    # Generic labels on transcripts (e.g. "Undergraduate") mean major is not declared
    if program and program.strip().lower() in _GENERIC_PROGRAM_LABELS:
        return "Unknown"

    return program or "Unknown"


def _map_course_to_planner_id(course_code: str, course_title: str) -> str:
    compact_code = course_code.replace(" ", "").upper()
    if compact_code in PLANNER_COURSE_EQUIVALENTS:
        return PLANNER_COURSE_EQUIVALENTS[compact_code]

    normalized_title = re.sub(r"\s+", " ", course_title.strip().lower())
    if normalized_title in PLANNER_TITLE_EQUIVALENTS:
        return PLANNER_TITLE_EQUIVALENTS[normalized_title]

    return compact_code
