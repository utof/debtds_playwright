from pathlib import Path
import os

# Base configuration
BASE_URL = "https://zachestnyibiznes.ru/"

# Timeouts (milliseconds for Playwright waits/assertions)
DEFAULT_TIMEOUT_MS = 30_000
NAVIGATION_TIMEOUT_MS = 30_000

# Headless by default for performance; set to False for debugging
# HEADLESS = True if os.getenv("HEADLESS", "true").lower() == "true" else False
HEADLESS = False

# Data paths
DATA_DIR = Path("data")
LOGS_DIR = DATA_DIR / "logs"
EXCEL_INPUT = DATA_DIR / "input.xlsx"  # point/rename your filtered file here
JSON_OUTPUT = DATA_DIR / "output.json"

# Retries
MAX_RETRIES = 2
RETRY_BACKOFF_MS = 1000

# Results readiness (opt-in, minimal and safe)
ENABLE_RESULTS_READY_WAIT = True
# A conservative selector that likely exists when results render (container or any result link)
RESULTS_READY_SELECTOR = 'a[href*="/company/ul/"], a[href*="/company/ip/"]'
RESULTS_READY_TIMEOUT_MS = DEFAULT_TIMEOUT_MS

# Anti-DDOS handling (MVP)
ENABLE_DDOS_GUARD_HANDLING = True  # keep simple toggle
DDOS_INITIAL_SLEEP_MS = 1000       # let interstitial render
DDOS_CONTINUE_TIMEOUT_MS = 180_000 # wait up to 3 minutes for human solve