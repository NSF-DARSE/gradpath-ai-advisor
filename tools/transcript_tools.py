"""Tools for reading transcript data and integrating transcript parsing with ADK."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from .transcript_parser import parse_transcript_pdf, transcript_from_json


LOGGER = logging.getLogger(__name__)

# Base folder for all data files.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
TRANSCRIPT_JSON_STATE_KEY = "transcript_json"
TRANSCRIPT_PROFILE_STATE_KEY = "transcript_profile"
TRANSCRIPT_SOURCE_STATE_KEY = "transcript_source"
TRANSCRIPT_STATUS_STATE_KEY = "transcript_status"
TRANSCRIPT_ARTIFACT_NAME = "transcript_structured.json"


def load_transcript_data(student_id: str) -> Dict[str, Any]:
    """Load one student's transcript JSON by student_id.

    Example: student_id='s1001' -> data/transcripts/student_s1001.json
    """

    file_path = TRANSCRIPTS_DIR / f"student_{student_id}.json"
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_completed_courses(student_id: str) -> List[str]:
    """Return only the list of completed course IDs for a student."""

    transcript = load_transcript_data(student_id)
    completed = transcript.get("completed_courses", [])
    return [course["course_id"] for course in completed]


async def extract_transcript_to_json(
    pdf_path: Optional[str] = None,
    file_uri: Optional[str] = None,
    artifact_name: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Read a transcript PDF, parse it deterministically, and store the result in ADK state/artifacts."""

    if tool_context is None:
        raise ValueError("ToolContext is required so GradPath can store transcript state and artifacts.")

    # If transcript was already parsed (e.g. by the backend before ADK ran), return the cached result.
    existing_json = tool_context.state.get(TRANSCRIPT_JSON_STATE_KEY)
    if existing_json is not None:
        return {
            "status": tool_context.state.get(TRANSCRIPT_STATUS_STATE_KEY, "success"),
            "message": "Transcript already parsed and cached in session state.",
            "transcript_json_state_key": TRANSCRIPT_JSON_STATE_KEY,
            "transcript_artifact_name": TRANSCRIPT_ARTIFACT_NAME,
            "source": tool_context.state.get(TRANSCRIPT_SOURCE_STATE_KEY, "cached"),
        }

    try:
        resolved_source = _resolve_source(pdf_path=pdf_path, file_uri=file_uri, artifact_name=artifact_name, tool_context=tool_context)
    except ValueError:
        return {
            "status": "missing",
            "message": "No transcript file was uploaded. The workflow will continue using the student registry instead.",
            "transcript_json_state_key": TRANSCRIPT_JSON_STATE_KEY,
            "transcript_artifact_name": None,
        }

    if resolved_source["kind"] == "artifact":
        file_bytes = await _load_artifact_bytes(tool_context, resolved_source["name"])
        source_label = resolved_source["name"]
    else:
        source_path = Path(resolved_source["path"]).expanduser().resolve()
        file_bytes = source_path.read_bytes()
        source_label = str(source_path)

    parse_result = parse_transcript_pdf(file_bytes)
    transcript_payload = parse_result.transcript.model_dump() if parse_result.transcript else None

    tool_context.state[TRANSCRIPT_SOURCE_STATE_KEY] = source_label
    tool_context.state[TRANSCRIPT_STATUS_STATE_KEY] = parse_result.status

    response: Dict[str, Any] = {
        "status": parse_result.status,
        "message": parse_result.message,
        "warnings": list(parse_result.warnings),
        "transcript_json_state_key": TRANSCRIPT_JSON_STATE_KEY,
        "transcript_artifact_name": TRANSCRIPT_ARTIFACT_NAME,
        "source": source_label,
    }

    if transcript_payload is not None:
        tool_context.state[TRANSCRIPT_JSON_STATE_KEY] = transcript_payload
        tool_context.state[TRANSCRIPT_PROFILE_STATE_KEY] = parse_result.transcript.to_planner_profile()
        await tool_context.save_artifact(
            TRANSCRIPT_ARTIFACT_NAME,
            types.Part.from_text(text=json.dumps(transcript_payload, indent=2)),
        )
        response["transcript"] = transcript_payload
    else:
        response["transcript"] = None

    return response


def get_transcript_json_from_state(tool_context: ToolContext) -> Dict[str, Any]:
    """Return the transcript JSON previously stored in ADK session state."""

    transcript_json = tool_context.state.get(TRANSCRIPT_JSON_STATE_KEY)
    status = tool_context.state.get(TRANSCRIPT_STATUS_STATE_KEY)
    if transcript_json is None:
        return {
            "status": status or "missing",
            "message": "No transcript JSON is stored in the current GradPath session yet.",
            "transcript": None,
        }

    validated = transcript_from_json(transcript_json)
    return validated.to_payload()


def get_transcript_profile_from_state(tool_context: ToolContext) -> Dict[str, Any]:
    """Return the planner-friendly profile generated from transcript JSON state."""

    profile = tool_context.state.get(TRANSCRIPT_PROFILE_STATE_KEY)
    if profile is None:
        return {
            "status": "missing",
            "message": "No transcript profile is stored in the current GradPath session yet.",
        }
    return profile


def _resolve_source(
    *,
    pdf_path: Optional[str],
    file_uri: Optional[str],
    artifact_name: Optional[str],
    tool_context: ToolContext,
) -> Dict[str, str]:
    if pdf_path:
        return {"kind": "path", "path": pdf_path}

    if file_uri:
        if file_uri.startswith("file://"):
            return {"kind": "path", "path": file_uri.replace("file://", "", 1)}
        return {"kind": "path", "path": file_uri}

    selected_artifact = artifact_name or tool_context.state.get("transcript_artifact_name")
    if selected_artifact:
        return {"kind": "artifact", "name": str(selected_artifact)}

    cached_path = tool_context.state.get("transcript_pdf_path")
    if cached_path:
        return {"kind": "path", "path": str(cached_path)}

    raise ValueError("Provide a PDF path, file URI, or uploaded transcript artifact reference.")


async def _load_artifact_bytes(tool_context: ToolContext, artifact_name: str) -> bytes:
    artifact = await tool_context.load_artifact(artifact_name)
    if artifact is None:
        raise ValueError(f"Transcript artifact '{artifact_name}' was not found in the current session.")
    if getattr(artifact, "inline_data", None) and getattr(artifact.inline_data, "data", None):
        return artifact.inline_data.data
    if getattr(artifact, "text", None):
        return artifact.text.encode("utf-8")
    raise ValueError(f"Transcript artifact '{artifact_name}' does not contain readable PDF bytes.")


extract_transcript_tool = FunctionTool(extract_transcript_to_json)
get_transcript_json_tool = FunctionTool(get_transcript_json_from_state)
get_transcript_profile_tool = FunctionTool(get_transcript_profile_from_state)
