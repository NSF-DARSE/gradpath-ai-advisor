"""Google ADK runner wrapper for the GradPath web UI."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from dotenv import load_dotenv
from google.adk.runners import InMemoryRunner
from google.genai import types

from tools.transcript_tools import (
    TRANSCRIPT_ARTIFACT_NAME,
    TRANSCRIPT_JSON_STATE_KEY,
    TRANSCRIPT_PROFILE_STATE_KEY,
    TRANSCRIPT_SOURCE_STATE_KEY,
    TRANSCRIPT_STATUS_STATE_KEY,
)

if TYPE_CHECKING:
    from .transcript_parser import ParsedTranscript


ROOT_DIR = Path(__file__).resolve().parents[4]


@dataclass
class AdkRunResult:
    final_text: str
    planner_json: Optional[Dict[str, Any]]
    raw_texts: List[str]
    target_semester: Optional[str]
    max_credits: Optional[int]
    greeting_json: Optional[Dict[str, Any]] = None
    full_plan: Optional[List[Dict[str, Any]]] = None  # LLM-generated multi-semester plan


class AdkRunnerService:
    """Runs the existing GradPath ADK workflow with in-memory web sessions."""

    def __init__(self) -> None:
        self._runner: Optional[InMemoryRunner] = None
        self._session_map: Dict[str, Dict[str, str]] = {}

    async def run_planner(
        self,
        *,
        web_session_id: str,
        message: str,
        student_id: str,
        student_name: str,
        major: str,
        current_semester: str,
        transcript: Optional["ParsedTranscript"],
        semesters_used: int = 0,
        student_type: str = "undergraduate",
    ) -> AdkRunResult:
        runner = self._get_runner()
        initial_state = _build_transcript_state(transcript)
        session_meta = await self._ensure_session(web_session_id, initial_state=initial_state)
        await self._save_transcript_artifacts(session_meta=session_meta, transcript=transcript)

        _total = {"undergraduate": 8, "graduate": 4, "phd": 10}.get(student_type, 8)
        _remaining = max(_total - semesters_used, 0)
        prompt = (
            f"My student_id is {student_id}.\n"
            f"My name is {student_name}.\n"
            f"My major is {major}.\n"
            f"My current semester is {current_semester}.\n"
            f"Semesters completed (including current): {semesters_used} of {_total}.\n"
            f"Semesters remaining after this one: {_remaining}. Plan exactly {_remaining} future semesters — no more.\n"
            f"{message.strip() or 'Please plan my next semester.'}\n"
            "Return the full GradPath planning result."
        )
        content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

        raw_texts: List[str] = []
        async for event in runner.run_async(
            user_id=session_meta["user_id"],
            session_id=session_meta["adk_session_id"],
            new_message=content,
        ):
            event_text = _extract_text(event)
            if event_text:
                raw_texts.append(event_text)

        final_text = raw_texts[-1] if raw_texts else ""
        planner_json = _extract_planner_json(raw_texts)
        greeting_json = _extract_greeting_json(raw_texts)
        target_semester = greeting_json.get("target_semester") if greeting_json else None
        max_credits_val = greeting_json.get("max_credits") if greeting_json else None
        max_credits = int(max_credits_val) if max_credits_val is not None else None
        full_plan = planner_json.get("full_plan") if planner_json else None
        return AdkRunResult(
            final_text=final_text,
            planner_json=planner_json,
            raw_texts=raw_texts,
            target_semester=target_semester,
            max_credits=max_credits,
            full_plan=full_plan,
        )

    async def run_followup_intent(
        self,
        *,
        web_session_id: str,
        message: str,
        profile: Dict[str, Any],
        remaining_courses: Optional[List[str]] = None,
    ) -> AdkRunResult:
        """Run just the greeting agent to detect intent and answer questions conversationally."""
        runner = self._get_followup_intent_runner()
        session_meta = await self._ensure_followup_intent_session(web_session_id)

        completed_ids = [c["course_id"] for c in profile.get("completed_courses", [])]
        in_progress_ids = [c["course_id"] for c in profile.get("in_progress_courses", [])]
        career_goal = profile.get("career_goal")
        prompt = (
            f"Student profile — major: {profile.get('major', 'CS')}, "
            f"current semester: {profile.get('current_semester', 'Unknown')}, "
            f"completed courses: {', '.join(completed_ids) or 'none'}"
            + (f", in-progress courses: {', '.join(in_progress_ids)}" if in_progress_ids else "")
            + (f", career goal: {career_goal}" if career_goal else "")
            + (f", remaining required courses: {', '.join(remaining_courses)}" if remaining_courses else "")
            + f".\n\nStudent message: {message.strip()}"
        )
        content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

        raw_texts: List[str] = []
        async for event in runner.run_async(
            user_id=session_meta["user_id"],
            session_id=session_meta["adk_session_id"],
            new_message=content,
        ):
            event_text = _extract_text(event)
            if event_text:
                raw_texts.append(event_text)

        final_text = raw_texts[-1] if raw_texts else ""
        greeting_json = _extract_greeting_json(raw_texts)
        conversational_text = _strip_json_from_text(final_text) if greeting_json else final_text
        return AdkRunResult(
            final_text=conversational_text,
            planner_json=None,
            raw_texts=raw_texts,
            target_semester=None,
            max_credits=None,
            greeting_json=greeting_json,
        )

    async def _ensure_followup_intent_session(self, web_session_id: str) -> Dict[str, str]:
        intent_key = f"intent-{web_session_id}"
        if intent_key in self._session_map:
            return self._session_map[intent_key]

        runner = self._get_followup_intent_runner()
        user_id = f"web-{web_session_id}"
        session = await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=f"adk-intent-{web_session_id}",
            state={},
        )
        meta = {"user_id": user_id, "adk_session_id": session.id}
        self._session_map[intent_key] = meta
        return meta

    def _get_followup_intent_runner(self) -> InMemoryRunner:
        if hasattr(self, "_followup_intent_runner") and self._followup_intent_runner is not None:
            return self._followup_intent_runner

        load_dotenv(ROOT_DIR / ".env")
        repo_parent = str(ROOT_DIR.parent)
        if repo_parent not in sys.path:
            sys.path.insert(0, repo_parent)

        from gradpath.agent import followup_intent_agent

        self._followup_intent_runner: Optional[InMemoryRunner] = InMemoryRunner(
            agent=followup_intent_agent, app_name="gradpath-intent"
        )
        return self._followup_intent_runner

    async def run_greeting(
        self,
        *,
        web_session_id: str,
        message: str,
    ) -> AdkRunResult:
        """Standalone conversational greeting — runs before any profile exists."""
        runner = self._get_greeting_runner()
        session_meta = await self._ensure_greeting_session(web_session_id)
        content = types.Content(role="user", parts=[types.Part.from_text(text=message)])

        raw_texts: List[str] = []
        async for event in runner.run_async(
            user_id=session_meta["user_id"],
            session_id=session_meta["adk_session_id"],
            new_message=content,
        ):
            event_text = _extract_text(event)
            if event_text:
                raw_texts.append(event_text)

        final_text = raw_texts[-1] if raw_texts else ""
        greeting_json = _extract_greeting_json(raw_texts)
        target_semester = greeting_json.get("target_semester") if greeting_json else None
        max_credits_val = greeting_json.get("max_credits") if greeting_json else None
        max_credits = int(max_credits_val) if max_credits_val is not None else None
        # Strip any leaked JSON blocks so the chat bubble shows only conversational text
        clean_text = _strip_json_from_text(final_text) if greeting_json else final_text
        return AdkRunResult(
            final_text=clean_text,
            planner_json=None,
            raw_texts=raw_texts,
            target_semester=target_semester,
            max_credits=max_credits,
            greeting_json=greeting_json,
        )

    async def _ensure_greeting_session(self, web_session_id: str) -> Dict[str, str]:
        greeting_key = f"greeting-{web_session_id}"
        if greeting_key in self._session_map:
            return self._session_map[greeting_key]

        runner = self._get_greeting_runner()
        user_id = f"web-{web_session_id}"
        session = await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=f"adk-greeting-{web_session_id}",
            state={},
        )
        meta = {"user_id": user_id, "adk_session_id": session.id}
        self._session_map[greeting_key] = meta
        return meta

    def _get_greeting_runner(self) -> InMemoryRunner:
        if hasattr(self, "_greeting_runner") and self._greeting_runner is not None:
            return self._greeting_runner

        load_dotenv(ROOT_DIR / ".env")
        repo_parent = str(ROOT_DIR.parent)
        if repo_parent not in sys.path:
            sys.path.insert(0, repo_parent)

        from gradpath.agent import standalone_greeting_agent

        self._greeting_runner: Optional[InMemoryRunner] = InMemoryRunner(
            agent=standalone_greeting_agent, app_name="gradpath-greeting"
        )
        return self._greeting_runner

    async def run_followup(
        self,
        *,
        web_session_id: str,
        message: str,
        profile: Dict[str, Any],
        semesters_used: int = 0,
        student_type: str = "undergraduate",
    ) -> AdkRunResult:
        """Slim pipeline for follow-up messages — runs greeting + planner only.

        The student profile (completed courses, major, transcript) is already
        known from the previous turn, so we inject it directly into the prompt
        and skip transcript_agent, history_agent, and catalog_agent entirely.
        """
        runner = self._get_followup_runner()
        session_meta = await self._ensure_followup_session(web_session_id)

        completed_ids = [c["course_id"] for c in profile.get("completed_courses", [])]
        in_progress_ids = [c["course_id"] for c in profile.get("in_progress_courses", [])]
        elective_ids = profile.get("elective_course_ids", [])
        career_goal = profile.get("career_goal")
        preferences = profile.get("preferences", "balanced")
        _total = {"undergraduate": 8, "graduate": 4, "phd": 10}.get(student_type, 8)
        _remaining = max(_total - semesters_used, 0)
        prompt = (
            f"My student_id is {profile.get('student_id', '')}.\n"
            f"My name is {profile.get('student_name', 'Student')}.\n"
            f"My major is {profile.get('major', 'CS')}.\n"
            f"My current semester is {profile.get('current_semester', 'Unknown')}.\n"
            f"Semesters completed (including current): {semesters_used} of {_total}.\n"
            f"Semesters remaining after this one: {_remaining}. Plan exactly {_remaining} future semesters — no more.\n"
            f"My completed courses are: {', '.join(completed_ids) or 'none'}.\n"
            + (f"My in-progress courses (being taken this semester — do NOT reschedule these): {', '.join(in_progress_ids)}.\n" if in_progress_ids else "")
            + (f"The following elective courses have already been identified and will be scheduled by the system: {', '.join(elective_ids)}. Do NOT substitute or replace these — just acknowledge them in your response.\n" if elective_ids else "")
            + f"My credits earned so far: {profile.get('credits_earned', 0)}.\n"
            + (f"My career goal is: {career_goal}.\n" if career_goal else "")
            + f"My preference is: {preferences}.\n"
            + f"{message.strip() or 'Please update my semester plan.'}\n"
            + "Return the full GradPath planning result."
        )
        content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

        raw_texts: List[str] = []
        async for event in runner.run_async(
            user_id=session_meta["user_id"],
            session_id=session_meta["adk_session_id"],
            new_message=content,
        ):
            event_text = _extract_text(event)
            if event_text:
                raw_texts.append(event_text)

        final_text = raw_texts[-1] if raw_texts else ""
        planner_json = _extract_planner_json(raw_texts)
        greeting_json = _extract_greeting_json(raw_texts)
        target_semester = greeting_json.get("target_semester") if greeting_json else None
        max_credits_val = greeting_json.get("max_credits") if greeting_json else None
        max_credits = int(max_credits_val) if max_credits_val is not None else None
        full_plan = planner_json.get("full_plan") if planner_json else None
        return AdkRunResult(
            final_text=final_text,
            planner_json=planner_json,
            raw_texts=raw_texts,
            target_semester=target_semester,
            max_credits=max_credits,
            greeting_json=greeting_json,
            full_plan=full_plan,
        )

    async def _ensure_followup_session(self, web_session_id: str) -> Dict[str, str]:
        """Get or create an ADK session for the slim follow-up pipeline."""
        followup_key = f"followup-{web_session_id}"
        if followup_key in self._session_map:
            return self._session_map[followup_key]

        runner = self._get_followup_runner()
        user_id = f"web-{web_session_id}"
        session = await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=f"adk-followup-{web_session_id}",
            state={},
        )
        meta = {"user_id": user_id, "adk_session_id": session.id}
        self._session_map[followup_key] = meta
        return meta

    def _get_followup_runner(self) -> InMemoryRunner:
        if hasattr(self, "_followup_runner") and self._followup_runner is not None:
            return self._followup_runner

        load_dotenv(ROOT_DIR / ".env")
        repo_parent = str(ROOT_DIR.parent)
        if repo_parent not in sys.path:
            sys.path.insert(0, repo_parent)

        from gradpath.agent import planner_only_agent

        self._followup_runner: Optional[InMemoryRunner] = InMemoryRunner(
            agent=planner_only_agent, app_name="gradpath-followup"
        )
        return self._followup_runner

    async def _ensure_session(
        self, web_session_id: str, initial_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        if web_session_id in self._session_map:
            return self._session_map[web_session_id]

        runner = self._get_runner()
        user_id = f"web-{web_session_id}"
        session = await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=f"adk-{web_session_id}",
            state=initial_state or {},
        )
        meta = {"user_id": user_id, "adk_session_id": session.id}
        self._session_map[web_session_id] = meta
        return meta

    async def _save_transcript_artifacts(
        self,
        *,
        session_meta: Dict[str, str],
        transcript: Optional["ParsedTranscript"],
    ) -> None:
        if transcript is None:
            return

        runner = self._get_runner()
        if transcript.transcript_json is not None:
            await runner.artifact_service.save_artifact(
                app_name=runner.app_name,
                user_id=session_meta["user_id"],
                session_id=session_meta["adk_session_id"],
                filename=TRANSCRIPT_ARTIFACT_NAME,
                artifact=types.Part.from_text(text=json.dumps(transcript.transcript_json, indent=2)),
            )

        if transcript.content_bytes is not None:
            mime_type = _mime_type_for_filename(transcript.filename)
            await runner.artifact_service.save_artifact(
                app_name=runner.app_name,
                user_id=session_meta["user_id"],
                session_id=session_meta["adk_session_id"],
                filename=transcript.filename,
                artifact=types.Part.from_bytes(data=transcript.content_bytes, mime_type=mime_type),
            )

    def _get_runner(self) -> InMemoryRunner:
        if self._runner is not None:
            return self._runner

        load_dotenv(ROOT_DIR / ".env")
        repo_parent = str(ROOT_DIR.parent)
        if repo_parent not in sys.path:
            sys.path.insert(0, repo_parent)

        from gradpath.agent import root_agent

        self._runner = InMemoryRunner(agent=root_agent, app_name="gradpath-ui")
        return self._runner


def get_adk_runner_service() -> AdkRunnerService:
    global _SERVICE
    try:
        return _SERVICE
    except NameError:
        _SERVICE = AdkRunnerService()
        return _SERVICE


def _build_transcript_state(transcript: Optional["ParsedTranscript"]) -> Dict[str, Any]:
    """Build the initial ADK session state dict from a parsed transcript."""
    if transcript is None:
        return {}
    state: Dict[str, Any] = {
        "transcript_artifact_name": transcript.filename,
        "transcript_source_filename": transcript.filename,
    }
    if transcript.status:
        state[TRANSCRIPT_STATUS_STATE_KEY] = transcript.status
    if transcript.transcript_json is not None:
        state[TRANSCRIPT_JSON_STATE_KEY] = transcript.transcript_json
        state[TRANSCRIPT_PROFILE_STATE_KEY] = transcript.profile or {}
        state[TRANSCRIPT_SOURCE_STATE_KEY] = transcript.filename
    return state


def _extract_text(event: Any) -> str:
    content = getattr(event, "content", None)
    if not content or not getattr(content, "parts", None):
        return ""

    text_parts: List[str] = []
    for part in content.parts:
        text = getattr(part, "text", None)
        if text:
            text_parts.append(text)
    return "\n".join(text_parts).strip()


def _extract_greeting_json(raw_texts: List[str]) -> Optional[Dict[str, Any]]:
    for text in raw_texts:
        parsed = _try_parse_json_blob(text)
        if parsed and isinstance(parsed, dict) and (
            ("target_semester" in parsed and "max_credits" in parsed)
            or "intent" in parsed
        ):
            return parsed
    return None


def _strip_json_from_text(text: str) -> str:
    """Remove JSON blocks from a mixed text+JSON response to get just the conversational part."""
    stripped = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", text, flags=re.DOTALL)
    stripped = re.sub(r"\{[^{}]*\"intent\"[^{}]*\}", "", stripped, flags=re.DOTALL)
    return stripped.strip()


def _extract_planner_json(raw_texts: List[str]) -> Optional[Dict[str, Any]]:
    for text in reversed(raw_texts):
        parsed = _try_parse_json_blob(text)
        if parsed and isinstance(parsed, dict) and "recommended_courses" in parsed:
            return parsed
    return None


def _try_parse_json_blob(text: str) -> Optional[Dict[str, Any]]:
    candidate = text.strip()
    if not candidate:
        return None

    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    for snippet in fenced:
        try:
            payload = json.loads(snippet)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            continue

    for snippet in _find_json_objects(candidate):
        try:
            payload = json.loads(snippet)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            continue
    return None


def _find_json_objects(text: str) -> List[str]:
    snippets: List[str] = []
    start = None
    depth = 0
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    snippets.append(text[start : index + 1])
                    start = None
    return snippets


def _mime_type_for_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".json":
        return "application/json"
    return "text/plain"
