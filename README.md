# GradPath

GradPath is an AI-powered academic planning assistant built around your existing Google ADK workflow. This repo now includes a full local web UI with:

- a modern two-column student/advisor experience
- a right-side chatbot for all user interaction
- a left-side read-only dashboard that updates only from GradPath analysis
- transcript upload support for `.json`, `.txt`, `.md`, and text-based `.pdf` files
- a FastAPI wrapper layer so you can plug in your current Google ADK agent without replacing it

## What Was Added

```text
gradpath/
├── backend/
│   └── app/
│       ├── main.py                    # FastAPI app + static frontend serving
│       ├── models.py                  # API and dashboard schemas
│       ├── routers/chat.py            # Session bootstrap + chat/upload routes
│       └── services/
│           ├── agent_adapter.py       # Maps ADK/planning output into the UI schema
│           ├── adk_service.py         # Runs the live Google ADK workflow for web sessions
│           ├── session_store.py       # In-memory chat session state
│           └── transcript_parser.py   # Upload parsing helpers
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx
│       ├── styles.css
│       ├── lib/api.ts
│       └── components/
│           ├── ChatPanel.tsx
│           ├── DashboardCard.tsx
│           └── DashboardPanel.tsx
├── run_gradpath_ui.py                 # Starts the local site and opens the browser
└── requirements.txt                   # Backend dependencies
```

## Architecture

- Frontend: React + Vite + TypeScript
- Backend: FastAPI
- Existing planning logic: your current Python GradPath agent/tooling
- UI contract: the backend returns structured dashboard data and chat responses in one API call

The user only interacts through chat. The dashboard cards are read-only and are updated only from backend analysis results.

## How The Web Flow Works

1. The browser opens a GradPath session with `GET /api/session`.
2. The student types a message and can optionally upload a transcript file.
3. `POST /api/chat` sends the message and file to FastAPI.
4. The backend parses the upload, resolves a known student record if possible, and runs the ADK workflow when it can.
5. The adapter returns:
   - chat reply text
   - completed courses
   - degree progress summary
   - recommended courses
   - advising notes
6. The frontend updates:
   - the chat thread on the right
   - the read-only dashboard cards on the left

## Google ADK Integration Point

The UI is designed to wrap your existing agent, not replace it.

The main connection points are:

- [backend/app/services/agent_adapter.py](/Users/arunr3ddy/Documents/New project/gradpath/backend/app/services/agent_adapter.py)
- [backend/app/services/adk_service.py](/Users/arunr3ddy/Documents/New project/gradpath/backend/app/services/adk_service.py)

The web app now attempts to run the real ADK multi-agent flow first for known student records and maps the planner output into the dashboard schema. If the live ADK call cannot run, the backend falls back to the local planning adapter so the site still works during development or when transcript uploads do not map to the current ADK tools.

## API Routes

- `GET /api/session`
  Returns the initial placeholder dashboard and starter chat history.

- `POST /api/chat`
  Accepts `multipart/form-data`:
  - `session_id`
  - `message`
  - `transcript` optional file

- `GET /api/schema`
  Returns an example structured dashboard response shape for frontend/reference use.

## Example Structured Response Schema

`GET /api/schema` returns data shaped like this:

```json
{
  "completed_courses": [
    {
      "course_id": "CS101",
      "title": "Intro to Programming",
      "term": "Fall 2025",
      "grade": "A",
      "credits": 3
    }
  ],
  "progress_summary": {
    "major": "CS",
    "target_semester": "Fall 2026",
    "credits_earned": 6,
    "required_courses_total": 10,
    "required_courses_completed": 2,
    "required_courses_remaining": 8,
    "percent_complete": 20.0,
    "total_recommended_credits": 9
  },
  "recommended_courses": [
    {
      "course_id": "CS201",
      "title": "Discrete Mathematics for CS",
      "credits": 3,
      "reason": "Fits remaining degree requirements, prerequisites, and term availability."
    }
  ],
  "advising_notes": [
    {
      "level": "success",
      "title": "Plan generated",
      "message": "Prepared recommendations for Fall 2026."
    }
  ]
}
```

## Transcript Upload Behavior

Supported uploads:

- `.json`
- `.txt`
- `.md`
- `.pdf` if the PDF already contains extractable text

Notes:

- Scanned PDFs without embedded text will fail gracefully with a clear error.
- Uploaded files are used only through the chat workflow.
- The uploaded filename is shown in the chat panel.
- The dashboard is not directly editable by the user.

## Running The Full Project Locally

### 1. Backend setup

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you are on Windows PowerShell, use:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Frontend setup

```bash
cd frontend
npm install
npm run build
cd ..
```

This creates `frontend/dist`, which FastAPI serves as the website.

### 3. Start the GradPath website

```bash
python run_gradpath_ui.py
```

That will:

- start the FastAPI server on `http://127.0.0.1:8000`
- open the local website in your browser

## Frontend Dev Mode

If you want live React hot reload during UI work:

Terminal 1:

```bash
uvicorn backend.app.main:app --reload
```

Terminal 2:

```bash
cd frontend
npm run dev
```

Then open `http://localhost:5173`.

## Environment Variables

Copy `.env.example` to `.env` and fill in what you need.

```env
GOOGLE_API_KEY=your_google_api_key_here
GRADPATH_USE_ADK_WRAPPER=true
GRADPATH_DEFAULT_TARGET_SEMESTER=Fall 2026
GRADPATH_DEFAULT_MAX_CREDITS=9
GRADPATH_FRONTEND_ORIGIN=http://localhost:5173
```

Meaning:

- `GOOGLE_API_KEY`: needed for your existing Google ADK setup
- `GRADPATH_USE_ADK_WRAPPER`: enables the live ADK workflow and falls back locally if the agent cannot complete
- `GRADPATH_DEFAULT_TARGET_SEMESTER`: fallback term when the student does not specify one
- `GRADPATH_DEFAULT_MAX_CREDITS`: fallback credit load
- `GRADPATH_FRONTEND_ORIGIN`: CORS origin for Vite dev mode

## Reasonable Assumptions Made

- The current GradPath repo is primarily a local Python project and did not yet include a dedicated website.
- Student-facing dashboard data should be derived from existing normalized transcript/catalog/schedule data when available.
- If a student references a known ID like `s1`, `T1`, or `s1001`, the UI should use the existing data registry.
- If the current ADK pipeline does not yet emit the exact structured schema needed by the UI, the adapter layer should provide that schema now.
- Uploaded transcript parsing should work for structured or text-based files first, with graceful failure for scan-only PDFs.

## Key Files To Customize Next

- [backend/app/services/agent_adapter.py](/Users/arunr3ddy/Documents/New project/gradpath/backend/app/services/agent_adapter.py)
- [backend/app/services/transcript_parser.py](/Users/arunr3ddy/Documents/New project/gradpath/backend/app/services/transcript_parser.py)
- [frontend/src/App.tsx](/Users/arunr3ddy/Documents/New project/gradpath/frontend/src/App.tsx)
- [frontend/src/components/DashboardPanel.tsx](/Users/arunr3ddy/Documents/New project/gradpath/frontend/src/components/DashboardPanel.tsx)
- [frontend/src/components/ChatPanel.tsx](/Users/arunr3ddy/Documents/New project/gradpath/frontend/src/components/ChatPanel.tsx)

## Verification Checklist

After install/build, verify:

- the site loads in the browser
- the chat panel accepts text
- transcript upload works
- the dashboard updates only after the API responds
- placeholder states show before any analysis
- errors display clearly for unsupported or unparseable transcript files
