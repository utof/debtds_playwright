# Open Questions, TODOs, and Partial Implementations

This document preserves historical context and evolving decisions. New entries are appended with timestamps; prior content is retained for archaeology.

## History Log

- 2025-08-04 — Initial modularization
  - Separated into `src/` and `data/`.
  - Centralized configuration (`config.py`) and selectors (`locators.py`).
  - Introduced URL assertions for company pages (`/company/ul/`).
  - Added zero-results heuristic detection (“найдено 0 организаций”).
  - Implemented atomic JSON writes and resumability.
  - Rationale: robustness, observability, maintainability.

- 2025-08-04 — Captcha stance clarified
  - Site presents DDOS-Guard interstitial (e.g., `#ddg-iframe`, `#ddg-captcha`).
  - Policy: manual solving preferred; no automated solver integration unless explicitly approved.
  - Detection points added with clear logging.
  - Rationale: compliance, simplicity, reduce maintenance risk.

- 2025-08-04 — Pause-on-captcha mode added
  - Environment flags: `PAUSE_ON_CAPTCHA=true` with `HEADLESS=false` triggers `page.pause()` and logs instructions.
  - After solving, pressing Resume in Playwright Inspector continues the same INN flow.
  - Rationale: human-in-the-loop without derailing batch runs.

- 2025-08-04 — Runner execution clarified
  - Removed separate entry file; prefer direct execution of `src/runner.py` and module mode `python -m src.runner`.
  - Added import fallback logic in `runner.py` to support both invocation styles.
  - Rationale: avoid redundant wrappers; compatibility across run modes.

## Open Questions (Active)

1) Selector precision (needs page data)
- Please provide minimal HTML snippets or codegen traces for:
  - Search input
  - Submit button
  - One result link `/company/ul/...`
  - Element displaying “найдено 0 организаций”
  - Heading “Общая информация об организации” + the first following div with non-empty text

2) Output schema
- Current behavior:
  - Saves overview text if present
  - Saves "0 записей" if zero results detected
  - Saves a status string otherwise (e.g., `status:... msg:...`)
- Consider switching to a structured object per INN: `{ inn, status, overview, url, ts }`.
- Decision pending consumer needs.

3) Rate limits and policy (admins approved scraping)
- Confirm acceptable pacing and any constraints (concurrency, proxies) to reduce captcha frequency.

## TODOs (Next)

- Add CLI flags to `runner.run`:
  - Paths (excel/json), headless, pause-on-captcha, limit count.
- Finalize zero-results detection with a precise DOM selector once snippets are provided (beyond substring).
- Add end-of-run summary metrics:
  - Count ok / no_results / captcha_suspected / error.
- Optional: JSONL audit log for per-INN outcomes with timestamps.
- Optional: Tests
  - Utils: Excel parsing and JSON IO.
  - Smoke test for flows with a known static page.

## Partial Implementations

- Captcha handling:
  - Manual pause mode implemented via `PAUSE_ON_CAPTCHA` + `page.pause()`; no automatic solver (policy-dependent).
- Zero-results:
  - Heuristic via substring “найдено 0 организаций”; to be hardened after DOM confirmation.
- Imports:
  - `runner.py` supports both script (`python src/runner.py`) and module (`python -m src.runner`) invocations via path fallback.

## Rejected / Debated Items

- Extra entrypoint file that only imports/calls `run()`: rejected as redundant; `runner.py` is the single operational script for both script and module runs.
- Text-based selectors by visible name: avoided; prefer role/attribute/href selectors for stability.
- Automated captcha solver integration: deferred; revisit only with explicit approval and terms review.
- Complex folder hierarchy: avoided; kept to `src/` + `data/` for clarity and speed.