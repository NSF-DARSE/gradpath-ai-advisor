# Changelog

All notable changes to GradPath are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.7.0] — 2026-05-05

### Added
- Dual ADK pipeline: full pipeline for first message, slim pipeline for follow-ups (60% fewer LLM calls on follow-ups)
- Input guardrails on every entry point — blocks off-topic and oversized messages (>2000 chars)
- 3-state degree progress dashboard: Completed / In Progress / Remaining with credit breakdown
- What-if scenario support: "What if I switch to Biology?" or "What if I can only take 9 credits?"
- Print and PDF export of the graduation plan from the dashboard
- Full test suite: 66 tests across 6 files (unit, integration, end-to-end, performance)
- GitHub Actions CI workflow — runs all tests on every push and pull request
- Apache 2.0 LICENSE file
- Fall 2026 schedule data (`fall_2026.json`, 210 sections)
- Transcript deduplication — repeated course entries no longer inflate completed credit counts

### Fixed
- Semester counting across academic years (fall → spring → summer sequence)
- CIP courses no longer re-scheduled after completion
- JSON data no longer leaked raw in agent chat output
- Transcript parser now correctly excludes failed grades (F, NP, NC, U)

### Breaking
- Follow-up messages require an active session profile from the first message — starting a new session resets all context

### Known Issues
- Scanned / image-only PDFs require OCR preprocessing before upload
- Session memory is in-memory only — cleared on server restart
- Fall 2026 schedule present but limited; some sections inferred from catalog only

---

## [0.6.0] — 2026-04-15

### Added
- Advisor warning when student has unusual course load
- Summer schedule sections (GC and OL tracks)

### Fixed
- Semester counting logic corrected for multi-year plans
- CIP cross-listed courses handled correctly in prerequisite chains
- JSON output no longer leaks raw agent response into chat

---

## [0.5.0] — 2026-03-20

### Added
- Multi-semester graduation planner — builds semester-by-semester roadmap to degree completion
- Parallel ADK pipeline: `transcript_agent` and `catalog_agent` run simultaneously, saving 1–2 seconds
- Follow-up message routing — subsequent messages reuse parsed session profile
- Student profile merging across transcript and chat input
- Accordion UI for semester plan in dashboard
- Auto transcript ingestion on PDF upload

### Added (Data)
- Expanded major coverage from 11 to 29 Lincoln University undergraduate programs
- Fall 2026 schedule ingested and normalized

---

## [0.4.0] — 2026-02-28

### Added
- React + TypeScript frontend with two-panel layout (chat left, dashboard right)
- FastAPI backend with session store and transcript upload handler
- Real Lincoln University catalog data (597 courses, 29 majors)
- Session memory — transcript parsed once per session, reused on follow-ups
- Failed grade exclusion (F, NP, NC, U not counted as completed)

---

## [0.1.0] — 2026-01-20

### Added
- Initial GradPath prototype
- ADK agent pipeline with greeting, transcript, catalog, history, and planner agents
- Basic course recommendation using Lincoln University catalog JSON
- PDF transcript parsing via pdfplumber
