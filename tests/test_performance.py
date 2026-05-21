"""Performance tests for GradPath's deterministic pipeline.

These tests measure wall-clock time and fail if a component exceeds its budget.
They do not call any LLM or external service.

Budgets are intentionally generous — the goal is to catch accidental regressions
(e.g. a file being re-read on every call) not to micro-benchmark.
"""

from __future__ import annotations

import time
import unittest

from tools.transcript_parser import parse_transcript_text
from tools.planning_tools import recommend_courses


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_REALISTIC_TRANSCRIPT = """
Lincoln University
Student Name: Alex Johnson
Student ID: 0123456
Program: Computer Science
Cumulative GPA: 3.20
Total Credits Completed: 48

Fall 2022
ENG1001    English Composition I         4.00  A
MAT1010    College Algebra               4.00  B+
CSC1058    Computer Programming I        4.00  A
Term GPA: 3.65

Spring 2023
ENG1002    English Composition II        4.00  B
MAT1014    Elementary Statistics I       4.00  B+
CSC1059    Computer Programming II       4.00  A-
Term GPA: 3.40

Fall 2023
CSC2054    Data Structures               4.00  B+
CSC3053    Computer Organization         4.00  B
SOS1051    African American Experience   4.00  A
Term GPA: 3.33

Spring 2024
CSC3055    Operating Systems with Linux  4.00  A-
CSC3054    Database Design & Development 4.00  B+
MAT2013    Discrete Mathematics          4.00  B
Term GPA: 3.40
"""

# How many times to repeat a parse in the throughput test
_PARSE_REPEAT = 50

# Time budgets (seconds)
_SINGLE_PARSE_BUDGET_S = 0.5   # one parse must complete under 500 ms
_BULK_PARSE_BUDGET_S   = 5.0   # 50 parses must complete under 5 s
_RECOMMEND_BUDGET_S    = 1.0   # one recommend_courses call under 1 s


# ---------------------------------------------------------------------------
# Parser performance
# ---------------------------------------------------------------------------

class ParserPerformanceTests(unittest.TestCase):

    def test_single_parse_is_under_500ms(self) -> None:
        start = time.perf_counter()
        result = parse_transcript_text(_REALISTIC_TRANSCRIPT, extraction_method="text")
        elapsed = time.perf_counter() - start

        self.assertEqual(result.status, "success", "Parse failed — fix correctness before measuring speed.")
        self.assertLess(
            elapsed,
            _SINGLE_PARSE_BUDGET_S,
            f"Single parse took {elapsed:.3f}s — over the {_SINGLE_PARSE_BUDGET_S}s budget.",
        )

    def test_fifty_consecutive_parses_under_5s(self) -> None:
        # Warm up once so any module-level caching is counted fairly.
        parse_transcript_text(_REALISTIC_TRANSCRIPT, extraction_method="text")

        start = time.perf_counter()
        for _ in range(_PARSE_REPEAT):
            parse_transcript_text(_REALISTIC_TRANSCRIPT, extraction_method="text")
        elapsed = time.perf_counter() - start

        self.assertLess(
            elapsed,
            _BULK_PARSE_BUDGET_S,
            f"{_PARSE_REPEAT} parses took {elapsed:.3f}s — over the {_BULK_PARSE_BUDGET_S}s budget.",
        )

    def test_parse_speed_does_not_degrade_with_longer_transcript(self) -> None:
        # Double the transcript length — time should not more than double (no quadratic behaviour).
        long_transcript = _REALISTIC_TRANSCRIPT * 2

        start_short = time.perf_counter()
        parse_transcript_text(_REALISTIC_TRANSCRIPT, extraction_method="text")
        time_short = time.perf_counter() - start_short

        start_long = time.perf_counter()
        parse_transcript_text(long_transcript, extraction_method="text")
        time_long = time.perf_counter() - start_long

        self.assertLess(
            time_long,
            time_short * 3,
            f"Long parse ({time_long:.3f}s) is more than 3× the short parse ({time_short:.3f}s). "
            "Possible quadratic behaviour — check loop logic in the parser.",
        )


# ---------------------------------------------------------------------------
# Planning pipeline performance
# ---------------------------------------------------------------------------

class PlanningPerformanceTests(unittest.TestCase):

    def test_recommend_courses_under_1s(self) -> None:
        start = time.perf_counter()
        result = recommend_courses("s1001", "CS", "Fall 2026", 15)
        elapsed = time.perf_counter() - start

        self.assertIn("recommended_courses", result, "recommend_courses returned unexpected shape.")
        self.assertLess(
            elapsed,
            _RECOMMEND_BUDGET_S,
            f"recommend_courses took {elapsed:.3f}s — over the {_RECOMMEND_BUDGET_S}s budget.",
        )

    def test_recommend_courses_ten_calls_under_3s(self) -> None:
        # Repeated calls should not re-read JSON files each time if caching is in place.
        # If they do re-read every time, this test catches it being unreasonably slow.
        start = time.perf_counter()
        for _ in range(10):
            recommend_courses("s1001", "CS", "Fall 2026", 15)
        elapsed = time.perf_counter() - start

        self.assertLess(
            elapsed,
            3.0,
            f"10 recommend_courses calls took {elapsed:.3f}s — each call is re-reading from disk.",
        )


if __name__ == "__main__":
    unittest.main()
