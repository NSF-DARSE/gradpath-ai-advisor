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
- Prerequisite chains
- Credit limits per semester (configurable)
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
│   └── transcripts/                  # Pre-loaded student profiles (JSON)
├── scripts/
│   └── parse_all.py                  # pdfplumber parser for LU PDFs
├── run_gradpath_ui.py                # One-command project launcher
└── requirements.txt
```

---

## How It Works

### Full Request Flow (First Message)

1. Student opens the app — a new session is created with a blank dashboard
2. Student uploads their transcript PDF or types their student ID
3. FastAPI runs `pdfplumber` to extract transcript text
4. Gemini parses raw text into structured JSON (courses, GPA, student info)
5. Course codes are normalized to canonical LU format (`CSC1058` → `CSC-1058`)
6. Failed grades (F, NP, NC, U) are excluded from completed courses
7. In-progress courses (current semester) are tracked separately
8. The student profile is passed to the **full ADK pipeline**:

```
greeting_agent        → determines target semester and max credits per semester
  ├── transcript_agent  ┐
  └── catalog_agent     ┘  (run in parallel)
history_agent         → extracts completed and in-progress course IDs
planner_agent         → checks prerequisites, availability, credit cap → outputs plan
```

9. The planner outputs:
   - `recommended_courses` — what to take next semester
   - `full_plan` — complete semester-by-semester roadmap to graduation
   - `can_graduate_on_time` + `graduation_note`
10. The dashboard updates live

### Follow-Up Message Flow

Follow-up messages skip the transcript and catalog agents and use a slim pipeline:

```
intent_agent   → detects "chat", "question", or "plan_change" + extracts any profile changes
planner_agent  → re-runs with updated profile if intent is "plan_change"
```

This keeps follow-ups fast and avoids redundant re-parsing.

### Session Memory

After the first message the student profile (major, completed courses, in-progress courses, semester) is saved in `SessionStore` and restored on every subsequent message. The transcript does not need to be re-uploaded.

---

## Data

All data was parsed from real Lincoln University PDF files:

| File | Source | Size |
|---|---|---|
| `catalog_2026.json` | LU Academic Catalog 2026 | 597 courses, 44 departments |
| `major_requirements.json` | LU degree requirements | 29 majors, required courses + 120 cr cap |
| `spring_2026.json` | LU Spring 2026 Schedule | 468 sections |
| `summer_2026_gc.json` | LU Summer 2026 GC Schedule | 17 sections |
| `summer_2026_ol.json` | LU Summer 2026 Online Schedule | 64 sections |

---

## Tech Stack

| Component | Technology |
|---|---|
| AI Agents | Google ADK (SequentialAgent, ParallelAgent, LlmAgent) |
| LLM | Gemini 2.5 Flash |
| Backend | FastAPI + Uvicorn |
| Frontend | React + Vite + TypeScript |
| PDF Parsing | pdfplumber |
| Data Validation | Pydantic v2 |
| Session Memory | InMemoryRunner (reused across messages) |

---

## Running the Project

### 1. Clone and set up the environment

```bash
git clone https://github.com/ArunReddyVittedi/gradpath1.git
cd gradpath1
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Set up your API key

Copy `.env.example` to `.env` and add your Google API key:

```env
GOOGLE_API_KEY=your_google_api_key_here
GRADPATH_TRANSCRIPT_LLM_MODEL=gemini-2.5-flash
GRADPATH_FRONTEND_ORIGIN=http://localhost:5173
```

Get a free key at [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials).

### 3. Build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

### 4. Run

```bash
python run_gradpath_ui.py
```

Opens at **http://127.0.0.1:8000**

---

## API Endpoints

| Method | Route | Description |
|---|---|---|
| GET | `/api/session` | Start a new session, returns blank dashboard |
| POST | `/api/chat` | Send message + optional transcript, returns updated dashboard |
| GET | `/api/schema` | Example response shape for reference |

`POST /api/chat` accepts `multipart/form-data`:
- `session_id` — from `/api/session`
- `message` — student's chat message
- `transcript` — optional PDF file upload

---

## Supported Transcript Uploads

- `.pdf` — text-based PDFs (most LU transcripts)
- `.json`, `.txt`, `.md` — structured or plain text

Scanned / image-only PDFs return an "OCR required" message.

---

## Majors Supported (29)

CS, BIO, CHE, BIOCHEM, HSC, ACC, FIN, MGT, ISM, CRJ, ANT, SOC, PSY, COM, HIS, PHL, ENG, MUS, ART, MAT, PHY, ENV, POL, HUS, PAS, REL, FRE, SPN, FORENSIC

---

## Known Limitations

- Fall 2026 schedule data is not yet available — fall planning infers availability from the catalog
- Session memory is in-memory only — cleared when the server restarts
- Scanned PDF transcripts require OCR preprocessing before upload
