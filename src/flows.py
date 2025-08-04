from __future__ import annotations

import re
import logging
from time import sleep
from typing import Literal, TypedDict

from playwright.sync_api import Page, expect, TimeoutError as PlaywrightTimeoutError

from .config import BASE_URL, DEFAULT_TIMEOUT_MS, NAVIGATION_TIMEOUT_MS, MAX_RETRIES, RETRY_BACKOFF_MS, ENABLE_RESULTS_READY_WAIT, RESULTS_READY_SELECTOR, RESULTS_READY_TIMEOUT_MS
from .locators import searchbox, submit_button, first_company_result_link, overview_heading, zero_results_banner
from .utils import ddos_gate_if_needed, await_idle, dump_debug, goto, ensure_visible, results_ready, flow_step, ok, fail


class StepResult(TypedDict):
    status: Literal["ok", "no_results", "timeout", "captcha_suspected", "missing_overview", "error"]
    message: str
    url: str
    overview_text: str | None


@flow_step("open_home")
def open_home(page: Page) -> dict:
    # Centralized navigation: goto + await_idle + optional DDOS gate
    goto(page, BASE_URL, wait_until="networkidle", ddos_search_selector='role=searchbox', apply_ddos_gate=True)
    return ok("home opened", page.url)


@flow_step("submit_search")
def submit_search(page: Page, inn: str) -> StepResult:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info("inn=%s step=fill_search attempt=%d", inn, attempt)
            # Ensure page settled and search is visible before interaction
            await_idle(page)
            sb = searchbox(page)
            ensure_visible(sb, timeout_ms=DEFAULT_TIMEOUT_MS)
            sb.click()
            sb.fill(inn)

            logging.info("inn=%s step=submit attempt=%d", inn, attempt)
            submit = submit_button(page)
            ensure_visible(submit, timeout_ms=DEFAULT_TIMEOUT_MS)
            submit.click()
            # Settle after submit before querying results
            await_idle(page)
            # Optional, targeted results readiness wait (simple, opt-in via config)
            if ENABLE_RESULTS_READY_WAIT:
                if results_ready(page, RESULTS_READY_SELECTOR, timeout_ms=RESULTS_READY_TIMEOUT_MS):
                    logging.info("inn=%s step=results_ready outcome=ok", inn)
                else:
                    logging.info("inn=%s step=results_ready outcome=timeout", inn)

            # Either we land on results or directly on company
            # Quick zero-results detection on the same page (some sites update results dynamically)
            try:
                if zero_results_banner(page).is_visible():
                    logging.info("inn=%s step=zero_results_detected outcome=no_results", inn)
                    return fail("no_results", "zero results banner visible", page.url)
            except PlaywrightTimeoutError:
                pass
            except Exception:
                pass

            # If a result link exists, click and then expect company URL
            await_idle(page)
            link = first_company_result_link(page)
            cnt = link.count()
            logging.info("inn=%s step=result_link_count count=%d", inn, cnt)
            if cnt == 0:
                # Give results a moment if they render dynamically
                page.wait_for_timeout(500)
                cnt = link.count()
                logging.info("inn=%s step=result_link_count_after_wait count=%d", inn, cnt)
                if cnt == 0:
                    # Dump a minimal debug snapshot to understand current state
                    try:
                        dump_debug(page, "no_result_links_after_submit")
                    except Exception:
                        pass
            if cnt > 0:
                link.click()
                logging.info("inn=%s step=company_link_click outcome=clicked", inn)
                await_idle(page)

            # Expect company URL (still succeeds if we were redirected directly)
            expect(page).to_have_url(re.compile(r"/company/ul/"), timeout=NAVIGATION_TIMEOUT_MS)
            logging.info("inn=%s step=url_assertion outcome=ok url=%s", inn, page.url)
            return ok("navigated to company page", page.url)

        except PlaywrightTimeoutError as e:
            # Still honor existing retry loop but keep it smaller
            try:
                dump_debug(page, "timeout_in_submit_search")
            except Exception:
                pass
            if attempt == MAX_RETRIES:
                return fail("timeout", "navigation/search timeout", page.url)
            sleep(RETRY_BACKOFF_MS / 1000.0)
        except Exception as e:
            # Heuristic captcha suspicion: page blocked or unexpected interstitial
            if "captcha" in (str(e).lower()):
                return fail("captcha_suspected", str(e), page.url)
            if attempt == MAX_RETRIES:
                return fail("error", str(e), page.url)
            sleep(RETRY_BACKOFF_MS / 1000.0)

    return {"status": "error", "message": "unreachable state", "url": page.url, "overview_text": None}


@flow_step("extract_overview")
def extract_overview(page: Page, inn: str) -> StepResult:
    try:
        # Ensure heading is visible
        hd = overview_heading(page)
        hd.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)

        # Get first following div's innerText
        h_el = hd.element_handle()
        if not h_el:
            return fail("missing_overview", "heading handle missing", page.url)

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
            return fail("missing_overview", "no following div text", page.url)

        return ok("extracted overview", page.url, overview_text=text)
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