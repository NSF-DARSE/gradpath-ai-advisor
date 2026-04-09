"""Simple parser coverage for the shared transcript extraction flow."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tools.transcript_parser import parse_transcript_text
from tools.transcript_schema import (
    AcademicSummary,
    CompletedCourseRecord,
    TranscriptDocument,
    TranscriptStudent,
    TranscriptTerm,
    TranscriptCourse,
)


class TranscriptParserTests(unittest.TestCase):
    def test_parse_transcript_text_builds_terms_and_completed_courses(self) -> None:
        sample_text = """
        Example State University
        Student Name: Jamie Rivera
        Student ID: 900123
        Program: Computer Science
        Cumulative GPA: 3.74
        Total Credits Completed: 12
        Fall 2025
        CISC 681 Intro to AI
        3.0 A
        MATH 210 Linear Algebra 3.0 B+
        Term GPA: 3.65
        Spring 2026
        CISC 690 Machine Learning 3.0 A-
        ENGL 510 Technical Writing 3.0 B
        """

        result = parse_transcript_text(sample_text, extraction_method="text")

        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.transcript)
        assert result.transcript is not None
        self.assertEqual(result.transcript.student.name, "Jamie Rivera")
        self.assertEqual(result.transcript.student.student_id, "900123")
        self.assertEqual(result.transcript.student.program, "Computer Science")
        self.assertEqual(result.transcript.academic_summary.cumulative_gpa, 3.74)
        self.assertEqual(len(result.transcript.terms), 2)
        self.assertEqual(result.transcript.terms[0].term, "Fall 2025")
        self.assertEqual(result.transcript.terms[0].courses[0].course_code, "CISC 681")
        self.assertEqual(len(result.transcript.completed_courses), 4)

    def test_parse_two_column_year_first_transcript_layout(self) -> None:
        sample_text = """
                     2023 FALL
          ENG101     English Composition I            3.00  A    12.00                 2025 SPRING
          FYE101     First Year Experience            3.00  A    12.00      CSC2054    Data Structures                  4.00  B    12.00
          HPR101     Dimensions of Wellness           2.00  A     8.00      CSC3090    ST: QA & Testing in SD           4.00  B    12.00
          Term  ( 15.00)  ( 15.00)  (    56)  (    15)  (  3.733)           SOS1051    African American Experience      4.00  A    16.00
                                                                            Term  ( 20.00)  ( 20.00)  (    68)  (    20)  (  3.400)
        """

        result = parse_transcript_text(sample_text, extraction_method="text")

        self.assertEqual(result.status, "success")
        assert result.transcript is not None
        terms = {term.term: term for term in result.transcript.terms}
        self.assertIn("Fall 2023", terms)
        self.assertIn("Spring 2025", terms)
        self.assertEqual(terms["Fall 2023"].courses[0].course_code, "ENG 101")
        self.assertTrue(any(course.course_code == "CSC 2054" for course in terms["Spring 2025"].courses))

        profile = result.transcript.to_planner_profile()
        completed_ids = {course["course_id"] for course in profile["completed_courses"]}
        self.assertIn("CS102", completed_ids)
        self.assertEqual(profile["major"], "CS")

    def test_llm_fallback_can_fill_missing_fields_while_preserving_local_courses(self) -> None:
        sample_text = """
        Student Name: Taylor Example
        Student ID: 555123
        Program: Undergraduate
        CSC2054 Data Structures 4.00 B
        """

        llm_transcript = TranscriptDocument(
            student=TranscriptStudent(
                name="Taylor Example",
                student_id="555123",
                institution="Example College",
                program="Computer Science",
            ),
            academic_summary=AcademicSummary(cumulative_gpa=3.5, total_credits_completed=4.0),
            terms=[
                TranscriptTerm(
                    term="Spring 2025",
                    term_gpa=3.5,
                    courses=[
                        TranscriptCourse(
                            course_code="CSC 2054",
                            course_title="Data Structures",
                            credits=4.0,
                            grade="B",
                        )
                    ],
                )
            ],
            completed_courses=[
                CompletedCourseRecord(
                    term="Spring 2025",
                    course_code="CSC 2054",
                    course_title="Data Structures",
                    credits=4.0,
                    grade="B",
                )
            ],
            raw_text_excerpt="Taylor Example",
        )

        with patch("tools.transcript_parser._try_llm_transcript_fallback", return_value=llm_transcript):
            result = parse_transcript_text(sample_text, extraction_method="text")

        self.assertEqual(result.status, "success")
        assert result.transcript is not None
        self.assertEqual(result.transcript.student.program, "Computer Science")
        self.assertEqual(result.transcript.student.institution, "Example College")
        self.assertEqual(len(result.transcript.completed_courses), 1)
        profile = result.transcript.to_planner_profile()
        self.assertEqual(profile["major"], "CS")
        self.assertEqual(profile["completed_courses"][0]["course_id"], "CS102")


if __name__ == "__main__":
    unittest.main()
