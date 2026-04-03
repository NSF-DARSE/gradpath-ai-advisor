"""Configuration helpers for the GradPath web backend."""

from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST_DIR = ROOT_DIR / "frontend" / "dist"

API_TITLE = "GradPath UI API"
API_VERSION = "1.0.0"

FRONTEND_ORIGIN = os.getenv("GRADPATH_FRONTEND_ORIGIN", "http://localhost:5173")
