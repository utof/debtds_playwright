# Architecture

Updated to reflect runner-as-script execution and captcha pause mode.

## Overview

Folders:
- `src/` — application code
  - `config.py` — BASE_URL, timeouts, `HEADLESS`, `PAUSE_ON_CAPTCHA`, paths, retry policy
  - `utils.py` — logging setup, Excel loading (ИНН), atomic JSON IO
  - `browser.py` — Playwright session lifecycle (context-managed)
  - `locators.py` — centralized selectors for robust targeting
  - `flows.py` — high-level user flows (open home, submit search, detect zero results/captcha, extract overview)
  - `runner.py` — orchestrates batch processing; now executable directly and module-friendly
- `data/` — runtime data: `input.xlsx`, `output.json`, `logs/`

Entry/Run:
- No separate entrypoint.
- Run with:
  - `python src/runner.py` (script mode)
  - `python -m src.runner` (module mode)
  - or REPL: `from src.runner import run; run()`

## Execution flow

1. `runner.run()` initializes logging.
2. Load INNs from `data/input.xlsx` (column “ИНН”).
3. Load prior results from `data/output.json` (resume-friendly).
4. Start one Playwright session (browser/context/page) for the whole batch.
5. For each INN:
   - `flows.open_home` navigates and detects DDOS-Guard.
     - If `PAUSE_ON_CAPTCHA=true` and `HEADLESS=false`: `page.pause()` until you solve the captcha; resume continues the same INN.
     - Else: mark `captcha_suspected`.
   - `flows.submit_search` fills INN, submits, attempts to click `a[href*="/company/ul/"]`, asserts URL contains `/company/ul/`.
     - Zero results: detect “найдено 0 организаций”.
   - `flows.extract_overview` finds the heading “Общая информация об организации” and returns the first following `div` with non-empty text.
6. Save JSON after each INN (atomic write).

## Observability & reliability

- Logs to console and `data/logs/run_*.log` with structured step messages.
- Atomic JSON writes; can resume runs.
- Timeouts and retries centralized in config.
- CAPTCHA handling path is clear and manual-first.
## Extensibility Points

- `locators.py`: adjust selectors without touching flow logic.
- `flows.py`: add new extraction routines or support alternative site sections.
- `config.py`: tune performance and behavior (timeouts, retries, headless).
- `runner.py`: add CLI params (limit, resume modes, dry run).
## Known behaviors

- Company pages asserted by `/company/ul/` in URL.
- Zero results persist `"0 записей"` for that INN.
- Overview extraction seeks the first non-empty following div after the target heading.

## Import strategy

`src/runner.py` supports:
- Package imports when launched via `python -m src.runner`.
- Fallback sys.path adjustment when launched as `python src/runner.py` (adds repo root so `import src.*` works).
