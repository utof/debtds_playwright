# Open Questions, TODOs, and Partial Implementations

Concise list of what remains uncertain or unfinished, plus clear next actions.

## Open Questions
1) Selectors precision (needs page data)
- We used reasonable defaults (roles, href patterns, substring) but the final robust selectors should be confirmed with real DOM.
- Ask: Provide HTML snippets or codegen traces for:
  - Search input
  - Submit button
  - A results link pointing to /company/ul/...
  - The “найдено 0 организаций” element
  - The heading “Общая информация об организации” and the first following div

2) Zero-results variants
- Text used: “найдено 0 организаций”. Are there other variants (pluralization, capitalization, whitespace, different containers)?
- Ask: Confirm if other phrasings appear on the site so we can broaden detection.

3) Data shape expectations
- Currently we store either the overview text or a status string (“status:… msg:…”).
- Ask: Should results be structured JSON objects, e.g. { "inn": "...", "status": "...", "overview": "...", "url": "..." }?

4) Legal/policy constraints
- Scraping and captcha handling depend on site terms and jurisdiction.
- Ask: Confirm acceptable rate limits, whether proxies are allowed, and if automated captcha solving is permissible.

5) Performance constraints
- Single browser/page reused.
- Ask: Is parallelization required later (multiple contexts/pages)? If yes, confirm limits and data correctness strategy (ordering and rate).

## TODOs
- Finalize selectors after receiving real HTML snippets.
- Implement explicit zero-results detection with robust locators (beyond substring) once DOM is confirmed.
- Add CLI parameters to runner (e.g., --headless, --limit, --resume-from, --excel-path, --json-path).
- Add simple metrics: processed count, durations, success/timeout/error tallies (end-of-run summary).
- Optional: Add JSONL result log for auditing per-INN outcomes.
- Optional: Add retry/backoff tuning per step (submit, link click, extraction).
- Optional: Add unit tests for utils (Excel parsing and JSON IO), smoke tests for flows.

## Partial Implementations
- Captcha handling: documented strategy only; no automated solver integration.
- Zero-results handling: substring-based heuristic is present; final selector to be confirmed with DOM.
- URL assertion: implemented to expect `/company/ul/` on company pages; will adjust if site uses different patterns.

## Rejected / Debated Items
- Complex folder hierarchy: avoided; kept to `src/` + `data/` for clarity and speed.
- Text-based click by visible name: rejected; we prefer role/attribute/href selectors for stability.
- Immediate captcha solver integration: deferred until legal/policy confirmation.
- Over-engineered config/CLI before DOM confirmation: postponed to keep iteration tight.
