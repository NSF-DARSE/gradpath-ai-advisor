"""Unit tests for guardrail input validation."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Import guardrails directly to avoid agents/__init__.py, which transitively
# imports catalog_agent and other agents that require the 'gradpath' package
# to be installed (they use 'from gradpath.tools import ...' style paths).
_guardrails_path = Path(__file__).resolve().parents[1] / "src" / "backend" / "agents" / "guardrails.py"
_spec = importlib.util.spec_from_file_location("agents.guardrails", _guardrails_path)
_guardrails = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guardrails)

MAX_INPUT_CHARS = _guardrails.MAX_INPUT_CHARS
check_input = _guardrails.check_input


def _make_context(message: str):
    """Build a minimal CallbackContext stub with a single text part."""
    part = MagicMock()
    part.text = message
    content = MagicMock()
    content.parts = [part]
    ctx = MagicMock()
    ctx.user_content = content
    return ctx


class GuardrailLengthTests(unittest.TestCase):
    def test_message_over_limit_is_blocked(self) -> None:
        long_msg = "course " * 300  # academic keywords but over 2000 chars
        result = check_input(_make_context(long_msg))
        self.assertIsNotNone(result)
        text = result.parts[0].text
        self.assertIn(str(len(long_msg.strip())), text)
        self.assertIn(str(MAX_INPUT_CHARS), text)

    def test_message_at_limit_passes(self) -> None:
        # Exactly MAX_INPUT_CHARS chars with an academic keyword — length guard does not fire (not over limit)
        academic_prefix = "What courses should I take? "
        padding = "x" * (MAX_INPUT_CHARS - len(academic_prefix))
        msg = academic_prefix + padding
        self.assertEqual(len(msg), MAX_INPUT_CHARS)
        result = check_input(_make_context(msg))
        self.assertIsNone(result)

    def test_empty_message_passes(self) -> None:
        result = check_input(_make_context(""))
        self.assertIsNone(result)


class GuardrailOffTopicTests(unittest.TestCase):
    def test_long_off_topic_message_is_blocked(self) -> None:
        # 121+ chars, no academic keywords, does not start with a greeting phrase
        off_topic = "My favorite recipes involve fresh ingredients from local markets. " * 3
        result = check_input(_make_context(off_topic))
        self.assertIsNotNone(result)
        self.assertIn("GradPath", result.parts[0].text)

    def test_short_message_always_passes(self) -> None:
        # ≤ 120 chars with no academic keywords — should not be blocked
        result = check_input(_make_context("What is the weather today?"))
        self.assertIsNone(result)

    def test_academic_keyword_in_long_message_passes(self) -> None:
        msg = ("I want to know about my " + "major " + "and stuff. " * 20).strip()
        self.assertGreater(len(msg), 120)
        result = check_input(_make_context(msg))
        self.assertIsNone(result)


class GuardrailGreetingTests(unittest.TestCase):
    def test_hi_greeting_passes(self) -> None:
        self.assertIsNone(check_input(_make_context("hi there")))

    def test_hello_greeting_passes(self) -> None:
        self.assertIsNone(check_input(_make_context("Hello, I need help")))

    def test_hey_greeting_passes(self) -> None:
        self.assertIsNone(check_input(_make_context("hey what can you do")))

    def test_good_morning_passes(self) -> None:
        self.assertIsNone(check_input(_make_context("Good morning!")))

    def test_what_is_gradpath_passes(self) -> None:
        self.assertIsNone(check_input(_make_context("What's GradPath?")))


class GuardrailNullInputTests(unittest.TestCase):
    def test_none_content_passes(self) -> None:
        ctx = MagicMock()
        ctx.user_content = None
        self.assertIsNone(check_input(ctx))

    def test_no_parts_passes(self) -> None:
        content = MagicMock()
        content.parts = []
        ctx = MagicMock()
        ctx.user_content = content
        self.assertIsNone(check_input(ctx))


if __name__ == "__main__":
    unittest.main()
