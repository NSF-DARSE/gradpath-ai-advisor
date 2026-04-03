"""API routes for the GradPath web UI."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..models import ChatResponse, SessionBootstrap
from ..services.agent_adapter import (
    analyze_request,
    build_assistant_message,
    build_placeholder_dashboard,
    build_schema_example,
    build_user_message,
    build_welcome_history,
)
from ..services.session_store import SessionStore
from ..services.transcript_parser import parse_upload


def build_chat_router(session_store: SessionStore) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["gradpath-ui"])

    @router.get("/session", response_model=SessionBootstrap)
    def create_session() -> SessionBootstrap:
        history = build_welcome_history()
        dashboard = build_placeholder_dashboard()
        session_id = session_store.create(dashboard=dashboard, history=history)
        return SessionBootstrap(session_id=session_id, dashboard=dashboard, history=history)

    @router.get("/schema")
    def get_schema_example() -> Dict[str, Any]:
        return build_schema_example().model_dump()

    @router.post("/chat", response_model=ChatResponse)
    async def chat_with_gradpath(
        session_id: str = Form(...),
        message: str = Form(""),
        transcript: Optional[UploadFile] = File(default=None),
    ) -> ChatResponse:
        state = session_store.get(session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Session not found. Refresh to start a new session.")

        parsed_transcript = None
        attachment_name = None

        if transcript is not None and transcript.filename:
            attachment_name = transcript.filename
            file_bytes = await transcript.read()
            try:
                parsed_transcript = parse_upload(transcript.filename, file_bytes)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not message.strip() and parsed_transcript is None:
            raise HTTPException(status_code=400, detail="Enter a message or upload a transcript.")

        user_text = message.strip() or "Please analyze the uploaded transcript and update my plan."
        user_message = build_user_message(user_text, attachment_name=attachment_name)

        try:
            analysis = await analyze_request(
                user_text, parsed_transcript, session_id, session_profile=state.profile
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        assistant_message = build_assistant_message(analysis.reply_text)
        history = [*state.history, user_message, assistant_message]
        session_store.save(
            session_id=session_id,
            dashboard=analysis.dashboard,
            history=history,
            profile=analysis.profile,
        )

        return ChatResponse(
            session_id=session_id,
            reply=assistant_message,
            dashboard=analysis.dashboard,
            history=history,
        )

    return router
