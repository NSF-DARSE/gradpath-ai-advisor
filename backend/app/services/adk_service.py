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


ROOT_DIR = Path(__file__).resolve().parents[3]


@dataclass
class AdkRunResult:
    final_text: str
    planner_json: Optional[Dict[str, Any]]
    raw_texts: List[str]
    target_semester: Optional[str]
    max_credits: Optional[int]


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
    ) -> AdkRunResult:
        runner = self._get_runner()
        initial_state = _build_transcript_state(transcript)
        session_meta = await self._ensure_session(web_session_id, initial_state=initial_state)
        await self._save_transcript_artifacts(session_meta=session_meta, transcript=transcript)

        prompt = (
            f"My student_id is {student_id}.\n"
            f"My name is {student_name}.\n"
            f"My major is {major}.\n"
            f"My current semester is {current_semester}.\n"
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
        return AdkRunResult(
            final_text=final_text,
            planner_json=planner_json,
            raw_texts=raw_texts,
            target_semester=target_semester,
            max_credits=max_credits,
        )

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
        if parsed and isinstance(parsed, dict) and "target_semester" in parsed and "max_credits" in parsed:
            return parsed
    return None


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
