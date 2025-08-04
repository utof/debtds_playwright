# Decisions

This document records key decisions made during the refactor and setup to provide long-term context for future contributors.

## 1) Split responsibilities into a minimal two-folder structure

- Folders: `src/` (code) and `data/` (inputs/outputs/logs).
- Rationale: Simplify mental model and navigation while enabling separation of concerns and testing. Avoid premature complexity.

## 2) Keep a thin entrypoint and centralize orchestration

- `my_test_script.py` replaced with a thin entrypoint that calls `src.runner.run()`.
- Rationale: Keeps the CLI interaction trivial and pushes business logic into versioned modules with clear boundaries.

## 3) Centralize configuration and selectors

- `src/config.py` holds BASE_URL, timeouts, headless default, paths, retries.
- `src/locators.py` holds all selectors (searchbox, submit button, result link by `/company/ul/`, overview heading, zero-results banner).
- Rationale: Reduce selector drift and avoid magic numbers/strings sprinkled across the code.

## 4) Logging-first approach with resumability and atomic writes

- Structured logging for each step (with INN and outcome) to `data/logs/`.
- JSON writes are atomic and performed after each INN to allow safe resumption.
- Rationale: Observability + reliability for long-running scraping tasks.

## 5) Explicit flow stages with URL assertions and zero-results handling

- Flows assert navigation to `/company/ul/` when opening a company page.
- Zero-results detection via substring “найдено 0 организаций”.
- Rationale: Make success criteria precise and handle empty states explicitly.

## 6) Prepare for captcha scenarios without implementing an opinionated solution

- Strategy documented rather than implemented to avoid policy/ethics risk and to keep the code compliant and flexible.
- Rationale: Captcha handling is situational and may require policy/legal review.