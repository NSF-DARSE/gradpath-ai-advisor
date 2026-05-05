"""Integration tests for GradPath.

Integration tests verify that two or more real components work correctly
together using real data files. No mocking, no LLM, no network.

Components under test and their interactions:
  - transcript_parser  ↔  transcript_schema  (parse → Pydantic → planner profile)
  - catalog_tools      ↔  major_requirements  (required courses exist in catalog)
  - catalog_tools      ↔  catalog_tools       (prerequisites reference real courses)
  - schedule_tools     ↔  catalog_tools       (scheduled courses exist in catalog)
  - student_tools      ↔  catalog_tools       (profile → required → prerequisites chain)
"""

from __future__ import annotations

import unittest

from tools.catalog_tools import (
    get_course_prerequisites,
    get_required_courses,
    load_catalog_data,
    load_major_requirements,
)
from tools.schedule_tools import get_offered_course_ids
from tools.student_tools import load_student_profile
from tools.transcript_parser import parse_transcript_text


# ---------------------------------------------------------------------------
# Known data gaps (lab sections and cross-listed courses not in catalog_2026.json)
# These are documented here so failures are immediately understandable.
# ---------------------------------------------------------------------------

_KNOWN_PREREQ_GAPS = {
    # Biology lab sections — listed as prereqs but catalogued separately
    "BIO-1001L", "BIO-1002L", "BIO-1003L", "BIO-1004L", "BIO-1005",
    "BIO-2005L", "BIO-2006L", "BIO-2007L", "BIO-2008L",
    "BIO-3002L", "BIO-3004L", "BIO-3008L", "BIO-3009L", "BIO-3010L", "BIO-3012L",
    "BIO-4001L", "BIO-4002L", "BIO-4005L", "BIO-4007L", "BIO-4008L", "BIO-4012L",
    # Chemistry lab sections
    "CHE-1004L", "CHE-1020L", "CHE-2003L", "CHE-2004L", "CHE-2005L", "CHE-2055L",
    "CHE-3001L", "CHE-3003L", "CHE-3004L", "CHE-4002L",
    # Physics lab sections
    "PHY-1004L", "PHY-1005L", "PHY-1006L",
    # MBA/graduate courses referenced as prereqs
    "MBA-712", "MBA-742", "MBA-756",
    # Other cross-listed or missing courses
    "ECO-2001", "ECO-2002", "ACC-2003", "COM-2000", "COM-4052",
    "HSC-2001", "HSC-4006", "ENG-102", "MUS-2019", "ART-2020",
    "ANY-2000", "OF-4000", "MSEG-3010",
}

# Minimum percentage of scheduled courses that must exist in the catalog.
# The schedule includes lab sections, special topics, and visiting courses
# that are not always in catalog_2026.json — 75% coverage is the threshold.
_SCHEDULE_CATALOG_COVERAGE_THRESHOLD = 0.75

_TRANSCRIPT_FIXTURE = """
Lincoln University
Student Name: Casey Lee
Student ID: 7700002
Program: Computer Science
Cumulative GPA: 3.55
Total Credits Completed: 24

Fall 2023
ENG1001    English Composition I         4.00  A
MAT1010    College Algebra               4.00  B+
CSC1058    Computer Programming I        4.00  A
Term GPA: 3.75

Spring 2024
ENG1002    English Composition II        4.00  B+
CSC1059    Computer Programming II       4.00  A-
MAT1014    Elementary Statistics I       4.00  B
Term GPA: 3.40
"""


# ---------------------------------------------------------------------------
# 1. Parser ↔ Schema handoff
# ---------------------------------------------------------------------------

class ParserSchemaIntegrationTests(unittest.TestCase):
    """Verify that parse_transcript_text output passes through Pydantic
    validation and produces a correctly shaped planner profile."""

    def setUp(self) -> None:
        result = parse_transcript_text(_TRANSCRIPT_FIXTURE, extraction_method="text")
        self.assertEqual(result.status, "success", f"Parse failed: {result.message}")
        assert result.transcript is not None
        self.transcript = result.transcript
        self.profile = result.transcript.to_planner_profile()

    def test_pydantic_model_is_valid_after_parse(self) -> None:
        # model_dump() round-trips through Pydantic validation — will raise if schema is violated
        dumped = self.transcript.model_dump()
        self.assertIn("student", dumped)
        self.assertIn("terms", dumped)
        self.assertIn("completed_courses", dumped)

    def test_profile_has_all_required_keys(self) -> None:
        required_keys = {
            "student_id", "student_name", "major", "current_semester",
            "completed_courses", "in_progress_courses", "status", "source",
        }
        self.assertEqual(required_keys, required_keys & set(self.profile.keys()))

    def test_every_completed_course_in_profile_has_required_fields(self) -> None:
        for course in self.profile["completed_courses"]:
            self.assertIn("course_id", course, f"Missing course_id in {course}")
            self.assertIn("grade", course, f"Missing grade in {course}")
            self.assertIn("term", course, f"Missing term in {course}")
            self.assertIsInstance(course["course_id"], str)
            self.assertGreater(len(course["course_id"]), 0)

    def test_major_resolves_to_known_value_not_raw_program_text(self) -> None:
        # "Computer Science" should map to "CS", not remain as the raw text
        self.assertEqual(self.profile["major"], "CS")

    def test_current_semester_matches_last_term_in_transcript(self) -> None:
        last_term = self.transcript.terms[-1].term
        self.assertEqual(self.profile["current_semester"], last_term)


# ---------------------------------------------------------------------------
# 2. Catalog ↔ Major requirements
# ---------------------------------------------------------------------------

class CatalogMajorRequirementsIntegrationTests(unittest.TestCase):
    """Verify that every course listed in major_requirements.json
    actually exists in catalog_2026.json."""

    def setUp(self) -> None:
        catalog = load_catalog_data()
        self.catalog_ids = {c["course_id"] for c in catalog}
        self.requirements = load_major_requirements()

    def test_all_required_courses_exist_in_catalog(self) -> None:
        missing = {}
        for major, data in self.requirements.items():
            for course_id in data.get("required_courses", []):
                if course_id not in self.catalog_ids:
                    missing.setdefault(major, []).append(course_id)

        self.assertEqual(
            missing,
            {},
            f"Required courses missing from catalog — planner will silently skip them: {missing}",
        )

    def test_all_majors_have_at_least_one_required_course(self) -> None:
        for major, data in self.requirements.items():
            courses = data.get("required_courses", [])
            self.assertGreater(
                len(courses), 0,
                f"Major '{major}' has no required courses defined in major_requirements.json",
            )

    def test_get_required_courses_returns_list_for_every_major(self) -> None:
        for major in self.requirements:
            result = get_required_courses(major)
            self.assertIsInstance(result, list)
            self.assertGreater(len(result), 0, f"get_required_courses('{major}') returned empty list")


# ---------------------------------------------------------------------------
# 3. Prerequisite self-consistency within the catalog
# ---------------------------------------------------------------------------

class PrerequisiteConsistencyIntegrationTests(unittest.TestCase):
    """Verify that prerequisite course IDs reference real courses.

    Known gaps (lab sections, MBA courses) are allowlisted so the test
    documents them without failing — a CI alert for new unknown gaps.
    """

    def setUp(self) -> None:
        catalog = load_catalog_data()
        self.catalog_ids = {c["course_id"] for c in catalog}
        self.all_prereqs = []
        for course in catalog:
            for prereq in get_course_prerequisites(course["course_id"]):
                self.all_prereqs.append((course["course_id"], prereq))

    def test_no_unknown_prerequisite_gaps(self) -> None:
        unknown_gaps = [
            (course, prereq)
            for course, prereq in self.all_prereqs
            if prereq not in self.catalog_ids and prereq not in _KNOWN_PREREQ_GAPS
        ]
        self.assertEqual(
            unknown_gaps,
            [],
            f"New prerequisite IDs found that are not in the catalog or the known-gaps list: {unknown_gaps}",
        )

    def test_known_prereq_gaps_are_documented(self) -> None:
        # Confirm the known gaps still exist — if a gap is fixed, remove it from _KNOWN_PREREQ_GAPS
        actual_gaps = {
            prereq
            for _, prereq in self.all_prereqs
            if prereq not in self.catalog_ids
        }
        undocumented = actual_gaps - _KNOWN_PREREQ_GAPS
        self.assertEqual(
            undocumented,
            set(),
            f"New undocumented prerequisite gaps appeared — add to _KNOWN_PREREQ_GAPS: {undocumented}",
        )


# ---------------------------------------------------------------------------
# 4. Schedule ↔ Catalog consistency
# ---------------------------------------------------------------------------

class ScheduleCatalogIntegrationTests(unittest.TestCase):
    """Verify that the majority of scheduled courses exist in the catalog.
    The schedule includes lab sections and special-topics courses that are
    intentionally absent from catalog_2026.json — the threshold test
    catches large-scale data drift without requiring an exact allowlist."""

    def setUp(self) -> None:
        catalog = load_catalog_data()
        self.catalog_ids = {c["course_id"] for c in catalog}

    def _check_coverage(self, semester: str) -> None:
        offered = set(get_offered_course_ids(semester))
        if not offered:
            self.fail(f"No courses found for semester '{semester}' — check schedule JSON.")
        in_catalog = offered & self.catalog_ids
        coverage = len(in_catalog) / len(offered)
        self.assertGreaterEqual(
            coverage,
            _SCHEDULE_CATALOG_COVERAGE_THRESHOLD,
            f"Only {coverage:.0%} of '{semester}' schedule courses exist in the catalog "
            f"(threshold: {_SCHEDULE_CATALOG_COVERAGE_THRESHOLD:.0%}). "
            f"Missing: {offered - self.catalog_ids}",
        )

    def test_fall_2026_schedule_has_sufficient_catalog_coverage(self) -> None:
        self._check_coverage("Fall 2026")

    def test_spring_2026_schedule_has_sufficient_catalog_coverage(self) -> None:
        self._check_coverage("Spring 2026")

    def test_schedule_returns_non_empty_list(self) -> None:
        for semester in ("Fall 2026", "Spring 2026"):
            offered = get_offered_course_ids(semester)
            self.assertGreater(len(offered), 0, f"No courses found for '{semester}'")


# ---------------------------------------------------------------------------
# 5. Student tools ↔ Catalog tools chain
# ---------------------------------------------------------------------------

class PlannerToolsChainIntegrationTests(unittest.TestCase):
    """Verify the full data-access chain: student profile → required courses
    → prerequisites, all reading from real files and returning consistent data."""

    STUDENT_ID = "s1001"
    MAJOR = "CS"

    def test_load_student_profile_returns_ready_status(self) -> None:
        profile = load_student_profile(self.STUDENT_ID)
        self.assertEqual(profile.get("status"), "ready")
        self.assertIn("completed_courses", profile)

    def test_required_courses_for_student_major_are_non_empty(self) -> None:
        profile = load_student_profile(self.STUDENT_ID)
        major = profile.get("major", self.MAJOR)
        required = get_required_courses(major)
        self.assertGreater(len(required), 0)

    def test_prerequisites_resolve_for_all_cs_required_courses(self) -> None:
        required = get_required_courses(self.MAJOR)
        catalog = load_catalog_data()
        catalog_ids = {c["course_id"] for c in catalog}

        for course_id in required:
            prereqs = get_course_prerequisites(course_id)
            for prereq in prereqs:
                self.assertIn(
                    prereq,
                    catalog_ids,
                    f"Prerequisite '{prereq}' for CS required course '{course_id}' is not in the catalog",
                )

    def test_completed_courses_in_profile_are_strings(self) -> None:
        profile = load_student_profile(self.STUDENT_ID)
        for course in profile.get("completed_courses", []):
            self.assertIsInstance(
                course.get("course_id"), str,
                f"Non-string course_id found in s1001 profile: {course}",
            )


if __name__ == "__main__":
    unittest.main()
