# Known Issues

Honest list of limitations and bugs in v1.0.0. Each entry names the impact and the workaround if one exists.

## Performance / Scalability

### 1. Gemini API quota caps concurrent users

**Impact.** GradPath relies on the Google Gemini API (via Google ADK). Default free-tier quota allows ~60 requests per minute. Under concurrent load the planner pipeline will hit rate limits and return errors.

**Workaround.** Run one session at a time for local use. For production, upgrade to a paid Gemini API tier and configure `GOOGLE_API_KEY` with a quota-enabled key.

### 2. Multi-agent pipeline adds 3–8 s latency per query

**Impact.** Each student query passes through the greeting agent → guardrails → planner agent chain. Cold-start on first message can take up to 8 s depending on Gemini response time.

**Workaround.** No workaround for latency itself. The InMemoryRunner is reused across messages in a session to avoid repeated initialization overhead.

## Transcript Parsing

### 3. PDF transcript parsing is brittle on non-standard layouts

**Impact.** The PDF parser uses heuristic text extraction. Transcripts with scanned images, two-column layouts, or non-UTF-8 encodings may parse incorrectly or return empty fields.

**Workaround.** Upload transcripts as JSON or plain text (`.txt`) for reliable parsing. The JSON schema is documented in `data/transcripts/`.

### 4. Duplicate course detection is keyword-based

**Impact.** If a course appears twice in a transcript with slightly different names (e.g., `CISC 101` vs `Intro to CS — CISC 101`), deduplication may miss it and count the course twice toward completion.

**Workaround.** Review the parsed transcript in the UI before running the planner.

## Planning

### 5. Course catalog is static JSON — not live from the university system

**Impact.** The catalog in `data/catalogs/` was last updated at project submission time. New courses, retired courses, and updated prerequisites are not reflected.

**Workaround.** Manually update `data/catalogs/` JSON files to reflect current offerings.

### 6. Planner does not check real-time seat availability

**Impact.** The multi-semester plan recommends courses without knowing whether sections are full. A suggested course may be unavailable for registration.

**Workaround.** Cross-check the generated plan against the live course registration system before advising.

### 7. No user authentication

**Impact.** Any student ID can be queried. There is no login or access control. In a production deployment this would be a privacy violation.

**Workaround.** Deploy behind a university SSO or VPN for any real-student use.