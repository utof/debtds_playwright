from __future__ import annotations

import re
import logging
from time import sleep
from typing import Literal, TypedDict

from playwright.sync_api import Page, expect, TimeoutError as PlaywrightTimeoutError

from .config import BASE_URL, DEFAULT_TIMEOUT_MS, NAVIGATION_TIMEOUT_MS, MAX_RETRIES, RETRY_BACKOFF_MS
from .locators import searchbox, submit_button, first_company_result_link, overview_heading, zero_results_banner


class StepResult(TypedDict):
    status: Literal["ok", "no_results", "timeout", "captcha_suspected", "missing_overview", "error"]
    message: str
    url: str
    overview_text: str | None


def open_home(page: Page) -> None:
    logging.info("inn=? step=open_home outcome=starting url=%s", BASE_URL)
    page.goto(BASE_URL, timeout=NAVIGATION_TIMEOUT_MS)
    logging.info("inn=? step=open_home outcome=ok current_url=%s", page.url)


def submit_search(page: Page, inn: str) -> StepResult:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info("inn=%s step=fill_search attempt=%d", inn, attempt)
            sb = searchbox(page)
            sb.click()
            sb.fill(inn)

            logging.info("inn=%s step=submit attempt=%d", inn, attempt)
            submit = submit_button(page)
            submit.click()

            # Either we land on results or directly on company
            # Quick zero-results detection on the same page (some sites update results dynamically)
            try:
                if zero_results_banner(page).is_visible():
                    logging.info("inn=%s step=zero_results_detected outcome=no_results", inn)
                    return {"status": "no_results", "message": "zero results banner visible", "url": page.url, "overview_text": None}
            except PlaywrightTimeoutError:
                pass
            except Exception:
                pass

            # If a result link exists, click and then expect company URL
            link = first_company_result_link(page)
            if link.count() > 0:
                link.click()
                logging.info("inn=%s step=company_link_click outcome=clicked", inn)

            # Expect company URL
            expect(page).to_have_url(re.compile(r"/company/ul/"), timeout=NAVIGATION_TIMEOUT_MS)
            logging.info("inn=%s step=url_assertion outcome=ok url=%s", inn, page.url)
            return {"status": "ok", "message": "navigated to company page", "url": page.url, "overview_text": None}

        except PlaywrightTimeoutError as e:
            logging.warning("inn=%s step=submit_search outcome=timeout attempt=%d msg=%s", inn, attempt, str(e))
            if attempt == MAX_RETRIES:
                return {"status": "timeout", "message": "navigation/search timeout", "url": page.url, "overview_text": None}
            sleep(RETRY_BACKOFF_MS / 1000.0)
        except Exception as e:
            # Heuristic captcha suspicion: page blocked or unexpected interstitial
            logging.warning("inn=%s step=submit_search outcome=error attempt=%d msg=%s", inn, attempt, str(e))
            if "captcha" in (str(e).lower()):
                return {"status": "captcha_suspected", "message": str(e), "url": page.url, "overview_text": None}
            if attempt == MAX_RETRIES:
                return {"status": "error", "message": str(e), "url": page.url, "overview_text": None}
            sleep(RETRY_BACKOFF_MS / 1000.0)

    return {"status": "error", "message": "unreachable state", "url": page.url, "overview_text": None}


def extract_overview(page: Page, inn: str) -> StepResult:
    try:
        logging.info("inn=%s step=extract_overview outcome=starting", inn)
        # Ensure heading is visible
        hd = overview_heading(page)
        hd.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)

        # Get first following div's innerText
        h_el = hd.element_handle()
        if not h_el:
            logging.warning("inn=%s step=extract_overview outcome=missing_heading", inn)
            return {"status": "missing_overview", "message": "heading handle missing", "url": page.url, "overview_text": None}

        text = page.evaluate(
            """(h) => {
                let n = h.nextElementSibling;
                while (n) {
                  if (n.tagName && n.tagName.toLowerCase() === 'div') {
                    return n.innerText || '';
                  }
                  n = n.nextElementSibling;
                }
                return '';
            }""",
            h_el,
        ) or ""

        text = text.strip()
        if not text:
            logging.warning("inn=%s step=extract_overview outcome=missing_overview url=%s", inn, page.url)
            return {"status": "missing_overview", "message": "no following div text", "url": page.url, "overview_text": None}

        logging.info("inn=%s step=extract_overview outcome=ok chars=%d", inn, len(text))
        return {"status": "ok", "message": "extracted overview", "url": page.url, "overview_text": text}

    except PlaywrightTimeoutError as e:
        logging.warning("inn=%s step=extract_overview outcome=timeout msg=%s", inn, str(e))
        return {"status": "timeout", "message": "overview timeout", "url": page.url, "overview_text": None}
    except Exception as e:
        msg = str(e)
        outcome: Literal["error", "captcha_suspected"] = "captcha_suspected" if "captcha" in msg.lower() else "error"
        logging.warning("inn=%s step=extract_overview outcome=%s msg=%s", inn, outcome, msg)
        return {"status": outcome, "message": msg, "url": page.url, "overview_text": None}


def search_and_extract(page: Page, inn: str) -> StepResult:
    """
    High-level flow for one INN:
      - ensure on home
      - submit search
      - if ok, extract overview
      - else, return the status as-is
    """
    open_home(page)
    submit_res = submit_search(page, inn)
    if submit_res.get("status") != "ok":
        return submit_res
    return extract_overview(page, inn)