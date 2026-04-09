"""Adapter that turns ADK agent and tool outputs into UI-ready data."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from tools.catalog_tools import load_catalog_data, load_major_planning_context
from tools.student_tools import load_student_index, load_student_profile

from ..models import (
    AdvisingNote,
    ChatMessage,
    CompletedCourse,
    DashboardData,
    ProgressSummary,
    RecommendedCourse,
    ResponseSchemaExample,
    StudentSnapshot,
    StructuredAgentResponse,
)
from .adk_service import get_adk_runner_service
from .transcript_parser import ParsedTranscript


def build_placeholder_dashboard() -> DashboardData:
    return DashboardData(
        student=StudentSnapshot(
            student_name="Awaiting student input",
            student_id="Not identified",
            major="Unknown",
            current_semester="Not provided",
            source="chat_session",
        ),
        completed_courses=[],
        progress_summary=ProgressSummary(
            major="Unknown",
            target_semester="Not specified",
            credits_earned=0,
            required_courses_total=0,
            required_courses_completed=0,
            required_courses_remaining=0,
            percent_complete=0.0,
            total_recommended_credits=0,
        ),
        recommended_courses=[],
        advising_notes=[
            AdvisingNote(
                level="info",
                title="No transcript uploaded yet",
                message="Share a student ID, transcript file, or past coursework in chat to generate a plan.",
            ),
            AdvisingNote(
                level="info",
                title="Recommendations will appear here",
                message="The GradPath agent will update this dashboard automatically after analysis.",
            ),
        ],
    )


def build_welcome_history() -> List[ChatMessage]:
    return [
        ChatMessage(
            id=uuid4().hex,
            role="assistant",
            content=(
                "Share your student ID, goals, and target semester, or upload a transcript. "
                "I’ll analyze your history and update the planning dashboard for you."
            ),
            timestamp=_timestamp(),
        )
    ]


def build_schema_example() -> ResponseSchemaExample:
    dashboard = _build_dashboard_from_profile(
        {
            "student_id": "s1001",
            "student_name": "Alex Kim",
            "major": "CS",
            "current_semester": "Spring 2026",
            "completed_courses": [
                {"course_id": "CS101", "term": "Fall 2025", "grade": "A", "credits": 3},
                {"course_id": "CS102", "term": "Spring 2026", "grade": "B+", "credits": 3},
            ],
            "source": "example",
            "status": "ready",
        },
        target_semester="Not specified",
        extra_notes=[],
        adk_plan={"recommended_courses": ["CS201", "MATH201"], "total_recommended_credits": 6, "skipped_courses": []},
    )
    return ResponseSchemaExample(
        completed_courses=dashboard.completed_courses,
        progress_summary=dashboard.progress_summary,
        recommended_courses=dashboard.recommended_courses,
        advising_notes=dashboard.advising_notes,
    )


async def analyze_request(
    message: str,
    transcript: Optional[ParsedTranscript],
    web_session_id: str,
    session_profile: Optional[Dict[str, Any]] = None,
) -> StructuredAgentResponse:
    student_ref = _extract_student_ref(message)

    extra_notes: List[AdvisingNote] = []
    profile: Optional[Dict[str, Any]] = None

    if transcript is not None:
        if transcript.status == "ocr_required":
            dashboard = build_placeholder_dashboard()
            dashboard.advising_notes = [
                AdvisingNote(
                    level="warning",
                    title="OCR support needed",
                    message=transcript.message,
                )
            ]
            return StructuredAgentResponse(reply_text=transcript.message, dashboard=dashboard)
        if transcript.profile is None:
            raise ValueError(transcript.message)
        profile = transcript.profile
        extra_notes.append(
            AdvisingNote(
                level="success",
                title="Transcript attached",
                message=f"Analyzed uploaded file: {transcript.filename}",
            )
        )
        extra_notes.extend(
            AdvisingNote(level="warning", title="Transcript parsing note", message=warning)
            for warning in transcript.warnings
        )
    elif student_ref:
        profile = load_student_profile(student_ref)

    # Use the profile saved from a previous turn in this session (e.g. transcript uploaded earlier)
    if profile is None and session_profile is not None:
        profile = session_profile

    # If the student declared their major in this message, update the session profile
    if profile is not None and profile.get("major", "Unknown") in {"Unknown", "Undergraduate", "Undeclared", ""}:
        inferred_major = _extract_major_from_message(message)
        if inferred_major:
            profile = {**profile, "major": inferred_major}

    if profile is None:
        inferred_profile = _infer_profile_from_message(message)
        if inferred_profile is not None:
            profile = inferred_profile
            extra_notes.append(
                AdvisingNote(
                    level="info",
                    title="Course history inferred from chat",
                    message="GradPath used the course references in the conversation to build a draft dashboard.",
                )
            )

    if profile is None:
        dashboard = build_placeholder_dashboard()
        dashboard.advising_notes.insert(
            0,
            AdvisingNote(
                level="warning",
                title="More academic history needed",
                message="Provide a student ID, upload a transcript, or list completed courses so GradPath can plan accurately.",
            ),
        )
        return StructuredAgentResponse(
            reply_text=(
                "I need more academic history before I can update your plan. "
                "Please share a student ID, transcript file, or completed courses."
            ),
            dashboard=dashboard,
            profile=None,
        )

    if profile.get("status") != "ready":
        dashboard = build_placeholder_dashboard()
        dashboard.student = StudentSnapshot(
            student_name=profile.get("student_name", "Unavailable"),
            student_id=profile.get("student_ref", profile.get("student_id", "Unavailable")),
            major=profile.get("major", "Unknown"),
            current_semester=profile.get("current_semester", "Unknown"),
            source="student_registry",
        )
        dashboard.advising_notes = [
            AdvisingNote(
                level="warning",
                title="Transcript not ready",
                message=profile.get("message", "Transcript data is not available yet."),
            )
        ]
        return StructuredAgentResponse(
            reply_text=dashboard.advising_notes[0].message,
            dashboard=dashboard,
            profile=profile,
        )

    if profile.get("major", "Unknown") in {"Unknown", "Undergraduate", "Undeclared", ""}:
        dashboard = build_placeholder_dashboard()
        dashboard.student = StudentSnapshot(
            student_name=profile.get("student_name", "Student"),
            student_id=profile.get("student_id", "uploaded-transcript"),
            major="Not declared",
            current_semester=profile.get("current_semester", "Unknown"),
            source=profile.get("source", "uploaded_transcript"),
        )
        dashboard.advising_notes = [
            *extra_notes,
            AdvisingNote(
                level="warning",
                title="Major not declared on transcript",
                message=(
                    "Your transcript does not list a declared major. "
                    "Please reply with your major (e.g. 'My major is Computer Science') "
                    "so GradPath can build your degree plan."
                ),
            ),
        ]
        return StructuredAgentResponse(
            reply_text=(
                f"Hi {profile.get('student_name', 'there')}! Your transcript was parsed successfully, "
                "but it does not list a declared major. "
                "Please tell me your major (e.g. 'My major is Computer Science') so I can build your plan."
            ),
            dashboard=dashboard,
            profile=profile,
        )

    return await _try_invoke_google_adk_agent(
        web_session_id=web_session_id,
        message=message,
        profile=profile,
        transcript=transcript,
        extra_notes=extra_notes,
    )


async def _try_invoke_google_adk_agent(
    web_session_id: str,
    message: str,
    profile: Dict[str, Any],
    transcript: Optional[ParsedTranscript],
    extra_notes: List[AdvisingNote],
) -> StructuredAgentResponse:
    adk_service = get_adk_runner_service()
    adk_result = await adk_service.run_planner(
        web_session_id=web_session_id,
        message=message,
        student_id=str(profile.get("student_id", profile.get("student_ref", ""))),
        student_name=str(profile.get("student_name", "Student")),
        major=str(profile.get("major", "CS")),
        current_semester=str(profile.get("current_semester", "Unknown")),
        transcript=transcript,
    )

    target_semester = adk_result.target_semester or "Not specified"

    if adk_result.planner_json is None:
        return StructuredAgentResponse(
            reply_text=adk_result.final_text or "GradPath needs a little more information before it can plan.",
            dashboard=build_placeholder_dashboard(),
            profile=profile,
        )

    notes = [
        AdvisingNote(
            level="success",
            title="Google ADK workflow active",
            message="The dashboard recommendations were generated by the live GradPath multi-agent flow.",
        ),
        *extra_notes,
    ]
    dashboard = _build_dashboard_from_profile(
        profile=profile,
        target_semester=target_semester,
        extra_notes=notes,
        adk_plan=adk_result.planner_json,
    )
    reply_text = _build_reply_text(dashboard, target_semester)
    return StructuredAgentResponse(reply_text=reply_text, dashboard=dashboard, profile=profile)


def _build_dashboard_from_profile(
    profile: Dict[str, Any],
    target_semester: str,
    extra_notes: List[AdvisingNote],
    adk_plan: Dict[str, Any],
) -> DashboardData:
    catalog = load_catalog_data()
    major = str(profile.get("major") or "CS")
    planning_context = load_major_planning_context(major, target_semester)
    required_courses = planning_context.get("required_courses", [])
    course_lookup = {course["course_id"]: course for course in (catalog if isinstance(catalog, list) else catalog.get("courses", []))}

    completed_courses_raw = profile.get("completed_courses", [])
    completed_ids = {course["course_id"] for course in completed_courses_raw}
    completed_courses = [
        CompletedCourse(
            course_id=course["course_id"],
            title=course_lookup.get(course["course_id"], {}).get("title", "Unknown Course"),
            term=course.get("term"),
            grade=course.get("grade"),
            credits=int(course.get("credits", course_lookup.get(course["course_id"], {}).get("credits", 0))),
        )
        for course in completed_courses_raw
    ]

    recommended_courses, skipped_notes, total_recommended_credits = _apply_adk_plan(
        adk_plan=adk_plan,
        course_lookup=course_lookup,
    )

    credits_earned = sum(course.credits for course in completed_courses)
    required_completed = sum(1 for course_id in required_courses if course_id in completed_ids)
    required_remaining = max(len(required_courses) - required_completed, 0)
    percent_complete = round((required_completed / len(required_courses)) * 100, 1) if required_courses else 0.0

    notes = list(extra_notes)
    if not recommended_courses:
        notes.append(
            AdvisingNote(
                level="warning",
                title="No eligible courses found",
                message="GradPath could not find a valid recommendation set under the current constraints.",
            )
        )
    else:
        notes.append(
            AdvisingNote(
                level="success",
                title="Plan generated",
                message=f"Prepared {len(recommended_courses)} recommendation(s) for {target_semester}.",
            )
        )
    notes.extend(skipped_notes)

    return DashboardData(
        student=StudentSnapshot(
            student_name=profile.get("student_name", "Unknown Student"),
            student_id=profile.get("student_id", profile.get("student_ref", "Unknown")),
            major=major,
            current_semester=profile.get("current_semester", "Unknown"),
            source=profile.get("source", "student_registry"),
        ),
        completed_courses=completed_courses,
        progress_summary=ProgressSummary(
            major=major,
            target_semester=target_semester,
            credits_earned=credits_earned,
            required_courses_total=len(required_courses),
            required_courses_completed=required_completed,
            required_courses_remaining=required_remaining,
            percent_complete=percent_complete,
            total_recommended_credits=total_recommended_credits,
        ),
        recommended_courses=recommended_courses,
        advising_notes=notes,
    )



def _apply_adk_plan(
    adk_plan: Dict[str, Any],
    course_lookup: Dict[str, Dict[str, Any]],
) -> Tuple[List[RecommendedCourse], List[AdvisingNote], int]:
    recommended: List[RecommendedCourse] = []
    notes: List[AdvisingNote] = []

    for course_id in adk_plan.get("recommended_courses", []):
        course = course_lookup.get(course_id, {})
        recommended.append(
            RecommendedCourse(
                course_id=course_id,
                title=course.get("title", "Unknown Course"),
                credits=int(course.get("credits", 0)),
                reason="Selected by the GradPath ADK planner after evaluating history, prerequisites, and offerings.",
            )
        )

    reason_map = {
        "completed": "Already completed.",
        "unmet_prerequisites": "Prerequisites are not yet satisfied.",
        "not_offered": "Not offered in the selected semester.",
        "credit_limit": "Would exceed the requested credit limit.",
    }
    for skipped in adk_plan.get("skipped_courses", []):
        course_id = skipped.get("course_id", "UNKNOWN")
        reason = skipped.get("reason", "deferred")
        notes.append(
            AdvisingNote(
                level="warning" if reason in {"unmet_prerequisites", "credit_limit"} else "info",
                title="Transcript issue" if course_id == "TRANSCRIPT" else f"{course_id} skipped",
                message=reason_map.get(reason, reason),
            )
        )

    total_credits = int(adk_plan.get("total_recommended_credits", 0))
    return recommended, notes, total_credits


def _build_reply_text(dashboard: DashboardData, target_semester: str) -> str:
    student = dashboard.student
    if not dashboard.recommended_courses:
        return (
            f"I reviewed {student.student_name}'s record for {target_semester}, but I couldn't assemble a valid next-term plan yet. "
            "Check the advising notes for prerequisite, availability, or transcript issues."
        )

    recommendations = ", ".join(
        f"{course.course_id} ({course.title})" for course in dashboard.recommended_courses
    )
    return (
        f"I analyzed {student.student_name}'s academic history and updated the dashboard for {target_semester}. "
        f"Recommended next courses: {recommendations}. "
        f"Degree progress is now shown on the left, along with advising notes and warnings."
    )



_MESSAGE_MAJOR_PATTERNS = {
    # longest phrases first so they match before shorter substrings
    "biochemistry and molecular biology": "BIOCHEM",
    "information systems management": "ISM",
    "chemistry forensic science": "FORENSIC",
    "forensic science": "FORENSIC",
    "environmental science": "ENV",
    "environmental studies": "ENV",
    "pan-africana studies": "PAS",
    "pan africana studies": "PAS",
    "political science": "POL",
    "criminal justice": "CRJ",
    "health science": "HSC",
    "computer science": "CS",
    "human services": "HUS",
    "visual arts": "ART",
    "black studies": "PAS",
    "information systems": "ISM",
    "biochemistry": "BIOCHEM",
    "mathematical sciences": "MAT",
    "mathematics": "MAT",
    "communication": "COM",
    "anthropology": "ANT",
    "accounting": "ACC",
    "sociology": "SOC",
    "psychology": "PSY",
    "philosophy": "PHL",
    "management": "MGT",
    "chemistry": "CHE",
    "biology": "BIO",
    "physics": "PHY",
    "history": "HIS",
    "finance": "FIN",
    "english": "ENG",
    "music": "MUS",
    "data science": "CS",
    "math": "MAT",
    "art": "ART",
    "religion": "REL",
    "religious studies": "REL",
    "french": "FRE",
    "spanish": "SPN",
}


def _extract_major_from_message(message: str) -> Optional[str]:
    """Extract a major declaration from a follow-up message like 'I am a CS student'."""
    lower = message.lower()
    for phrase, major_key in sorted(_MESSAGE_MAJOR_PATTERNS.items(), key=lambda x: -len(x[0])):
        if phrase in lower:
            return major_key
    return None


def _extract_student_ref(message: str) -> Optional[str]:
    index = load_student_index()
    aliases = []
    for record in index.get("students", []):
        aliases.extend(record.get("aliases", []))

    alias_pattern = "|".join(sorted({re.escape(alias) for alias in aliases}, key=len, reverse=True))
    if not alias_pattern:
        return None

    match = re.search(rf"\b({alias_pattern})\b", message, re.IGNORECASE)
    return match.group(1) if match else None



def _infer_profile_from_message(message: str) -> Optional[Dict[str, Any]]:
    catalog = load_catalog_data()
    catalog_list = catalog if isinstance(catalog, list) else catalog.get("courses", [])
    course_lookup = {course["course_id"] for course in catalog_list}
    found_courses = [
        course_id
        for course_id in re.findall(r"\b[A-Z]{2,4}-\d{3,4}\b", message.upper())
        if course_id in course_lookup
    ]
    if not found_courses:
        return None

    completed_courses = []
    seen = set()
    for course_id in found_courses:
        if course_id in seen:
            continue
        seen.add(course_id)
        completed_courses.append(
            {
                "course_id": course_id,
                "term": None,
                "grade": None,
                "credits": next(
                    (
                        int(course.get("credits", 0))
                        for course in catalog_list
                        if course.get("course_id") == course_id
                    ),
                    0,
                ),
            }
        )

    return {
        "student_id": "chat-history",
        "student_name": "Student from chat",
        "major": "CS",
        "current_semester": "Unknown",
        "completed_courses": completed_courses,
        "status": "ready",
        "source": "chat_message",
    }


def build_user_message(content: str, attachment_name: Optional[str] = None) -> ChatMessage:
    return ChatMessage(
        id=uuid4().hex,
        role="user",
        content=content,
        timestamp=_timestamp(),
        attachment_name=attachment_name,
    )


def build_assistant_message(content: str, attachment_name: Optional[str] = None) -> ChatMessage:
    return ChatMessage(
        id=uuid4().hex,
        role="assistant",
        content=content,
        timestamp=_timestamp(),
        attachment_name=attachment_name,
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
