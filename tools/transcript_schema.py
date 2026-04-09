"""Pydantic schemas for normalized transcript extraction results."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


PLANNER_COURSE_EQUIVALENTS = {
    # Variant/abbreviated codes found on real LU transcripts -> canonical catalog IDs (dash format)
    "CSC158": "CSC-1058",
    "CSC159": "CSC-1059",
    "CSC1058": "CSC-1058",
    "CSC1059": "CSC-1059",
    "CSC2001": "CSC-2001",
    "CSC2054": "CSC-2054",
    "CSC3002": "CSC-3002",
    "CSC3053": "CSC-3053",
    "CSC3054": "CSC-3054",
    "CSC3055": "CSC-3055",
    "CSC3058": "CSC-3058",
    "CSC3059": "CSC-3059",
    "CSC3090": "CSC-3090",
    "CSC3095": "CSC-3095",
    "CSC4054": "CSC-4054",
    "CSC4057": "CSC-4057",
    "CSC4098": "CSC-4098",
    "ENG101": "ENG-1001",
    "ENG1001": "ENG-1001",
    "ENG102": "ENG-1002",
    "ENG1002": "ENG-1002",
    "MAT101": "MAT-1010",
    "MAT110": "MAT-1010",
    "MAT1010": "MAT-1010",
    "MAT1014": "MAT-1014",
    "MAT2013": "MAT-2013",
    "BIO101": "BIO-1001",
    "BIO1001": "BIO-1001",
    "BIO102": "BIO-1002",
    "BIO1002": "BIO-1002",
    "SOC101": "SOC-1001",
    "SOC1001": "SOC-1001",
    "PSY101": "PSY-1001",
    "PSY1001": "PSY-1001",
    "HIS103": "HIS-1003",
    "HIS1003": "HIS-1003",
    "SOS1051": "SOS-1051",
    "ART2000": "ART-2000",
    "FIN1001": "FIN-1001",
    "FIN3041": "FIN-3041",
    "ECO2002": "ECO-2002",
    "ECO2003": "ECO-2003",
    "GSC1001": "GSC-1001",
    "GSC1002": "GSC-1002",
    "MAT1001": "MAT-1001",
}

PLANNER_TITLE_EQUIVALENTS = {
    # Title-based fallback -> canonical catalog IDs (dash format)
    "computer programming i": "CSC-1058",
    "computer program i": "CSC-1058",
    "intro to programming": "CSC-1052",
    "computer programming ii": "CSC-1059",
    "data structures": "CSC-2054",
    "web design and development": "CSC-2001",
    "web design & development": "CSC-2001",
    "web programming": "CSC-2001",
    "database design & development": "CSC-3054",
    "database design and development": "CSC-3054",
    "database systems": "CSC-3054",
    "computer organization and assembly language": "CSC-3053",
    "computer orgnztn & archictr": "CSC-3053",
    "computer organization": "CSC-3053",
    "operating systems with linux": "CSC-3055",
    "operating systems w/ linux": "CSC-3055",
    "software engineering": "CSC-4054",
    "computer networking and security": "CSC-4057",
    "elementary statistics i": "MAT-1014",
    "elementary statistics": "MAT-1014",
    "discrete mathematics": "MAT-2013",
    "college algebra": "MAT-1010",
    "elem & intermediate algebra": "MAT-1010",
    "elem and intermediate algebra": "MAT-1010",
    "english composition i": "ENG-1001",
    "english comp i": "ENG-1001",
    "english composition ii": "ENG-1002",
    "english comp ii": "ENG-1002",
    "intro to sociology": "SOC-1001",
    "introduction to sociology": "SOC-1001",
    "general psychology": "PSY-1001",
    "world history": "HIS-1003",
    "african american experience": "SOS-1051",
    "introduction to art": "ART-2000",
    "personal finance": "FIN-1001",
    "financial management": "FIN-3041",
    "principles of microeconomics": "ECO-2002",
    "physical science ii": "GSC-1002",
    "human health and disease": "BIO-1002",
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
    # Computer Science
    "computer science": "CS",
    "cs": "CS",
    # Biology
    "biology": "BIO",
    "bio": "BIO",
    # Chemistry
    "chemistry": "CHE",
    # Biochemistry
    "biochemistry": "BIOCHEM",
    "biochemistry and molecular biology": "BIOCHEM",
    # Forensic Science
    "forensic science": "FORENSIC",
    "chemistry forensic science": "FORENSIC",
    "chemistry: forensic science concentration": "FORENSIC",
    # Environmental Science
    "environmental science": "ENV",
    "environmental studies": "ENV",
    # Physics
    "physics": "PHY",
    # Health Science
    "health science": "HSC",
    "health sciences": "HSC",
    # Communication
    "communication": "COM",
    "communications": "COM",
    # Mathematics
    "mathematics": "MAT",
    "math": "MAT",
    "mathematical sciences": "MAT",
    # History
    "history": "HIS",
    # Philosophy
    "philosophy": "PHL",
    # Music
    "music": "MUS",
    # Pan-Africana Studies
    "pan-africana studies": "PAS",
    "pan africana studies": "PAS",
    "black studies": "PAS",
    # Political Science
    "political science": "POL",
    "politics": "POL",
    # Psychology
    "psychology": "PSY",
    # Human Services
    "human services": "HUS",
    # Visual Arts
    "visual arts": "ART",
    "art": "ART",
    "fine arts": "ART",
    # Sociology
    "sociology": "SOC",
    # English
    "english": "ENG",
    "english liberal arts": "ENG",
    "english literature": "ENG",
    # Accounting
    "accounting": "ACC",
    # Finance
    "finance": "FIN",
    # Management
    "management": "MGT",
    # Information Systems
    "information systems management": "ISM",
    "information systems": "ISM",
    # Criminal Justice
    "criminal justice": "CRJ",
    # Anthropology
    "anthropology": "ANT",
    # Religion
    "religion": "REL",
    "religious studies": "REL",
    # French
    "french": "FRE",
    # Spanish
    "spanish": "SPN",
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
    ("PHY",): "PHY",
    ("COM",): "COM",
    ("MAT",): "MAT",
    ("HIS",): "HIS",
    ("PHL",): "PHL",
    ("MUS",): "MUS",
    ("PAS",): "PAS",
    ("POL",): "POL",
    ("PSY",): "PSY",
    ("HUS",): "HUS",
    ("ART", "ARH", "MSM"): "ART",
    ("SOC",): "SOC",
    ("ENG",): "ENG",
    ("ENV", "GSC", "ENS"): "ENV",
    ("REL",): "REL",
    ("FRE",): "FRE",
    ("SPN",): "SPN",
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
    compact_code = course_code.replace(" ", "").replace("-", "").upper()
    if compact_code in PLANNER_COURSE_EQUIVALENTS:
        return PLANNER_COURSE_EQUIVALENTS[compact_code]

    normalized_title = re.sub(r"\s+", " ", course_title.strip().lower())
    if normalized_title in PLANNER_TITLE_EQUIVALENTS:
        return PLANNER_TITLE_EQUIVALENTS[normalized_title]

    # Convert raw code to dash format: "CSC1058" -> "CSC-1058", "ENG 1001" -> "ENG-1001"
    m = re.match(r"([A-Z]{2,5})\s*-?\s*(\d{3,4}[A-Z]?)", course_code.strip().upper())
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    return compact_code
