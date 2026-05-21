"""Pytest configuration — add src/backend to sys.path so tests can import tools and agents."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "backend"))