"""FastAPI entrypoint for the GradPath web UI."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# Register 'Gradpath' package under lowercase 'gradpath' alias so agents can
# import from `gradpath.*` regardless of how uvicorn was launched.
_root = Path(__file__).resolve().parents[2]
_parent = _root.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))
_pkg = importlib.import_module(_root.name)
sys.modules.setdefault("gradpath", _pkg)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import API_TITLE, API_VERSION, FRONTEND_DIST_DIR, FRONTEND_ORIGIN
from .routers.chat import build_chat_router
from .services.session_store import SessionStore


session_store = SessionStore()

app = FastAPI(title=API_TITLE, version=API_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(build_chat_router(session_store))


if FRONTEND_DIST_DIR.exists():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST_DIR / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        requested_file = FRONTEND_DIST_DIR / full_path
        if full_path and requested_file.exists() and requested_file.is_file():
            return FileResponse(requested_file)
        return FileResponse(FRONTEND_DIST_DIR / "index.html")
else:
    @app.get("/", include_in_schema=False)
    async def frontend_missing() -> dict:
        return {
            "message": "GradPath backend is running, but the frontend is not built yet.",
            "next_step": "Run `npm install` and `npm run build` inside `frontend/`, then restart the backend.",
        }
