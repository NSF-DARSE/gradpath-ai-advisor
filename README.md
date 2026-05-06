# GradPath — AI-Powered Academic Planning Assistant

GradPath is an AI-powered academic advising tool built for Lincoln University students. It helps students figure out which courses to take next semester — and maps out their full graduation roadmap — based on their transcript, declared major, and Lincoln University's real course catalog and schedule data.

A student uploads their transcript PDF and GradPath automatically:
- Parses their academic history (completed courses, in-progress courses, GPA, credits earned)
- Checks which required major courses they still need and which prerequisites are satisfied
- Verifies semester availability from the real LU schedule
- Recommends a personalized next-semester course plan
- Generates a full multi-semester graduation roadmap
- Displays a live dashboard with a 3-state degree progress breakdown (Core/Major + Electives)
- Remembers the student across follow-up messages in the same session

---

## Table of Contents

- [What We Built](#what-we-built)
- [Key Features](#key-features)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Data](#data)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Running the Project](#running-the-project)
- [API Endpoints](#api-endpoints)
- [Supported Transcript Uploads](#supported-transcript-uploads)
- [Majors Supported](#majors-supported-29)
- [Evaluation](#evaluation)
- [Tests](#tests)
- [Known Limitations / Future Work](#known-limitations--future-work)
- [Contributing](#contributing)
- [License](#license)

---

## What We Built

This project combines a multi-agent AI backend with a full web UI:

- **Two ADK pipelines** using Google ADK (SequentialAgent + ParallelAgent) with Gemini 2.5 Flash
  - **Full pipeline** (first message): greeting → [transcript + catalog in parallel] → history → planner
  - **Slim pipeline** (follow-up): intent detection → planner only (skips transcript re-parsing)
- **Guardrails** on every pipeline entry point — off-topic blocking and input length limit via ADK `before_agent_callback`
- **FastAPI backend** with session memory, transcript uploads, and structured JSON responses
- **React + Vite frontend** — two-panel layout (dashboard left, chat right), print/PDF export
- **Real Lincoln University data** — 597 courses, 29 majors, Spring 2026 schedule with 468+ sections

---

## Key Features

### Multi-Semester Graduation Plan
GradPath doesn't just recommend next semester's courses — it builds a full semester-by-semester roadmap from the student's current position to graduation, respecting:
- Prerequisite chains (recursive transitive dependency resolution)
- Credit limits per semester (configurable, default 9–12)
- Total degree credit requirement (120 UG / 36 Graduate / 60 PhD)
- Courses already in progress (not re-scheduled)

### 3-State Degree Progress Summary
The dashboard shows a clear split between:

| Section | Tracks |
|---|---|
| **Core / Major Courses** | Required courses from the major requirements list |
| **Electives & Gen Ed** | All other completed / in-progress courses |

Each section shows Completed / In Progress / Remaining with a segmented credit bar (green = done, blue = in progress, gray = remaining).

### In-Progress Course Awareness
Courses the student is currently taking are recognized as a distinct state — they count toward earned credits and are never re-scheduled in future semesters.

### What-If Scenario Support
Students can ask things like "What if I switch to Biology?" or "What if I can only take 12 credits?" — the intent agent detects the change, updates the profile, and re-runs the planner with the new parameters.

### Guardrails
Every pipeline entry point blocks:
- Messages over 2,000 characters
- Off-topic messages with no academic keywords (greetings and short messages always pass)

### Print / Export
A "Download Plan" button appears once a graduation plan is generated and triggers a clean `@media print` layout with all accordions expanded.

---

## Project Structure

```
gradpath/
├── agent.py                          # Root ADK pipelines (full + follow-up)
├── run_gradpath_ui.py                # One-command project launcher
├── evaluate.py                       # DAG-based evaluation framework
├── requirements.txt
├── agents/
│   ├── greeting_agent.py             # Collects target semester and credit limit
│   ├── transcript_agent.py           # Parses uploaded transcript PDF
│   ├── history_agent.py              # Summarizes completed courses
│   ├── catalog_agent.py              # Loads major requirements and schedule
│   ├── planner_agent.py              # Recommends next-semester courses + full plan
│   └── guardrails.py                 # before_agent_callback: length + off-topic guard
├── tools/
│   ├── catalog_tools.py              # Reads catalog, major requirements, credit totals
│   ├── schedule_tools.py             # Reads semester schedule JSON
│   ├── planning_tools.py             # Python planner: multi-semester graduation plan
│   ├── student_tools.py              # Loads student profiles from registry
│   ├── transcript_tools.py           # ADK tool for transcript extraction
│   └── transcript_schema.py          # Pydantic schemas + course ID normalization
├── backend/
│   └── app/
│       ├── main.py                   # FastAPI app entry point
│       ├── models.py                 # API response schemas (ProgressSummary etc.)
│       ├── config.py                 # Credit limits and env config
│       ├── routers/chat.py           # /api/session and /api/chat endpoints
│       └── services/
│           ├── agent_adapter.py      # Converts ADK output → dashboard data
│           ├── adk_service.py        # Runs ADK pipelines (InMemoryRunner, reused)
│           ├── session_store.py      # In-memory session + profile persistence
│           └── transcript_parser.py  # Upload parsing for the web API
├── frontend/
│   └── src/
│       ├── App.tsx                   # Root component, session + chat state
│       ├── types.ts                  # TypeScript types for all API shapes
│       ├── styles.css                # All styles including print media query
│       └── components/
│           ├── ChatPanel.tsx         # Chat thread, composer, file upload
│           ├── DashboardPanel.tsx    # Dashboard cards, accordions, progress bars
│           └── DashboardCard.tsx     # Card shell component
├── data/
│   ├── catalogs/
│   │   ├── catalog_2026.json         # 597 LU courses
│   │   └── major_requirements.json   # Required courses + credit totals for 29 majors
│   ├── schedules/
│   │   ├── spring_2026.json          # 468 sections
│   │   ├── summer_2026_gc.json       # 17 sections (Graduate Center)
│   │   └── summer_2026_ol.json       # 64 sections (Online)
│   ├── transcripts/                  # Pre-loaded student profiles + sample PDFs
│   └── eval/
│       └── eval_cases.json           # Evaluation test cases
├── tests/
│   ├── test_e2e.py                   # End-to-end full pipeline tests
│   ├── test_guardrails.py            # Input guardrail unit tests
│   ├── test_integration.py           # API + agent integration tests
│   ├── test_performance.py           # Planning performance benchmarks
│   ├── test_transcript_parser.py     # PDF column-parser unit tests
│   └── test_transcript_tools.py      # Transcript tool unit tests
└── scripts/
    ├── extract_catalog_pdf_text.py   # Parse LU catalog PDFs → JSON
    ├── ingest_schedule_pdfs.py       # Parse LU schedule PDFs → JSON
    ├── extract_majors.py             # Extract major requirements from catalog
    └── parse_all.py                  # Batch pdfplumber runner for transcripts
```

---

## How It Works

### Full Request Flow (First Message)

1. Student opens the app — a new session is created with a blank dashboard
2. Student uploads their transcript PDF or types their student ID
3. FastAPI runs `pdfplumber` to extract transcript text (two-column layout aware)
4. Gemini parses raw text into structured JSON (courses, GPA, student info)
5. Course codes are normalized to canonical LU format (`CSC1058` → `CSC-1058`)
6. Failed grades (F, NP, NC, U) are excluded from completed courses
7. In-progress courses (current semester, grade = CIP/IP) are tracked separately
8. The student profile is passed to the **full ADK pipeline**:

```
greeting_agent       →  determines target semester and max credits per semester
  ├── transcript_agent ┐
  └── catalog_agent    ┘  (run in parallel via ParallelAgent)
history_agent        →  extracts completed and in-progress course IDs
planner_agent        →  checks prerequisites, availability, credit cap → outputs plan
```

9. The planner outputs:
   - `recommended_courses` — what to take next semester
   - `full_plan` — complete semester-by-semester roadmap to graduation
   - `can_graduate_on_time` + `graduation_note`
10. The dashboard updates live

### Follow-Up Message Flow

Follow-up messages skip the transcript and catalog agents and use a slim pipeline:

```
followup_intent_agent   →  detects "chat", "question", or "plan_change"
                            + extracts any changed inputs (major, credits, semester)
followup_planner_agent  →  re-runs with updated profile if intent is "plan_change"
```

This keeps follow-ups fast and avoids redundant re-parsing.

### Session Memory

After the first message the student profile (major, completed courses, in-progress courses, semester) is saved in `SessionStore` and restored on every subsequent message. The transcript does not need to be re-uploaded.

### Transcript Parsing

LU transcripts use a two-column PDF layout. The parser (`tools/transcript_schema.py`, `backend/app/services/transcript_parser.py`) handles:
- Column-aware line splitting via `pdfplumber`
- Fragment buffering for course titles that wrap across PDF lines
- Course ID normalization from multiple source formats to canonical dash-separated IDs
- CIP (Currently In Progress) detection by grade value

---

## Tech Stack

| Component | Technology |
|---|---|
| AI Agents | Google ADK (SequentialAgent, ParallelAgent, LlmAgent) |
| LLM | Gemini 2.5 Flash |
| Backend | FastAPI + Uvicorn |
| Frontend | React 18 + Vite + TypeScript |
| PDF Parsing | pdfplumber + pypdf |
| Data Validation | Pydantic v2 |
| Session Memory | In-memory SessionStore (ADK InMemoryRunner) |
| Build | Vite (frontend static build served by FastAPI) |

---

## Data

All data was parsed from real Lincoln University PDF files:

| File | Source | Size |
|---|---|---|
| `catalog_2026.json` | LU Academic Catalog 2026 | 597 courses, 44 departments |
| `major_requirements.json` | LU degree requirements | 29 majors, required courses + credit caps |
| `spring_2026.json` | LU Spring 2026 Schedule | 468 sections |
| `summer_2026_gc.json` | LU Summer 2026 GC Schedule | 17 sections |
| `summer_2026_ol.json` | LU Summer 2026 Online Schedule | 64 sections |

---

## Prerequisites

- Python 3.11 or higher
- Node.js 18 or higher (for frontend build)
- A Google API key with access to the Gemini API
  - Get one at [console.cloud.google.com](https://console.cloud.google.com/apis/credentials)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/ArunReddyVittedi/gradpath1.git
cd gradpath1
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\Activate.ps1
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

Create a `.env` file in the project root:

```env
GOOGLE_API_KEY=your_google_api_key_here
GRADPATH_TRANSCRIPT_LLM_MODEL=gemini-2.5-flash
GRADPATH_DEFAULT_TARGET_SEMESTER=Fall 2026
GRADPATH_DEFAULT_MAX_CREDITS=9
GRADPATH_FRONTEND_ORIGIN=http://localhost:5173
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_API_KEY` | Yes | — | Google Gemini API key |
| `GRADPATH_TRANSCRIPT_LLM_MODEL` | No | `gemini-2.5-flash` | LLM model for transcript parsing |
| `GRADPATH_DEFAULT_TARGET_SEMESTER` | No | `Fall 2026` | Default planning target semester |
| `GRADPATH_DEFAULT_MAX_CREDITS` | No | `9` | Max credits per semester |
| `GRADPATH_FRONTEND_ORIGIN` | No | `http://localhost:5173` | Allowed CORS origin for dev mode |

### 5. Build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

---

## Running the Project

### Production mode (recommended)

```bash
python run_gradpath_ui.py
```

Opens at **http://127.0.0.1:8000** — the backend serves the pre-built frontend.

### Development mode (hot-reload frontend)

Run the backend and frontend separately:

```bash
# Terminal 1 — backend
uvicorn backend.app.main:app --reload --port 8000

# Terminal 2 — frontend (hot reload at http://localhost:5173)
cd frontend
npm run dev
```

---

## API Endpoints

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/session` | Start a new session, returns blank dashboard |
| `POST` | `/api/chat` | Send message + optional transcript, returns updated dashboard |
| `GET` | `/api/schema` | Example response shape for reference |

### `POST /api/chat`

Accepts `multipart/form-data`:

| Field | Type | Required | Description |
|---|---|---|---|
| `session_id` | string | Yes | Session ID from `/api/session` |
| `message` | string | Yes | Student's chat message |
| `transcript` | file | No | PDF (or `.json`/`.txt`) transcript upload |

Returns a full `DashboardData` JSON object including `student`, `progress_summary`, `completed_courses`, `recommended_courses`, `planned_semesters`, and `advising_notes`.

---

## Supported Transcript Uploads

| Format | Notes |
|---|---|
| `.pdf` | Text-based PDFs — most LU transcripts |
| `.json` | Pre-structured student profile |
| `.txt` / `.md` | Plain text transcript export |

Scanned / image-only PDFs cannot be parsed and will return an "OCR required" message.

---

## Majors Supported (29)

| Code | Major |
|---|---|
| CS | Computer Science |
| BIO | Biology |
| CHE | Chemistry |
| BIOCHEM | Biochemistry |
| FORENSIC | Forensic Science |
| ENV | Environmental Science |
| PHY | Physics |
| HSC | Health Science |
| COM | Communication |
| MAT | Mathematics |
| HIS | History |
| PHL | Philosophy |
| MUS | Music |
| PAS | Pan-Africana Studies |
| POL | Political Science |
| PSY | Psychology |
| HUS | Human Services |
| ART | Visual Arts |
| SOC | Sociology |
| ENG | English |
| ACC | Accounting |
| FIN | Finance |
| MGT | Management |
| ISM | Information Systems Management |
| CRJ | Criminal Justice |
| ANT | Anthropology |
| REL | Religion |
| FRE | French |
| SPN | Spanish |

---

## Evaluation

`evaluate.py` runs a DAG-based correctness check against the deterministic graduation planner. For each test case in `data/eval/eval_cases.json`, it verifies:

1. No completed courses are repeated in the plan
2. Prerequisites are satisfied before each course is scheduled
3. Credit limit is respected every semester
4. No course appears twice in the plan
5. All required major courses are eventually covered
6. The plan completes within the allowed semester limit

```bash
python evaluate.py
```

---

## Tests

Six test modules covering the full stack (~1,125 lines):

| File | What it tests |
|---|---|
| `tests/test_transcript_parser.py` | Two-column PDF parser, wrapped-line handling, grade normalization |
| `tests/test_transcript_tools.py` | ADK transcript tool, course ID normalization, dedup logic |
| `tests/test_guardrails.py` | Off-topic blocking, length limit, greeting pass-through |
| `tests/test_integration.py` | API endpoints, session lifecycle, dashboard field completeness |
| `tests/test_e2e.py` | End-to-end full pipeline with real student profiles |
| `tests/test_performance.py` | Planning throughput, response time benchmarks |

```bash
# Run all tests
python -m pytest tests/

# Run a specific module
python -m pytest tests/test_transcript_parser.py -v
```

---

## Known Limitations / Future Work

| Item | Notes |
|---|---|
| **Fall 2026 schedule** | Not yet available — fall planning infers availability from the catalog |
| **Session persistence** | Session memory is in-memory only and is cleared when the server restarts. A database-backed `SessionStore` is the primary planned next step. |
| **Scanned PDFs** | Image-only transcript PDFs require OCR preprocessing before upload |
| **Multi-user concurrency** | The current in-memory store is not designed for high-concurrency production deployments |

---

## Contributing

1. Fork the repository and create a feature branch
2. Make your changes — keep commits focused and descriptive
3. Run the test suite: `python -m pytest tests/`
4. Open a pull request with a clear description of the change

Please do not commit API keys, student transcript PDFs, or other private data.

---

## License

The source code in this repository is licensed under the **Apache License 2.0**. See [`LICENSE`](LICENSE).

```
Copyright 2026 GradPath contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
```

Student transcripts, uploaded student records, API keys/secrets, and third-party Lincoln University catalog or schedule source materials are not covered by this license and should not be redistributed without the appropriate permission.
