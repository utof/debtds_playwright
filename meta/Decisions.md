# Decisions

This document records key decisions made during the refactor and setup to provide long-term context for future contributors.

## 1) Minimal structure (src/ + data/)
- Keep only `src/` for code and `data/` for inputs/outputs/logs.
- Rationale: Simplicity, faster iteration, fewer moving parts.

## 2) Single orchestrator module (runner.py), no separate entry script
- We decided not to keep a separate entrypoint file.
- Running options:
  - `python src/runner.py` (script mode)
  - `python -m src.runner` (module mode)
  - `python -c "from src.runner import run; run()"` (direct invocation)
- Rationale: Avoid a redundant wrapper file that only imports and calls `run()`.

## 3) Robust imports for direct execution
- `src/runner.py` includes fallback import logic:
  - Tries package-relative imports.
  - On ImportError, adds repo root to `sys.path` and imports via `src.*`.
- Rationale: Make `runner.py` executable in common scenarios without packaging.

## 4) Captcha handling as manual, pause-on-captcha supported
- Introduced `PAUSE_ON_CAPTCHA` (env-controlled). When the DDOS-Guard page is detected:
  - If `PAUSE_ON_CAPTCHA=true` and `HEADLESS=false`, we call `page.pause()` and log instructions to solve the captcha, then Resume in the Inspector to continue the same INN.
  - Otherwise, we mark `captcha_suspected`.
- Rationale: Admins allowed scraping and automated captcha solvers.

## 5) URL assertion and zero-results handling
- Success criteria: company pages should include `/company/ul/` in the URL.
- Zero results detection looks for “найдено 0 организаций” and stores `"0 записей"` to JSON.
- Rationale: Make outcomes explicit and structured.

## 6) Overview extraction strategy
- Target: heading “Общая информация об организации”.
- Extract: first following `div` that has non-empty text.
- Rationale: Avoid brittle assumptions; prefer nearest meaningful content.