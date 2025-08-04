# Stack

This repo focuses on a simple, reliable scraping pipeline with a minimal tech stack to keep iteration fast.

## Languages and Runtimes
- Python 3.10+ — primary implementation language.

## Core Libraries
- Playwright (Python) — browser automation and DOM interactions.
  - Why: modern, fast, reliable locator strategies, inspector/codegen support.
- Pandas — Excel ingestion (reads column “ИНН”).
  - Why: robust parsing and cleaning for spreadsheet data.
- Standard Library — json, logging, pathlib, contextlib for IO and structure.

## Project Layout
- `src/` — application code
  - `config.py` — central configuration (URLs, timeouts, paths, headless, retry policy).
  - `utils.py` — logging setup, JSON atomic IO, Excel loading.
  - `browser.py` — Playwright session lifecycle (browser/context/page).
  - `locators.py` — centralized selectors and helpers.
  - `flows.py` — high-level user flows (search, zero-results handling, extraction).
  - `runner.py` — orchestrator (iterate INNs, persist results).
- `data/` — inputs/outputs/logs (created at runtime)
  - `input.xlsx` — spreadsheet with “ИНН”
  - `output.json` — result store
  - `logs/` — execution logs

## Operational Settings
- Headless: default True (config overrideable via env HEADLESS=true/false).
- Timeouts: DEFAULT_TIMEOUT_MS and NAVIGATION_TIMEOUT_MS (tunable in config).
- Retries: MAX_RETRIES and RETRY_BACKOFF_MS (tunable in config).

## Developer Experience
- Playwright Inspector/codegen for rapid selector exploration.
- Centralized locators to avoid brittle, distributed selectors.
- Structured logging for debugging long runs.
- Atomic writes for crash-safe progress.

## Install & Run (high level)
- pip install pandas playwright
- playwright install chromium
- Ensure Excel at `data/input.xlsx`
- python my_test_script.py