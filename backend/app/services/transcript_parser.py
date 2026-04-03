"""Backend adapter for transcript uploads that reuses the shared GradPath parser."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.transcript_parser import parse_transcript_pdf, parse_transcript_text, transcript_from_json


@dataclass
class ParsedTranscript:
    filename: str
    raw_text: str
    profile: Optional[Dict[str, Any]]
    warnings: List[str]
    transcript_json: Optional[Dict[str, Any]]
    status: str
    message: str
    content_bytes: Optional[bytes] = None


def parse_upload(filename: str, content: bytes) -> ParsedTranscript:
    """Parse an uploaded transcript file into the shared normalized schema."""

    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        return _parse_json_upload(filename, content)
    if suffix in {".txt", ".md"}:
        return _parse_text_upload(filename, content)
    if suffix == ".pdf":
        return _parse_pdf_upload(filename, content)
    raise ValueError("Unsupported transcript file type. Upload JSON, TXT, MD, or PDF.")


def _parse_json_upload(filename: str, content: bytes) -> ParsedTranscript:
    payload = json.loads(content.decode("utf-8"))
    result = transcript_from_json(payload)
    return _build_parsed_transcript(
        filename=filename,
        result=result,
        content_bytes=content,
    )


def _parse_text_upload(filename: str, content: bytes) -> ParsedTranscript:
    text = content.decode("utf-8", errors="ignore")
    result = parse_transcript_text(text, extraction_method="text")
    return _build_parsed_transcript(
        filename=filename,
        result=result,
        content_bytes=content,
    )


def _parse_pdf_upload(filename: str, content: bytes) -> ParsedTranscript:
    result = parse_transcript_pdf(content)
    return _build_parsed_transcript(
        filename=filename,
        result=result,
        content_bytes=content,
    )


def _build_parsed_transcript(filename: str, result: Any, content_bytes: bytes) -> ParsedTranscript:
    transcript_json = result.transcript.model_dump() if result.transcript else None
    profile = result.transcript.to_planner_profile() if result.transcript else None
    return ParsedTranscript(
        filename=filename,
        raw_text=result.raw_text,
        profile=profile,
        warnings=list(result.warnings),
        transcript_json=transcript_json,
        status=result.status,
        message=result.message,
        content_bytes=content_bytes,
    )
