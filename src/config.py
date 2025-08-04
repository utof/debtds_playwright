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