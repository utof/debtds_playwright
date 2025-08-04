import json
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
import logging
import sys
from datetime import datetime

from playwright.sync_api import Page

from .config import DATA_DIR, LOGS_DIR, ENABLE_DDOS_GUARD_HANDLING, DDOS_INITIAL_SLEEP_MS, DDOS_CONTINUE_TIMEOUT_MS

# ---------- Logging ----------

def setup_logging(run_name: str | None = None) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if not run_name:
        run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"run_{run_name}.log"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("ts=%(asctime)s level=%(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)


# ---------- JSON IO ----------

def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        # backup corrupt file
        backup = path.with_suffix(path.suffix + ".bak")
        try:
            path.replace(backup)
        except Exception:
            pass
        return {}


def save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ---------- Excel ----------

def read_inns_from_excel(xlsx_path: Path, column: str = "ИНН") -> List[str]:
    df = pd.read_excel(xlsx_path)
    if column not in df.columns:
        raise KeyError(f'The Excel file must contain a column named "{column}"')
    inns = (
        df[column]
        .dropna()
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
        .tolist()
    )
    return [i for i in inns if i]


# ---------- Anti-DDOS helpers (MVP) ----------

def detect_ddos_guard(page: Page) -> bool:
    """
    Very cheap heuristics to detect DDOS-Guard interstitial.
    No iframe spelunking; rely on obvious markers.
    """
    try:
        title = page.title().strip().lower()
    except Exception:
        title = ""
    if "ddos-guard" in title:
        return True

    try:
        # Fast existence checks; do not wait
        if page.locator("#ddg-captcha, #ddg-iframe, h1#title").count() > 0:
            # Further refine: check visible heading text when present
            try:
                txt = page.locator("h1#title").first.inner_text(timeout=500)
                if "checking your browser before accessing" in txt.strip().lower():
                    return True
            except Exception:
                # Presence of ddg-specific nodes is enough
                return True
    except Exception:
        pass

    return False


def wait_until_search_ready(page: Page, search_selector: str, timeout_ms: int) -> None:
    """
    Wait until the real page is ready by waiting for the search element.
    """
    page.wait_for_selector(search_selector, timeout=timeout_ms, state="visible")


def ddos_gate_if_needed(page: Page, search_selector: str) -> None:
    """
    MVP flow:
      - sleep a bit (allow interstitial to render)
      - if ddos detected: instruct user, then wait for search to appear
    """
    if not ENABLE_DDOS_GUARD_HANDLING:
        return

    # Initial short sleep
    try:
        page.wait_for_timeout(DDOS_INITIAL_SLEEP_MS)
    except Exception:
        pass

    if detect_ddos_guard(page):
        logging.info("step=ddos_guard_detected msg='Solve captcha in the opened browser window.' timeout_ms=%d", DDOS_CONTINUE_TIMEOUT_MS)
        logging.info("step=ddos_guard_waiting url=%s", page.url)
        # Block here while human solves captcha and redirect happens
        wait_until_search_ready(page, search_selector, DDOS_CONTINUE_TIMEOUT_MS)
        logging.info("step=ddos_guard_passed msg='Search control is visible; continuing.' url=%s", page.url)