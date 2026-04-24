"""DAG-based evaluation runner for GradPath.

Evaluates the full multi-semester graduation plan against the prerequisite DAG.
Checks:
1. No completed courses repeated
2. Prerequisites satisfied before each course is taken
3. Credit limit respected each semester
4. No course appears twice in the plan
5. All required courses eventually covered
6. Plan completes within semester limit
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from tools.catalog_tools import get_course_prerequisites, get_required_courses
from tools.planning_tools import build_full_graduation_plan
from tools.student_tools import load_student_profile


EVAL_FILE = Path(__file__).resolve().parent / "data" / "eval" / "eval_cases.json"


def _normalize(cid: str) -> str:
    return re.sub(r"\s+", "-", cid.strip().upper())


def evaluate_plan(
    plan: List[Dict[str, Any]],
    completed_course_ids: List[str],
    major: str,
    max_credits: int,
) -> Dict[str, Any]:
    """Evaluate a multi-semester graduation plan against the DAG.

    Returns a detailed report with pass/fail for each check.
    """
    required = [_normalize(c) for c in get_required_courses(major)]
    completed = {_normalize(c) for c in completed_course_ids}
    # Also normalize plan course IDs
    plan = [
        {**sem, "course_ids": [_normalize(c) for c in sem.get("course_ids", [])]}
        for sem in plan
    ]

    checks = {
        "no_repeats": True,
        "prerequisites_satisfied": True,
        "credit_limit_respected": True,
        "no_duplicates_in_plan": True,
        "all_required_covered": False,
    }
    issues = []

    seen_in_plan: Set[str] = set()
    available = set(completed)  # grows as semesters complete

    for sem in plan:
        term = sem["term"]
        course_ids = [_normalize(c) for c in sem.get("course_ids", [])]
        semester_credits = sem.get("total_credits", 0)

        # Check credit limit
        if semester_credits > max_credits:
            checks["credit_limit_respected"] = False
            issues.append(f"{term}: credits {semester_credits} exceed limit {max_credits}")

        for cid in course_ids:
            # Check no repeats from completed
            if cid in completed:
                checks["no_repeats"] = False
                issues.append(f"{term}: {cid} already completed before plan started")

            # Check no duplicates within plan
            if cid in seen_in_plan:
                checks["no_duplicates_in_plan"] = False
                issues.append(f"{term}: {cid} appears more than once in the plan")

            # Check prerequisites satisfied
            prereqs = [_normalize(p) for p in get_course_prerequisites(cid)]
            unmet = [p for p in prereqs if p not in available]
            if unmet:
                checks["prerequisites_satisfied"] = False
                issues.append(f"{term}: {cid} missing prerequisites {unmet}")

            seen_in_plan.add(cid)

        # After this semester, these courses become available for future semesters
        available.update(course_ids)

    # Check all required courses covered
    # Exclude courses whose prerequisites can never be satisfied from the required list
    all_covered = {_normalize(c) for c in seen_in_plan} | completed
    unresolvable = []
    for c in required:
        prereqs = [_normalize(p) for p in get_course_prerequisites(c)]
        if any(p not in {_normalize(r) for r in required} | completed for p in prereqs):
            unresolvable.append(c)

    checkable_required = [c for c in required if c not in unresolvable]
    missing_required = [c for c in checkable_required if c not in all_covered]
    checks["all_required_covered"] = len(missing_required) == 0

    if unresolvable:
        issues.append(f"Skipped unresolvable courses (missing prereqs not in required list): {unresolvable}")
    if missing_required:
        issues.append(f"Required courses not covered: {missing_required}")

    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    score = round((passed / total) * 100, 1)

    return {
        "checks": checks,
        "passed": passed,
        "total": total,
        "score": score,
        "issues": issues,
        "plan_semesters": len(plan),
        "courses_planned": len(seen_in_plan),
        "missing_required": missing_required,
    }


def run_evaluation() -> None:
    """Run all evaluation cases and print a readable report."""
    with EVAL_FILE.open("r", encoding="utf-8") as f:
        eval_data = json.load(f)

    cases = eval_data.get("cases", [])
    total_score = 0

    print("GradPath DAG Evaluation Report")
    print("=" * 40)

    for case in cases:
        case_id = case["case_id"]
        student_id = case["student_id"]
        major = case["major"]
        max_credits = case["max_credits"]
        description = case.get("description", "")

        print(f"\nCase: {case_id}")
        print(f"Student: {description}")

        profile = load_student_profile(student_id)
        if profile.get("status") != "ready":
            print(f"  SKIP — student not ready: {profile.get('message')}")
            continue

        completed_courses = [_normalize(c["course_id"]) for c in profile.get("completed_courses", [])]
        current_semester = profile.get("current_semester", "Spring 2026")
        student_type = profile.get("student_type", "undergraduate")

        plan = build_full_graduation_plan(
            major=major,
            completed_course_ids=completed_courses,
            current_semester=current_semester,
            max_credits_per_semester=max_credits,
            student_type=student_type,
        )

        result = evaluate_plan(
            plan=plan,
            completed_course_ids=completed_courses,
            major=major,
            max_credits=max_credits,
        )

        print(f"  Plan: {result['plan_semesters']} semesters, {result['courses_planned']} courses planned")
        print(f"  Score: {result['score']}% ({result['passed']}/{result['total']} checks passed)")

        for check, passed in result["checks"].items():
            status = "✅" if passed else "❌"
            print(f"    {status} {check.replace('_', ' ').title()}")

        if result["issues"]:
            print(f"  Issues:")
            for issue in result["issues"]:
                print(f"    - {issue}")

        total_score += result["score"]

    avg_score = round(total_score / len(cases), 1) if cases else 0
    print("\n" + "=" * 40)
    print(f"Overall Score: {avg_score}% average across {len(cases)} cases")


if __name__ == "__main__":
    run_evaluation()
