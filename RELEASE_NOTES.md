# Release Notes — v1.0.0

**Release date:** 2026-05-18
**Tag:** `v1.0.0`
**Status:** Initial release

---

## At a glance

GradPath is an AI-powered academic advisor that takes a student's transcript and produces a personalized, prerequisite-aware multi-semester course plan. It combines a transcript parsing pipeline, a multi-agent planning system built on Google ADK, and a web UI — all running locally in under four commands.

## Highlights

- **Two-pipeline architecture.** Transcript ingestion (PDF → normalized JSON) and multi-semester planning run as separate, independently testable pipelines.
- **Google ADK multi-agent system.** A greeting agent handles conversation and routes to a planner agent that generates prerequisite-checked semester schedules.
- **Guardrails on every message.** Input and output guardrails reject off-topic queries and flag unsafe content before responses reach the user.
- **Web UI included.** A React + FastAPI UI ships in the same repo. Run one script and the browser opens automatically.
- **Transcript flexibility.** Accepts PDF, plain text, and JSON transcripts. Parsed profiles are auto-registered for reuse across sessions.

## What's in v1.0.0

### Core features
- `tools/transcript_parser.py` — PDF, text, and JSON transcript parsing with GPA extraction, course deduplication, and normalized output schema
- `tools/planning_tools.py` — prerequisite graph traversal, credit load validation, multi-semester schedule generation
- `tools/catalog_tools.py` — static course catalog lookup with prerequisite chains
- `agents/greeting_agent.py` — ADK-based conversational agent with guardrails
- `src/backend/` — FastAPI backend with session management, ADK service, and transcript upload endpoint
- `src/frontend/` — React UI with chat interface and transcript upload

### Infrastructure
- `.github/workflows/tests.yml` — CI runs the full test suite on every push
- `pyproject.toml` — package metadata and dependency pinning
- `requirements.txt` — pinned runtime dependencies

## Known limitations

See [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for a full list. Key ones: Gemini API rate limits, static course catalog, no authentication, PDF parsing brittleness.

## How to run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd src/frontend && npm install && npm run build && cd ../..
python scripts/run_gradpath_ui.py
```

Browser opens at `http://127.0.0.1:8000`.