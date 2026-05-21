"""Configuration helpers for the GradPath web backend."""

from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
FRONTEND_DIST_DIR = ROOT_DIR / "src" / "frontend" / "dist"

API_TITLE = "GradPath UI API"
API_VERSION = "1.0.0"

FRONTEND_ORIGIN = os.getenv("GRADPATH_FRONTEND_ORIGIN", "http://localhost:5173")
DEFAULT_MAX_CREDITS = int(os.getenv("GRADPATH_DEFAULT_MAX_CREDITS", "12"))
DEFAULT_MIN_CREDITS = int(os.getenv("GRADPATH_DEFAULT_MIN_CREDITS", "9"))
