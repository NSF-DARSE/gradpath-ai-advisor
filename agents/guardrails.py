"""Guardrail callbacks for GradPath agents.

check_input — before_agent_callback
  Runs before any entry-point agent processes a message.
  Blocks inputs that are too long or clearly off-topic.
"""

from __future__ import annotations

import re
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.genai import types


MAX_INPUT_CHARS = 2000

_ACADEMIC_KEYWORDS = {
    "course", "class", "semester", "credit", "major", "minor", "grade", "gpa",
    "prerequisite", "prereq", "graduate", "graduation", "transcript", "schedule",
    "plan", "degree", "requirement", "enroll", "register", "advisor", "university",
    "lincoln", "program", "curriculum", "academic", "study", "studies", "department",
    "college", "fall", "spring", "summer", "csc", "mat", "bio", "psy", "eng",
    "his", "art", "mus", "soc", "che", "fin", "acc", "mgt", "crj", "com", "hsc",
    "transfer", "student", "id", "name", "my major", "my name", "my student",
}

# Short messages and opening greetings always pass through — they carry no academic
# keywords but are perfectly valid first messages to the advisor.
_GREETING_PATTERN = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|help|what can you|how (do|can) you|"
    r"good (morning|afternoon|evening)|what('?s| is) gradpath|tell me about)\b",
    re.IGNORECASE,
)


def check_input(callback_context: CallbackContext) -> Optional[types.Content]:
    """Block messages that are too long or clearly off-topic."""
    user_content = callback_context.user_content
    if not user_content or not getattr(user_content, "parts", None):
        return None

    message = " ".join(
        part.text for part in user_content.parts if getattr(part, "text", None)
    ).strip()

    if not message:
        return None

    # Guard 1: length limit
    if len(message) > MAX_INPUT_CHARS:
        return types.Content(
            role="model",
            parts=[types.Part.from_text(text=
                f"Your message is too long ({len(message)} characters). "
                f"Please keep it under {MAX_INPUT_CHARS} characters and try again."
            )],
        )

    # Guard 2: off-topic check
    # Short messages (<= 120 chars) and opening greetings always pass — they have
    # no academic keywords but are valid first-contact messages.
    if len(message) <= 120 or _GREETING_PATTERN.match(message):
        return None

    lower = message.lower()
    if not any(kw in lower for kw in _ACADEMIC_KEYWORDS):
        return types.Content(
            role="model",
            parts=[types.Part.from_text(text=
                "I'm GradPath, Lincoln University's AI academic advisor. "
                "I can only help with course planning, prerequisites, graduation requirements, "
                "and other academic topics. What can I help you with for your studies?"
            )],
        )

    return None
