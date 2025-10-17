# Contributing to the Company Data Scraping Project

This project is a Python-based web scraping and data extraction tool focused on Russian business registries and bankruptcy data. It uses Playwright for browser automation and FastAPI for serving extracted data via an API. The codebase is modular, with separate modules for different data sources.

## Project Overview

The project scrapes and analyzes company data from Russian sources like list-org.com, tbankrot.ru, zachestnyibiznes.ru, and others. Key features:
- **Company Card Data**: Registration details, founders, and main activities.
- **Financial Data**: Balance sheets, profit/loss statements, and financial ratios.
- **Bankruptcy Checks**: Lot parsing, debtor enrichment, and status filtering.
- **RDL Checks**: Disqualification status for CEOs and founders.
- **Extended Extraction**: CEOs, beneficiaries, employees, and court debts from ZChB.
- **API Endpoints**: FastAPI server for querying data by INN (Tax ID).

Core technologies:
- Python 3.10+ (managed via `pyproject.toml` and `uv`).
- Playwright for headless browser automation.
- Loguru for logging.

Data is cached in JSON files under `cache/` and output to `data/output/`. Screenshots and logs are in `data/screenshots/` and `data/logs/`.

## Project Structure

```
.
├── main.py                  # FastAPI server entrypoint
├── src/
│   ├── browser.py           # Playwright browser wrapper with proxy/captcha handling
│   ├── nalog_ru.py          # Disqualification checks on nalog.ru
│   ├── utils.py             # Shared utilities (INN processing, financial calculations)
│   ├── apicloud.py          # Bankruptcy status via API
│   ├── pdf_extractor.py     # PDF text extraction
│   ├── proxy_manager.py     # Proxy rotation (if needed)
│   ├── listorg/             # Company data from list-org.com
│   │   ├── main.py          # Core scraping logic (card, finances, RDL)
│   │   └── flows.py         # Page navigation and data extraction functions
│   ├── tbankrot/            # Bankruptcy lots from tbankrot.ru
│   │   ├── main.py          # Lot link collection and parsing orchestration
│   │   ├── parse_lots_links.py  # Catalog scraping
│   │   ├── parse_lot_data.py    # Individual lot details
│   │   ├── ai_request.py        # AI-based debtor enrichment
│   │   ├── filter_*.py          # Status filtering (Oksana/Sergey variants)
│   │   └── config.py            # TBankrot-specific settings
│   └── ZChB/                # Extended data from zachestnyibiznes.ru
│       ├── main.py          # CEO/beneficiary extraction
│       ├── flows.py         # Modal interactions and data pulls
│       ├── login.py         # Site authentication
│       └── handle_captcha.py # Captcha solving
├── debt_verifier/           # Bankruptcy risk analysis (structural/financial stages)
├── data/                    # Outputs, logs, screenshots
├── cache/                   # Parsed lot cache
├── debug/                   # Debug JSONs (e.g., all_lots.json)
└── static/                  # API favicon
```

## Setup for Development

Follow the detailed setup instructions in [README.md](README.md) for environment configuration, dependency installation, and running the server.

### Additional Development Notes

- **Environment Variables**: See `.env.example` for required API keys and credentials. Copy to `.env` and fill with provided values.
- **Browser Data**: The `datadir/` directory stores persistent browser state. Delete it to reset if you encounter issues.
- **Logging**: All operations log to `data/logs/` and `data/error_logs/`. Check these for debugging.
- **Testing INNs**: Use test INN `6312126585` for development and verification.

## Key Workflows

- **API Flow**: Requests hit `main.py` endpoints, which delegate to module-specific scrapers using a shared browser instance.
- **Scraping Flow**: Browser navigates sites, handles captchas/modals, extracts data, applies filters/AI enrichment, and caches results.
- **Data Flow**: Raw HTML → Parsed JSON → Enriched/Analyzed → API response or file output.
- **Error Handling**: Logs to `data/logs/` and `data/error_logs/`. Screenshots on failures.

## Contribution Guidelines

1. **Getting Started**:
   - Fork the repo and create a feature branch: `git checkout -b feature/new-scraper`.
   - Ensure your changes are atomic (one feature/fix per PR).
   - Install development dependencies: `uv sync --dev`.

2. **Code Style**:
   - Follow PEP 8 (use `uv run ruff format .` for formatting).
   - Add docstrings to functions (Google style).
   - Use type hints (e.g., `async def func(page: Page) -> dict`).
   - Log meaningfully with Loguru: `logger.info("Message")`.
   - Lint with Ruff: `uv run ruff check .` and `uv run ruff format .`.

3. **Best Practices**:
   - **Browser Automation**: Always use the `Browser` wrapper for context management. Handle captchas via `handle_captcha()`.
   - **Data Extraction**: Use robust selectors (e.g., `page.locator("text=Exact")`). Add retries for flaky sites.
   - **Caching**: Update `cache/lots_cache.json` atomically in tbankrot flows.
   - **Filtering**: Extend filters in `tbankrot/filter_*.py` for new status rules.
   - **AI Integration**: Modify `tbankrot/ai_request.py` for new enrichment prompts.
   - **Analysis**: Add stages in `debt_verifier/` for new risk checks.
   - **Environment**: Never commit `.env` files. Use `.env.example` as template.

4. **Testing Changes**:
   - Run scrapers with a test INN (e.g., `6312126585`).
   - Verify API: `curl http://localhost:8000/company_card/6312126585`.
   - Check logs for errors. Add tests if extending functionality.
   - Run linter: `uv run ruff check .`
   - Run tests: `uv run pytest`

5. **Submitting PRs**:
   - Update docs (README.md or CONTRIBUTING.md).
   - Reference issues: "Fixes #123".
   - Ensure no lint errors: `uv run ruff check . --fix`.
   - Test on both Linux/macOS and Windows if making browser-related changes.

6. **Common Tasks for New Contributors**:
   - Add a new filter rule in `tbankrot/filter_sergey.py`.
   - Improve captcha handling in `ZChB/handle_captcha.py`.
   - Extend financial analysis in `debt_verifier/stage_structural__finances_analysis.py`.
   - Add new API endpoint in `main.py` with proper error handling.
   - Fix a specific scraper issue (check logs in `data/error_logs/`).

7. **Platform-Specific Notes**:
   - **Windows**: Avoid `--reload` with uvicorn due to Playwright compatibility issues. Use `--workers 1` instead.
   - **Linux/macOS**: Use tmux for background server sessions: `tmux new -s zchb`.
   - **Cross-Platform**: Ensure selectors work across browser versions. Test with `headless=False` for debugging.

## Common Issues and Troubleshooting

- **Captcha Solving Fails**: Check `APIKEY_2CAPTCHA` credits and network connectivity.
- **Authentication Errors**: Verify TBankrot and ZChB credentials in `.env`. Regenerate tokens if expired.
- **Browser Crashes**: Delete `datadir/` and restart the server.
- **Port Already in Use**: Change the port in uvicorn command (e.g., `--port 8001`).
- **Missing Dependencies**: Run `uv sync` again or check `pyproject.toml`.
- **Playwright Errors**: Ensure `uv run playwright install chromium` was successful.
- **AI Requests Fail**: Verify `OPENROUTER_APIKEY` and check rate limits.

Questions? Open an issue or ask in PR comments. Thanks for contributing!
