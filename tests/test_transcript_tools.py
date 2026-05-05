"""Tests for transcript_tools: _resolve_source, get_completed_courses, and
the extract_transcript_to_json integration flow."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from tools.transcript_tools import (
    TRANSCRIPT_JSON_STATE_KEY,
    TRANSCRIPT_PROFILE_STATE_KEY,
    TRANSCRIPT_SOURCE_STATE_KEY,
    TRANSCRIPT_STATUS_STATE_KEY,
    _resolve_source,
    extract_transcript_to_json,
    get_completed_courses,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_context(state: dict | None = None):
    ctx = MagicMock()
    ctx.state = state or {}
    ctx.save_artifact = AsyncMock()
    ctx.load_artifact = AsyncMock(return_value=None)
    return ctx


# ---------------------------------------------------------------------------
# _resolve_source
# ---------------------------------------------------------------------------

class ResolveSourceTests(unittest.TestCase):

    def _ctx(self, state=None):
        ctx = MagicMock()
        ctx.state = state or {}
        return ctx

    def test_pdf_path_takes_priority(self) -> None:
        result = _resolve_source(
            pdf_path="/tmp/my.pdf",
            file_uri=None,
            artifact_name=None,
            tool_context=self._ctx(),
        )
        self.assertEqual(result, {"kind": "path", "path": "/tmp/my.pdf"})

    def test_file_uri_strips_scheme(self) -> None:
        result = _resolve_source(
            pdf_path=None,
            file_uri="file:///tmp/my.pdf",
            artifact_name=None,
            tool_context=self._ctx(),
        )
        self.assertEqual(result, {"kind": "path", "path": "/tmp/my.pdf"})

    def test_plain_file_uri_no_scheme(self) -> None:
        result = _resolve_source(
            pdf_path=None,
            file_uri="/tmp/my.pdf",
            artifact_name=None,
            tool_context=self._ctx(),
        )
        self.assertEqual(result, {"kind": "path", "path": "/tmp/my.pdf"})

    def test_explicit_artifact_name(self) -> None:
        result = _resolve_source(
            pdf_path=None,
            file_uri=None,
            artifact_name="transcript.pdf",
            tool_context=self._ctx(),
        )
        self.assertEqual(result, {"kind": "artifact", "name": "transcript.pdf"})

    def test_artifact_name_from_state(self) -> None:
        ctx = self._ctx(state={"transcript_artifact_name": "stored.pdf"})
        result = _resolve_source(
            pdf_path=None,
            file_uri=None,
            artifact_name=None,
            tool_context=ctx,
        )
        self.assertEqual(result, {"kind": "artifact", "name": "stored.pdf"})

    def test_cached_path_from_state(self) -> None:
        ctx = self._ctx(state={"transcript_pdf_path": "/data/cached.pdf"})
        result = _resolve_source(
            pdf_path=None,
            file_uri=None,
            artifact_name=None,
            tool_context=ctx,
        )
        self.assertEqual(result, {"kind": "path", "path": "/data/cached.pdf"})

    def test_raises_when_nothing_provided(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_source(
                pdf_path=None,
                file_uri=None,
                artifact_name=None,
                tool_context=self._ctx(),
            )


# ---------------------------------------------------------------------------
# get_completed_courses
# ---------------------------------------------------------------------------

class GetCompletedCoursesTests(unittest.TestCase):

    def _write_transcript(self, tmp_dir: str, student_id: str, data: dict) -> None:
        path = Path(tmp_dir) / f"student_{student_id}.json"
        path.write_text(json.dumps(data))

    def test_returns_completed_course_ids(self) -> None:
        data = {
            "completed_courses": [
                {"course_id": "CSC-1058"},
                {"course_id": "ENG-1001"},
            ],
            "in_progress_courses": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            self._write_transcript(tmp, "s001", data)
            with patch("tools.transcript_tools.TRANSCRIPTS_DIR", Path(tmp)):
                result = get_completed_courses("s001")
        self.assertEqual(sorted(result), ["CSC-1058", "ENG-1001"])

    def test_includes_in_progress_courses(self) -> None:
        data = {
            "completed_courses": [{"course_id": "CSC-1058"}],
            "in_progress_courses": [{"course_id": "CSC-2054"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            self._write_transcript(tmp, "s002", data)
            with patch("tools.transcript_tools.TRANSCRIPTS_DIR", Path(tmp)):
                result = get_completed_courses("s002")
        self.assertIn("CSC-1058", result)
        self.assertIn("CSC-2054", result)

    def test_raises_for_missing_student(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tools.transcript_tools.TRANSCRIPTS_DIR", Path(tmp)):
                with self.assertRaises(FileNotFoundError):
                    get_completed_courses("nonexistent")


# ---------------------------------------------------------------------------
# extract_transcript_to_json — integration
# ---------------------------------------------------------------------------

class ExtractTranscriptIntegrationTests(unittest.IsolatedAsyncioTestCase):

    async def test_returns_cached_result_when_state_already_has_json(self) -> None:
        ctx = _make_tool_context(state={
            TRANSCRIPT_JSON_STATE_KEY: {"student": {}},
            TRANSCRIPT_STATUS_STATE_KEY: "success",
            TRANSCRIPT_SOURCE_STATE_KEY: "prior_upload.pdf",
        })
        result = await extract_transcript_to_json(tool_context=ctx)

        self.assertEqual(result["status"], "success")
        self.assertIn("already parsed", result["message"])
        self.assertEqual(result["source"], "prior_upload.pdf")
        # Parse should not be called again
        ctx.save_artifact.assert_not_called()

    async def test_returns_missing_when_no_source_provided(self) -> None:
        ctx = _make_tool_context()
        result = await extract_transcript_to_json(tool_context=ctx)
        self.assertEqual(result["status"], "missing")

    async def test_raises_without_tool_context(self) -> None:
        with self.assertRaises(ValueError):
            await extract_transcript_to_json(pdf_path="/tmp/x.pdf", tool_context=None)

    async def test_parses_pdf_and_stores_state(self) -> None:
        from tools.transcript_parser import TranscriptParseResult
        from tools.transcript_schema import TranscriptDocument, TranscriptStudent

        fake_doc = TranscriptDocument(
            student=TranscriptStudent(name="Test Student", student_id="999"),
        )
        fake_result = TranscriptParseResult(
            status="success",
            message="Parsed OK",
            transcript=fake_doc,
            raw_text="Test Student",
        )

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake")
            pdf_path = f.name

        ctx = _make_tool_context()
        with patch("tools.transcript_tools.parse_transcript_pdf", return_value=fake_result):
            result = await extract_transcript_to_json(pdf_path=pdf_path, tool_context=ctx)

        self.assertEqual(result["status"], "success")
        self.assertIn(TRANSCRIPT_JSON_STATE_KEY, ctx.state)
        self.assertIn(TRANSCRIPT_PROFILE_STATE_KEY, ctx.state)
        ctx.save_artifact.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
