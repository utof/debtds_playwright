import json
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
import logging
import sys
from datetime import datetime

from playwright.sync_api import Page

from .config import DATA_DIR, LOGS_DIR, ENABLE_DDOS_GUARD_HANDLING, DDOS_INITIAL_SLEEP_MS, DDOS_CONTINUE_TIMEOUT_MS, DEFAULT_TIMEOUT_MS

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

# ---------- Page readiness (universal, minimal) ----------

def await_idle(page: Page) -> None:
    """
    Universal load-settle helper to reduce racing/partial DOM:
      - domcontentloaded (HTML parsed)
      - networkidle (no in-flight requests)
      - tiny grace pause to allow microtasks/late JS (200ms)
    Safe to call multiple times. No assumptions about current URL.
    """
    try:
        page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle")
    except Exception:
        pass
    try:
        page.wait_for_timeout(200)
    except Exception:
        pass

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


# ---------- Debug snapshots ----------

def dump_debug(page: Page, label: str) -> None:
    """
    Save URL, HTML, and a screenshot for quick post-mortem.
    Files go under data/logs/debug/{timestamp}_{label}.*
    """
    try:
        base = LOGS_DIR / "debug"
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"{ts}_{label}"
        (base / f"{stem}_url.txt").write_text(page.url, encoding="utf-8")
        # Limit inner HTML fetch time to avoid blocking too long
        try:
            html = page.content()
        except Exception:
            html = "<failed to get content>"
        (base / f"{stem}.html").write_text(html, encoding="utf-8")
        try:
            page.screenshot(path=str(base / f"{stem}.png"), full_page=True)
        except Exception:
            pass
        logging.info("step=dump_debug_saved label=%s path=%s", label, base)
    except Exception as e:
        logging.warning("step=dump_debug_failed label=%s msg=%s", label, str(e))


# ---------- Stability primitives ----------
def ensure_visible(locator, *, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
    """
    Uniform wrapper ensuring a locator is visible before interaction.
    Keeps all visibility waits consistent and tunable from one place.
    """
    locator.wait_for(state="visible", timeout=timeout_ms)


def results_ready(page: Page, selector: str, *, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> bool:
    """
    Wait until results area is present/visible. Returns True if visible, False on timeout.
    """
    try:
        page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
        return True
    except Exception:
        return False


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
    # Ensure page is idle before selector waits to reduce false negatives
    await_idle(page)
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


# ---------- Navigation wrapper (central policy) ----------

def goto(page: Page, url: str, *, wait_until: str = "networkidle", ddos_search_selector: str | None = None, apply_ddos_gate: bool = True) -> None:
    """
    Centralized navigation:
      - page.goto(url, wait_until=...)
      - await_idle()
      - optional DDOS gate using provided search selector
    """
    page.goto(url, wait_until=wait_until)
    await_idle(page)
    if apply_ddos_gate and ddos_search_selector:
        ddos_gate_if_needed(page, ddos_search_selector)


# ---------- Retry harness (per-step/per-INN) ----------

class RetryOutcome:
    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"


def run_with_retries(fn, *, max_retries: int, backoff_ms: int, on_error=None):
    """
    Generic retry harness. Calls fn() up to max_retries.
    - If fn() returns a dict with status != "ok", it's treated as error and retried.
    - Exceptions/timeouts are also retried.
    - on_error(attempt, exc_or_result) can be provided for logging/snapshots.
    Returns the final fn() result on success or the last error dict.
    """
    last_err: Dict[str, Any] | None = None
    for attempt in range(1, max_retries + 1):
        try:
            res = fn()
            if isinstance(res, dict) and res.get("status") == "ok":
                return res
            last_err = res if isinstance(res, dict) else {"status": RetryOutcome.ERROR, "message": "unknown result"}
            if on_error:
                try:
                    on_error(attempt, last_err)
                except Exception:
                    pass
        except Exception as e:
            last_err = {"status": RetryOutcome.ERROR, "message": str(e)}
            if on_error:
                try:
                    on_error(attempt, e)
                except Exception:
                    pass
        if attempt < max_retries:
            try:
                page = None
                # If the fn is a closure with page bound, caller can handle snapshots in on_error.
                # We only sleep/backoff here.
                import time
                time.sleep(backoff_ms / 1000.0)
            except Exception:
                pass
    return last_err or {"status": RetryOutcome.ERROR, "message": "unknown"}


# ---------- Flow niceties: result builders and decorator ----------

def ok(message: str, url: str, overview_text: str | None = None) -> Dict[str, Any]:
    return {"status": "ok", "message": message, "url": url, "overview_text": overview_text}


def fail(status: str, message: str, url: str, overview_text: str | None = None) -> Dict[str, Any]:
    return {"status": status, "message": message, "url": url, "overview_text": overview_text}


def flow_step(name: str):
    """
    Decorator to standardize logging and error handling for flow steps.
    - Logs start/ok/error with a consistent format
    - Catches exceptions and converts them to a StepResult-like dict via fail()
    - Optionally dumps debug snapshots for quick post-mortem
    Keep step functions themselves lean; no try/except/log soup inside flows.
    """
    def _wrap(fn):
        def _inner(*args, **kwargs):
            try:
                logging.info("step=%s outcome=starting", name)
                res = fn(*args, **kwargs)
                # If a dict StepResult is returned, propagate; else log ok
                if isinstance(res, dict):
                    logging.info("step=%s outcome=%s", name, res.get("status", "ok"))
                    return res
                logging.info("step=%s outcome=ok", name)
                return res
            except Exception as e:
                # Try to access page from args for debug, if present
                page = None
                for a in args:
                    if hasattr(a, "wait_for_selector") and hasattr(a, "url"):
                        page = a
                        break
                try:
                    if page:
                        dump_debug(page, f"flow_error_%s" % name)
                except Exception:
                    pass
                msg = str(e)
                status = "captcha_suspected" if "captcha" in msg.lower() else "error"
                current_url = page.url if page else ""
                logging.warning("step=%s outcome=%s msg=%s", name, status, msg)
                return fail(status, msg, current_url)
        return _inner
    return _wrap