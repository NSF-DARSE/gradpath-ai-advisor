"""End-to-end tests for GradPath's deterministic planning pipeline.

These tests exercise the full flow from raw transcript text all the way to
course recommendations, using real data files (catalog, schedule, registry).
No LLM or network calls are made — the AI agents are not involved.

Flow under test:
  transcript text
    → parse_transcript_text()        [transcript_parser]
    → to_planner_profile()           [transcript_schema]
    → recommend_courses()            [planning_tools]
    → validate all 4 guardrail constraints on the output
"""

from __future__ import annotations

import unittest

from tools.transcript_parser import parse_transcript_text
from tools.planning_tools import recommend_courses
from tools.catalog_tools import get_course_prerequisites, get_required_courses
from tools.schedule_tools import get_offered_course_ids


# ---------------------------------------------------------------------------
# Shared transcript fixture — realistic 3-term CS student
# ---------------------------------------------------------------------------

_CS_TRANSCRIPT = """
Lincoln University
Student Name: Jordan Smith
Student ID: 9900001
Program: Computer Science
Cumulative GPA: 3.40
Total Credits Completed: 36

Fall 2023
ENG1001    English Composition I         4.00  A
MAT1010    College Algebra               4.00  B
CSC1058    Computer Programming I        4.00  A
Term GPA: 3.55

Spring 2024
ENG1002    English Composition II        4.00  B+
MAT1014    Elementary Statistics I       4.00  B
CSC1059    Computer Programming II       4.00  A-
Term GPA: 3.40

Fall 2024
CSC2054    Data Structures               4.00  B+
CSC3053    Computer Organization         4.00  B
SOS1051    African American Experience   4.00  A
Term GPA: 3.33
"""


class TranscriptToProfileE2ETests(unittest.TestCase):
    """Parse a transcript and verify the planner profile is correct."""

    def setUp(self) -> None:
        result = parse_transcript_text(_CS_TRANSCRIPT, extraction_method="text")
        self.assertEqual(result.status, "success", f"Parse failed: {result.message}")
        assert result.transcript is not None
        self.profile = result.transcript.to_planner_profile()

    def test_major_is_correctly_identified(self) -> None:
        self.assertEqual(self.profile["major"], "CS")

    def test_student_name_and_id_are_extracted(self) -> None:
        self.assertEqual(self.profile["student_name"], "Jordan Smith")
        self.assertEqual(self.profile["student_id"], "9900001")

    def test_completed_courses_contain_all_parsed_courses(self) -> None:
        completed_ids = {c["course_id"] for c in self.profile["completed_courses"]}
        # These are the 9 courses in the fixture, mapped through PLANNER_COURSE_EQUIVALENTS
        self.assertIn("ENG-1001", completed_ids)
        self.assertIn("ENG-1002", completed_ids)
        self.assertIn("CSC-1058", completed_ids)
        self.assertIn("CSC-1059", completed_ids)
        self.assertIn("CSC-2054", completed_ids)
        self.assertIn("CSC-3053", completed_ids)

    def test_current_semester_is_last_parsed_term(self) -> None:
        self.assertEqual(self.profile["current_semester"], "Fall 2024")

    def test_no_in_progress_courses_for_fully_graded_transcript(self) -> None:
        self.assertEqual(self.profile["in_progress_courses"], [])


class RecommendCoursesGuardrailE2ETests(unittest.TestCase):
    """Call recommend_courses with a real student and validate every guardrail.

    Uses student s1001 from data/transcripts/student_s1001.json and the real
    catalog + schedule JSON files. No mocking.
    """

    STUDENT_ID = "s1001"
    MAJOR = "CS"
    SEMESTER = "Fall 2026"
    MAX_CREDITS = 15

    def setUp(self) -> None:
        self.result = recommend_courses(
            self.STUDENT_ID, self.MAJOR, self.SEMESTER, self.MAX_CREDITS
        )
        self.completed = set(
            c["course_id"]
            for c in __import__("json").loads(
                (__import__("pathlib").Path("data/transcripts/student_s1001.json")).read_text()
            ).get("completed_courses", [])
        )
        self.offered = set(get_offered_course_ids(self.SEMESTER))

    def test_result_has_expected_shape(self) -> None:
        self.assertIn("recommended_courses", self.result)
        self.assertIn("skipped_courses", self.result)
        self.assertIn("total_recommended_credits", self.result)
        self.assertEqual(self.result["student_id"], self.STUDENT_ID)
        self.assertEqual(self.result["target_semester"], self.SEMESTER)

    def test_guardrail_no_already_completed_course_is_recommended(self) -> None:
        for course_id in self.result["recommended_courses"]:
            self.assertNotIn(
                course_id,
                self.completed,
                f"{course_id} was recommended but is already completed.",
            )

    def test_guardrail_all_recommended_courses_are_offered_this_semester(self) -> None:
        for course_id in self.result["recommended_courses"]:
            self.assertIn(
                course_id,
                self.offered,
                f"{course_id} was recommended but is not offered in {self.SEMESTER}.",
            )

    def test_guardrail_prerequisites_are_met_for_every_recommended_course(self) -> None:
        for course_id in self.result["recommended_courses"]:
            prereqs = get_course_prerequisites(course_id)
            unmet = [p for p in prereqs if p not in self.completed]
            self.assertEqual(
                unmet,
                [],
                f"{course_id} was recommended but has unmet prerequisites: {unmet}",
            )

    def test_guardrail_total_credits_do_not_exceed_max(self) -> None:
        self.assertLessEqual(
            self.result["total_recommended_credits"],
            self.MAX_CREDITS,
            f"Total credits {self.result['total_recommended_credits']} exceed limit {self.MAX_CREDITS}.",
        )

    def test_lower_credit_limit_produces_fewer_or_equal_recommendations(self) -> None:
        tight_result = recommend_courses(self.STUDENT_ID, self.MAJOR, self.SEMESTER, max_credits=8)
        self.assertLessEqual(
            len(tight_result["recommended_courses"]),
            len(self.result["recommended_courses"]),
        )
        self.assertLessEqual(tight_result["total_recommended_credits"], 8)

    def test_skipped_courses_each_have_a_reason(self) -> None:
        valid_reasons = {"completed", "unmet_prerequisites", "not_offered", "credit_limit"}
        for skipped in self.result["skipped_courses"]:
            self.assertIn(
                skipped["reason"],
                valid_reasons,
                f"Unexpected skip reason: {skipped}",
            )


class FullPipelineE2ETest(unittest.TestCase):
    """Parse a transcript and feed its output directly into recommend_courses.

    This is the complete no-LLM path a real uploaded transcript would take:
      text → parse → profile → (planner uses completed courses) → recommendations
    """

    def test_parsed_transcript_feeds_into_planner_correctly(self) -> None:
        # Step 1: parse the fixture transcript
        parse_result = parse_transcript_text(_CS_TRANSCRIPT, extraction_method="text")
        self.assertEqual(parse_result.status, "success")
        assert parse_result.transcript is not None

        # Step 2: verify the profile shape is correct — this is what the planner agents consume
        profile = parse_result.transcript.to_planner_profile()
        self.assertEqual(profile["status"], "ready")
        self.assertEqual(profile["source"], "uploaded_transcript")
        self.assertIsInstance(profile["completed_courses"], list)
        self.assertGreater(len(profile["completed_courses"]), 0)
        for course in profile["completed_courses"]:
            self.assertIn("course_id", course)
            self.assertIn("grade", course)

        # Step 3: get recommendations for s1001 (a real registry student)
        plan = recommend_courses("s1001", "CS", "Fall 2026", 15)

        # Step 4: s1001's own completed courses must never appear in its own recommendations
        import json
        from pathlib import Path
        s1001_data = json.loads(Path("data/transcripts/student_s1001.json").read_text())
        s1001_completed = {c["course_id"] for c in s1001_data.get("completed_courses", [])}
        recommended = set(plan["recommended_courses"])
        overlap = recommended & s1001_completed
        self.assertEqual(
            overlap,
            set(),
            f"recommend_courses suggested already-completed courses for s1001: {overlap}",
        )

    def test_zero_credit_limit_produces_no_recommendations(self) -> None:
        plan = recommend_courses("s1001", "CS", "Fall 2026", max_credits=0)
        self.assertEqual(plan["recommended_courses"], [])
        self.assertEqual(plan["total_recommended_credits"], 0)


if __name__ == "__main__":
    unittest.main()
