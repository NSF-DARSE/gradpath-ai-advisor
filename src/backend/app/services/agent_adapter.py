"""Adapter that turns ADK agent and tool outputs into UI-ready data."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from tools.catalog_tools import load_catalog_data, load_major_planning_context, get_required_courses
from tools.student_tools import load_student_index, load_student_profile
from tools.planning_tools import build_full_graduation_plan

from ..config import DEFAULT_MAX_CREDITS, DEFAULT_MIN_CREDITS
from ..models import (
    AdvisingNote,
    ChatMessage,
    CompletedCourse,
    DashboardData,
    PlannedCourse,
    PlannedSemester,
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
        if session_profile is None:
            # First message with no student data — let the conversational greeting agent handle it
            adk_service = get_adk_runner_service()
            greeting_result = await adk_service.run_greeting(
                web_session_id=web_session_id,
                message=message,
            )
            if greeting_result.greeting_json:
                # Agent collected enough info — build a profile and run the full pipeline
                gj = greeting_result.greeting_json
                loaded = load_student_profile(str(gj.get("student_id", "")))
                if loaded and loaded.get("status") == "ready":
                    profile = loaded
                else:
                    profile = {
                        "student_id": gj.get("student_id", "chat"),
                        "student_name": gj.get("student_name", "Student"),
                        "major": gj.get("major", "CS"),
                        "current_semester": gj.get("current_semester", "Spring 2026"),
                        "target_semester": gj.get("target_semester"),
                        "max_credits": gj.get("max_credits", 12),
                        "career_goal": gj.get("career_goal"),
                        "preferences": gj.get("preferences", "balanced"),
                        "completed_courses": [],
                        "status": "ready",
                        "source": "chat_session",
                    }
                return await _try_invoke_google_adk_agent(
                    web_session_id=web_session_id,
                    message=message,
                    profile=profile,
                    transcript=None,
                    extra_notes=extra_notes,
                )
            # Still in conversation — return Maya's response with placeholder dashboard
            return StructuredAgentResponse(
                reply_text=greeting_result.final_text or (
                    "Hey! I'm your GradPath AI advisor. What's your name and student ID so I can get started?"
                ),
                dashboard=build_placeholder_dashboard(),
                profile=None,
            )

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

    # Follow-up message — profile already exists from a previous turn.
    # Skip transcript_agent, history_agent, catalog_agent and go straight to planner.
    if session_profile is not None and transcript is None:
        return await _try_invoke_followup_agent(
            web_session_id=web_session_id,
            message=message,
            profile=profile,
            extra_notes=extra_notes,
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
    _current_sem = str(profile.get("current_semester", "Unknown"))
    _student_type = profile.get("student_type", "undergraduate")
    _completed_terms = {c.get("term") for c in profile.get("completed_courses", []) if c.get("term")}
    if _current_sem:
        _completed_terms.add(_current_sem)
    _semesters_used = len(_completed_terms)
    adk_result = await adk_service.run_planner(
        web_session_id=web_session_id,
        message=message,
        student_id=str(profile.get("student_id", profile.get("student_ref", ""))),
        student_name=str(profile.get("student_name", "Student")),
        major=str(profile.get("major", "CS")),
        current_semester=_current_sem,
        transcript=transcript,
        semesters_used=_semesters_used,
        student_type=_student_type,
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
    reply_text = _build_reply_text(dashboard, target_semester, adk_plan=adk_result.planner_json, message=message, profile=profile)
    return StructuredAgentResponse(reply_text=reply_text, dashboard=dashboard, profile=profile)


async def _try_invoke_followup_agent(
    web_session_id: str,
    message: str,
    profile: Dict[str, Any],
    extra_notes: List[AdvisingNote],
) -> StructuredAgentResponse:
    """Slim pipeline for follow-up messages — greeting + planner only."""
    adk_service = get_adk_runner_service()

    # Compute remaining required courses to enrich the intent agent's context
    _major = profile.get("major", "CS")
    _completed_ids = {c["course_id"] for c in profile.get("completed_courses", [])}
    _completed_ids |= {c["course_id"] for c in profile.get("in_progress_courses", [])}
    _remaining_courses = [c for c in get_required_courses(_major) if c not in _completed_ids]

    # Detect intent first — avoids running the planner for questions and chat
    intent_result = await adk_service.run_followup_intent(
        web_session_id=web_session_id,
        message=message,
        profile=profile,
        remaining_courses=_remaining_courses,
    )
    intent = (intent_result.greeting_json or {}).get("intent", "plan_change")

    if intent in ("chat", "question"):
        return StructuredAgentResponse(
            reply_text=intent_result.final_text or "Let me know if you have any other questions!",
            dashboard=None,
            profile=profile,
        )

    # Apply any detected changes (major, target_semester, etc.) to the profile
    # BEFORE calling run_followup so the planner prompt reflects the new values.
    updated_profile = profile
    if intent_result.greeting_json:
        changed = {k: v for k, v in intent_result.greeting_json.items() if v is not None and k != "intent"}
        # Resolve requested_courses: fuzzy-match names to catalog IDs and merge into profile
        if "requested_courses" in changed:
            resolved, unresolved = _resolve_elective_requests(changed.pop("requested_courses"))
            existing = list(profile.get("elective_course_ids", []))
            merged = list(dict.fromkeys(existing + resolved))  # deduplicate, preserve order
            changed["elective_course_ids"] = merged
            if unresolved:
                extra_notes.append(AdvisingNote(
                    level="warning",
                    title="Course not found",
                    message=f"Could not find in catalog: {', '.join(unresolved)}. Check the course name and try again.",
                ))
        if changed:
            updated_profile = {**profile, **changed}

    _current_sem = str(updated_profile.get("current_semester", "Unknown"))
    _student_type = updated_profile.get("student_type", "undergraduate")
    _completed_terms = {c.get("term") for c in updated_profile.get("completed_courses", []) if c.get("term")}
    if _current_sem:
        _completed_terms.add(_current_sem)
    _semesters_used = len(_completed_terms)
    adk_result = await adk_service.run_followup(
        web_session_id=web_session_id,
        message=message,
        profile=updated_profile,
        semesters_used=_semesters_used,
        student_type=_student_type,
    )

    # Merge any additional fields the planner pipeline detected on top of intent changes.
    if adk_result.greeting_json:
        changed = {k: v for k, v in adk_result.greeting_json.items() if v is not None and k != "intent"}
        if changed:
            updated_profile = {**updated_profile, **changed}

    target_semester = adk_result.target_semester or updated_profile.get("target_semester") or "Not specified"

    if adk_result.planner_json is None:
        return StructuredAgentResponse(
            reply_text=adk_result.final_text or "GradPath needs a little more information before it can plan.",
            dashboard=build_placeholder_dashboard(),
            profile=updated_profile,
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
        profile=updated_profile,
        target_semester=target_semester,
        extra_notes=notes,
        adk_plan=adk_result.planner_json,
    )
    reply_text = _build_reply_text(dashboard, target_semester, adk_plan=adk_result.planner_json, message=message, profile=updated_profile)
    return StructuredAgentResponse(reply_text=reply_text, dashboard=dashboard, profile=updated_profile)


_STOP_WORDS = {"a", "an", "the", "to", "of", "in", "for", "and", "or", "with", "course", "class", "intro", "introduction"}

_ACRONYM_EXPANSIONS = {
    "ai": "artificial intelligence",
    "ml": "machine learning",
    "db": "database",
    "oop": "object oriented programming",
    "os": "operating systems",
    "cs": "computer science",
    "ui": "user interface",
}


def _expand_acronyms(text: str) -> str:
    words = text.lower().split()
    return " ".join(_ACRONYM_EXPANSIONS.get(w, w) for w in words)


def _inject_electives(
    planned_semesters: List[PlannedSemester],
    elective_ids: List[str],
    course_lookup: Dict[str, Any],
    max_credits: int = 12,
) -> tuple[List[PlannedSemester], List[str]]:
    """Insert elective courses into the first semester of the LLM plan that has room.

    Returns updated planned_semesters and a list of elective IDs that couldn't be placed.
    """
    from tools.catalog_tools import get_course_prerequisites
    from tools.planning_tools import _normalize

    # Build the set of all courses placed so far (semester by semester)
    already_in_plan = {
        c.course_id for sem in planned_semesters for c in sem.courses
    }

    skipped: List[str] = []
    for elective_id in elective_ids:
        if elective_id in already_in_plan:
            continue  # LLM already included it

        prereqs = [_normalize(p) for p in get_course_prerequisites(elective_id)]
        elective_credits = int(course_lookup.get(elective_id, {}).get("credits", 0))
        placed = False
        placed_so_far: set = set()

        for sem in planned_semesters:
            # Check prereqs against courses from PREVIOUS semesters only
            prereqs_met = all(p in placed_so_far for p in prereqs)
            has_room = sem.total_credits + elective_credits <= max_credits
            sem_course_ids = {c.course_id for c in sem.courses}

            if prereqs_met and has_room and elective_id not in sem_course_ids:
                sem.courses.append(PlannedCourse(
                    course_id=elective_id,
                    title=course_lookup.get(elective_id, {}).get("title", "Unknown Course"),
                    credits=elective_credits,
                ))
                sem.total_credits += elective_credits
                already_in_plan.add(elective_id)
                placed = True
                break
            placed_so_far |= sem_course_ids  # update AFTER checking so prereqs = prior semesters only

        if not placed:
            skipped.append(elective_id)

    return planned_semesters, skipped


def _resolve_elective_requests(
    requests: List[str],
) -> tuple[List[str], List[str]]:
    """Fuzzy-match course name/ID requests against the catalog. Returns (resolved_ids, unresolved_names)."""
    catalog = load_catalog_data()
    catalog_list = catalog if isinstance(catalog, list) else catalog.get("courses", [])

    resolved: List[str] = []
    unresolved: List[str] = []
    for req in requests:
        req_upper = req.strip().upper()
        # Exact course ID match first (e.g. "CSC-3058" or "CSC3058")
        normalized_req = re.sub(r'\s+', '-', req_upper)
        normalized_req = re.sub(r'^([A-Z]{2,5})(\d{3,4})', r'\1-\2', normalized_req)
        exact = next((c["course_id"] for c in catalog_list if c["course_id"].upper() == normalized_req), None)
        if exact:
            resolved.append(exact)
            continue
        # Expand acronyms before keyword matching
        expanded = _expand_acronyms(req)
        req_keywords = {w for w in expanded.split() if w not in _STOP_WORDS and len(w) > 2}
        if not req_keywords:
            unresolved.append(req)
            continue
        best_score = 0
        best_course = None
        for c in catalog_list:
            title_words = {w for w in c.get("title", "").lower().split() if w not in _STOP_WORDS and len(w) > 2}
            overlap = len(req_keywords & title_words)
            if overlap > best_score:
                best_score = overlap
                best_course = c
        # Require at least half the meaningful keywords to match
        min_required = max(1, len(req_keywords) // 2)
        if best_course and best_score >= min_required:
            resolved.append(best_course["course_id"])
        else:
            unresolved.append(req)
    return resolved, unresolved


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
    in_progress_raw = profile.get("in_progress_courses", [])
    completed_ids = {course["course_id"] for course in completed_courses_raw}
    completed_courses = [
        CompletedCourse(
            course_id=course["course_id"],
            title=course_lookup.get(course["course_id"], {}).get("title", course.get("source_course_title", "Unknown Course")),
            term=course.get("term"),
            grade=course.get("grade"),
            credits=int(course.get("credits", course_lookup.get(course["course_id"], {}).get("credits", 0))),
        )
        for course in completed_courses_raw
    ]
    # Append in-progress courses so current semester appears in the history
    # Use catalog credits since transcript stores 0 for in-progress courses
    completed_courses += [
        CompletedCourse(
            course_id=course["course_id"],
            title=course_lookup.get(course["course_id"], {}).get("title", course.get("source_course_title", "Unknown Course")),
            term=course.get("term"),
            grade="In Progress",
            credits=int(course_lookup.get(course["course_id"], {}).get("credits", 0)),
        )
        for course in in_progress_raw
    ]

    recommended_courses, skipped_notes, total_recommended_credits = _apply_adk_plan(
        adk_plan=adk_plan,
        course_lookup=course_lookup,
    )

    # 3-state credit breakdown
    in_progress_ids = {course["course_id"] for course in in_progress_raw}
    credits_completed = sum(
        int(course.get("credits", course_lookup.get(course["course_id"], {}).get("credits", 0)))
        for course in completed_courses_raw
    )
    credits_in_progress = sum(
        int(course_lookup.get(course["course_id"], {}).get("credits", 0))
        for course in in_progress_raw
    )
    credits_earned = credits_completed + credits_in_progress

    from tools.catalog_tools import get_total_credits_required
    student_type = profile.get("student_type", "undergraduate")
    total_credits_required = get_total_credits_required(major, student_type)
    credits_remaining_to_degree = max(total_credits_required - credits_earned, 0)

    # 3-state course breakdown
    req_set = set(required_courses)
    required_completed = sum(1 for course_id in required_courses if course_id in completed_ids)
    required_in_progress = sum(1 for course_id in required_courses if course_id in in_progress_ids)
    required_remaining = max(len(required_courses) - required_completed - required_in_progress, 0)
    percent_complete = round((required_completed / len(required_courses)) * 100, 1) if required_courses else 0.0

    # Required course credit breakdown
    required_credits_completed = sum(
        int(course.get("credits", course_lookup.get(course["course_id"], {}).get("credits", 0)))
        for course in completed_courses_raw
        if course["course_id"] in req_set
    )
    required_credits_in_progress = sum(
        int(course_lookup.get(course["course_id"], {}).get("credits", 0))
        for course in in_progress_raw
        if course["course_id"] in req_set
    )

    # Elective / gen-ed breakdown (everything not in required list)
    elective_courses_completed = sum(1 for c in completed_courses_raw if c["course_id"] not in req_set)
    elective_credits_completed = credits_completed - required_credits_completed
    elective_courses_in_progress = sum(1 for c in in_progress_raw if c["course_id"] not in req_set)
    elective_credits_in_progress = credits_in_progress - required_credits_in_progress
    required_credits_total = sum(int(course_lookup.get(cid, {}).get("credits", 0)) for cid in required_courses)
    elective_credits_total = max(total_credits_required - required_credits_total, 0)
    elective_credits_remaining = max(elective_credits_total - elective_credits_completed - elective_credits_in_progress, 0)

    notes = [
        AdvisingNote(
            level="success",
            title="Google ADK workflow active",
            message="The dashboard recommendations were generated by the live GradPath multi-agent flow.",
        ),
        *extra_notes,
    ]
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

    # Build multi-semester graduation plan
    current_semester = profile.get("current_semester", "Spring 2026")
    student_type = profile.get("student_type", "undergraduate")
    completed_courses_raw = profile.get("completed_courses", [])
    completed_terms = {c.get("term") for c in completed_courses_raw if c.get("term")}
    if current_semester:
        completed_terms.add(current_semester)
    semesters_used = len(completed_terms)

    # Use LLM-generated full plan if available, otherwise fall back to Python planner
    llm_full_plan = adk_plan.get("full_plan") if adk_plan else None

    if llm_full_plan:
        # LLM generated the full plan — use it directly
        planned_semesters = [
            PlannedSemester(
                term=sem["term"],
                total_credits=sem.get("total_credits", sum(
                    int(course_lookup.get(cid, {}).get("credits", 0)) for cid in sem.get("courses", [])
                )),
                courses=[
                    PlannedCourse(
                        course_id=cid,
                        title=course_lookup.get(cid, {}).get("title", "Unknown Course"),
                        credits=int(course_lookup.get(cid, {}).get("credits", 0)),
                    )
                    for cid in sem.get("courses", [])
                ],
            )
            for sem in llm_full_plan
        ]
        # Inject any user-requested electives the LLM didn't include
        elective_ids = profile.get("elective_course_ids", [])
        if elective_ids:
            planned_semesters, skipped_electives = _inject_electives(
                planned_semesters, elective_ids, course_lookup, max_credits=DEFAULT_MAX_CREDITS
            )
            if skipped_electives:
                elective_names = [
                    f"{cid} ({course_lookup.get(cid, {}).get('title', 'Unknown')})"
                    for cid in skipped_electives
                ]
                notes.append(AdvisingNote(
                    level="info",
                    title="Elective courses not yet scheduled",
                    message=(
                        f"{', '.join(elective_names)} couldn't fit within your current plan. "
                        "You can take these as an extra semester or adjust your credit load."
                    ),
                ))
        # Add graduation note from LLM if present
        graduation_note = adk_plan.get("graduation_note")
        can_graduate_on_time = adk_plan.get("can_graduate_on_time", True)
        if not can_graduate_on_time and graduation_note:
            notes.append(AdvisingNote(
                level="warning",
                title="Cannot finish on time",
                message=graduation_note,
            ))
        elif graduation_note:
            notes.append(AdvisingNote(
                level="info",
                title="Graduation timeline",
                message=graduation_note,
            ))
    else:
        # Fallback to Python planner
        in_progress_ids = {course["course_id"] for course in in_progress_raw}
        graduation_result = build_full_graduation_plan(
            major=major,
            completed_course_ids=list(completed_ids),
            in_progress_course_ids=list(in_progress_ids),
            credits_already_earned=credits_earned,
            current_semester=current_semester,
            max_credits_per_semester=DEFAULT_MAX_CREDITS,
            min_credits_per_semester=DEFAULT_MIN_CREDITS,
            student_type=student_type,
            semesters_used=semesters_used,
            elective_course_ids=profile.get("elective_course_ids"),
        )
        raw_planned = graduation_result["planned"]
        unplanned = graduation_result["unplanned"]
        unplanned_electives = graduation_result.get("unplanned_electives", [])
        remaining_semesters = graduation_result["remaining_semesters"]
        total_semesters = graduation_result["total_semesters"]

        if unplanned:
            notes.append(AdvisingNote(
                level="warning",
                title="Cannot finish on time",
                message=(
                    f"You have used {semesters_used} of {total_semesters} semesters. "
                    f"With {remaining_semesters} semester(s) remaining, "
                    f"{len(unplanned)} required course(s) could not be scheduled: "
                    f"{', '.join(unplanned[:5])}{'...' if len(unplanned) > 5 else ''}. "
                    "Consider speaking with your advisor about overloading or extending your program."
                ),
            ))
        if unplanned_electives:
            catalog = load_catalog_data()
            cat_list = catalog if isinstance(catalog, list) else catalog.get("courses", [])
            cat_lookup = {c["course_id"]: c for c in cat_list}
            elective_names = [
                f"{cid} ({cat_lookup.get(cid, {}).get('title', 'Unknown')})"
                for cid in unplanned_electives
            ]
            notes.append(AdvisingNote(
                level="info",
                title="Elective courses not yet scheduled",
                message=(
                    f"{', '.join(elective_names)} couldn't fit within your standard graduation timeline "
                    "because required courses fill the available credit slots. "
                    "You can take these as an extra semester or work with your advisor to adjust your credit load."
                ),
            ))

        planned_semesters = [
            PlannedSemester(
                term=sem["term"],
                total_credits=sem["total_credits"],
                courses=[
                    PlannedCourse(
                        course_id=cid,
                        title=course_lookup.get(cid, {}).get("title", "Unknown Course"),
                        credits=int(course_lookup.get(cid, {}).get("credits", 0)),
                    )
                    for cid in sem["course_ids"]
                ],
            )
            for sem in raw_planned
        ]

    return DashboardData(
        student=StudentSnapshot(
            student_name=profile.get("student_name", "Unknown Student"),
            student_id=profile.get("student_id", profile.get("student_ref", "Unknown")),
            major=major,
            current_semester=current_semester,
            source=profile.get("source", "student_registry"),
            student_type=student_type,
            gpa=profile.get("gpa"),
            expected_graduation=profile.get("expected_graduation"),
            career_goal=profile.get("career_goal"),
            preferences=profile.get("preferences"),
            email=profile.get("email"),
        ),
        completed_courses=completed_courses,
        progress_summary=ProgressSummary(
            major=major,
            target_semester=target_semester,
            credits_completed=credits_completed,
            credits_in_progress=credits_in_progress,
            credits_remaining=credits_remaining_to_degree,
            credits_earned=credits_earned,
            total_credits_required=total_credits_required,
            required_courses_total=len(required_courses),
            required_courses_completed=required_completed,
            required_courses_in_progress=required_in_progress,
            required_courses_remaining=required_remaining,
            required_credits_completed=required_credits_completed,
            required_credits_in_progress=required_credits_in_progress,
            elective_courses_completed=elective_courses_completed,
            elective_credits_completed=elective_credits_completed,
            elective_courses_in_progress=elective_courses_in_progress,
            elective_credits_in_progress=elective_credits_in_progress,
            elective_credits_remaining=elective_credits_remaining,
            percent_complete=percent_complete,
            total_recommended_credits=total_recommended_credits,
        ),
        recommended_courses=recommended_courses,
        advising_notes=notes,
        planned_semesters=planned_semesters,
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

    # Group skipped courses by reason and generate summary notes
    skipped_by_reason: Dict[str, List[str]] = {}
    for skipped in adk_plan.get("skipped_courses", []):
        course_id = skipped.get("course_id", "UNKNOWN")
        reason = skipped.get("reason", "deferred")
        if course_id == "TRANSCRIPT":
            continue
        skipped_by_reason.setdefault(reason, []).append(course_id)

    completed_list = skipped_by_reason.get("completed", [])
    prereq_list = skipped_by_reason.get("unmet_prerequisites", [])
    not_offered_list = skipped_by_reason.get("not_offered", [])
    credit_list = skipped_by_reason.get("credit_limit", [])

    # Build one paragraph summary note
    summary_parts = []

    if completed_list:
        summary_parts.append(
            f"{len(completed_list)} required course{'s are' if len(completed_list) != 1 else ' is'} already completed and counted toward your degree."
        )

    if prereq_list:
        prereq_str = ", ".join(prereq_list[:3]) + ("..." if len(prereq_list) > 3 else "")
        summary_parts.append(
            f"{len(prereq_list)} course{'s' if len(prereq_list) != 1 else ''} ({prereq_str}) {'are' if len(prereq_list) != 1 else 'is'} waiting on prerequisites — complete earlier courses first to unlock {'them' if len(prereq_list) != 1 else 'it'}."
        )

    if not_offered_list:
        summary_parts.append(
            f"{len(not_offered_list)} course{'s are' if len(not_offered_list) != 1 else ' is'} not offered this semester and will be available in a future term."
        )

    if credit_list:
        summary_parts.append(
            f"{len(credit_list)} course{'s were' if len(credit_list) != 1 else ' was'} deferred to the next semester to stay within the credit cap."
        )

    if summary_parts:
        notes.append(AdvisingNote(
            level="info",
            title="Degree Progress Summary",
            message=" ".join(summary_parts),
        ))

    total_credits = int(adk_plan.get("total_recommended_credits", 0))
    return recommended, notes, total_credits


def _build_reply_text(
    dashboard: DashboardData,
    target_semester: str,
    adk_plan: Optional[Dict[str, Any]] = None,
    message: str = "",
    profile: Optional[Dict[str, Any]] = None,
) -> str:
    student = dashboard.student
    career_goal = (profile or {}).get("career_goal")
    reasoning = (adk_plan or {}).get("reasoning", {})
    skipped = (adk_plan or {}).get("skipped_courses", [])

    # Check if the student cannot graduate on time — surface this in chat
    cannot_graduate = not (adk_plan or {}).get("can_graduate_on_time", True)
    if not cannot_graduate:
        cannot_graduate = any(
            n.title == "Cannot finish on time" for n in (dashboard.advising_notes or [])
        )
    advisor_warning = (
        "Your required courses cannot fit within the standard graduation timeline. "
        "Your plan below shows the best schedule possible — please contact your academic advisor "
        "to discuss your options.\n\n"
        if cannot_graduate else ""
    )

    # Count skipped reasons
    skipped_reasons: Dict[str, List[str]] = {}
    for s in skipped:
        skipped_reasons.setdefault(s.get("reason", "other"), []).append(s.get("course_id", ""))

    if not dashboard.recommended_courses:
        base = advisor_warning
        base += f"I reviewed your record for {target_semester} but couldn't find any eligible courses right now."
        if skipped_reasons.get("unmet_prerequisites"):
            base += f" Most required courses are locked behind prerequisites you haven't completed yet."
        if career_goal:
            base += f" For your goal of becoming a {career_goal}, you'll need to work through the prerequisite chain first before relevant courses become available."
        return base

    course_list = ", ".join(
        f"{c.course_id} ({c.title})" for c in dashboard.recommended_courses
    )

    # Build opening line
    if career_goal:
        reply = advisor_warning + f"I've updated your plan for {target_semester} with your goal of becoming a {career_goal} in mind. "
    else:
        reply = advisor_warning + f"I've updated your plan for {target_semester}. "

    reply += f"Here's what I recommend: {course_list}. "

    # Add reasoning for each course if available
    if reasoning:
        reply += "\n\n"
        for course in dashboard.recommended_courses:
            reason = reasoning.get(course.course_id)
            if reason:
                reply += f"• **{course.course_id}** — {reason}\n"

    # Explain what was skipped and why
    unmet = skipped_reasons.get("unmet_prerequisites", [])
    in_progress = skipped_reasons.get("in_progress", [])
    not_offered = skipped_reasons.get("not_offered", [])

    if career_goal and (unmet or not_offered):
        reply += f"\nFor your {career_goal} goal, some relevant courses couldn't be added this semester"
        if unmet:
            reply += f" — {', '.join(unmet[:3])} require prerequisites you haven't completed yet"
        if not_offered:
            reply += f" — {', '.join(not_offered[:3])} aren't offered this semester"
        reply += ". These will open up as you progress."

    if in_progress:
        reply += f"\n\nNote: {', '.join(in_progress)} are currently in progress and will unlock more courses once completed."

    return reply.strip()



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
