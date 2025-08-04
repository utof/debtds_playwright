# Architecture

High-level documentation of the current scraping pipeline to help future maintainers quickly understand structure and intent.

## Overview

Minimal two-folder structure:

- `src/` — application code
  - `config.py` — constants and runtime toggles (URLs, timeouts, headless, paths, retries)
  - `utils.py` — logging setup, Excel reading (ИНН), JSON atomic read/write
  - `browser.py` — Playwright lifecycle (browser/context/page) with safe cleanup
  - `locators.py` — centralized locator helpers (stable selectors and fallbacks)
  - `flows.py` — user journey logic (search by ИНН, detect zero results, assert URL, extract overview)
  - `runner.py` — orchestration (iterate INNs, call flows, persist JSON incrementally, resumable)
- `data/` — runtime data
  - `input.xlsx` — spreadsheet containing column “ИНН”
  - `output.json` — results: { INN: overview_text or status string }
  - `logs/` — execution logs per run

Entry point:
- `my_test_script.py` — thin wrapper that calls `src.runner.run()`.

## Data Flow

1. Runner loads INNs from `data/input.xlsx` via `utils.read_inns_from_excel`.
2. Runner loads existing results JSON via `utils.load_json`.
3. Runner starts a `browser.playwright_session` (single browser/page reused).
4. For each INN:
   - `flows.search_and_extract`:
     - Open home page.
     - Submit search with robust selectors (no reliance on visible text).
     - If a result exists: click the first `a[href*="/company/ul/"]`, assert URL contains `/company/ul/`.
     - Extract overview text: first div following the heading “Общая информация об организации”.
     - Detect zero-results via substring “найдено 0 организаций”.
   - Runner writes result after each INN using atomic write.
5. Logs written to `data/logs/` with contextual fields (INN, step, outcome).

## Reliability & Observability

- Centralized configuration of timeouts and retry policy.
- Structured logging at each step with status and URL.
- Atomic writes for results to prevent corruption on interruption.
- Resumable processing: skips INNs already present with a non-empty value.

## Extensibility Points

- `locators.py`: adjust selectors without touching flow logic.
- `flows.py`: add new extraction routines or support alternative site sections.
- `config.py`: tune performance and behavior (timeouts, retries, headless).
- `runner.py`: add CLI params (limit, resume modes, dry run).

## Known Behaviors

- URL assertion: expects company pages to match `/company/ul/`.
- Zero-results detection: substring “найдено 0 организаций”.
- Overview extraction: the first `div` immediately after the target heading.
