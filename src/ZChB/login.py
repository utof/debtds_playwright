import os
import time
from pathlib import Path
from datetime import datetime

from patchright.sync_api import Page, TimeoutError
from loguru import logger
from dotenv import load_dotenv
from .handle_captcha import CaptchaHandler

# Ensure UTF-8 encoding (handles BOMs if present)
# dotenv_path = Path(__file__).parent / ".env"
# load_dotenv(dotenv_path=dotenv_path, encoding="utf-8", override=True)
load_dotenv(encoding="utf-8", override=True)

def require_env(key: str) -> str:
    """
    Fetch an env var, log its raw repr() (to see \n, \r, spaces),
    raise if missing or empty after stripping.
    """
    raw_value = os.getenv(key, "")
    logger.info(f"ENV RAW (len={len(raw_value)})")

    if raw_value is None or raw_value == "":
        raise RuntimeError(f"Missing required env var: {key}")

    value = raw_value.strip()
    if len(value) == 0:
        raise RuntimeError(f"Env var {key} is empty after stripping")

    return value


LOGIN = require_env("ZCHB_LOGIN")
PWD = require_env("ZCHB_PWD")

logger.info(f"Using LOGIN={repr(LOGIN)}, PWD length={len(PWD)}")
captcha_handler = CaptchaHandler()


# ---------- Debug helper ----------

def quick_dump(page: Page, label: str):
    """Write compact debug info to a text file for easy SSH cat."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = Path(f".zchb_debug_{label}_{ts}.txt")
    try:
        body_text = page.evaluate("document.body.innerText")[:2000]
    except Exception as e:
        body_text = f"<could not extract body text: {e}>"

    markers = {
        "url": page.url,
        "guest_text": page.get_by_text("Вход / Регистрация", exact=False).count(),
        "premium_modal": page.locator("#premiumloginmodal").count(),
        "logout_link": page.locator("a[href*='logout']").count(),
        "profile_link": page.locator("a[href*='/user'], a[href*='/profile']").count(),
    }

    text = [
        f"== quick_dump: {label} ==",
        f"URL: {markers['url']}",
        f"guest_text: {markers['guest_text']}",
        f"premium_modal: {markers['premium_modal']}",
        f"logout_link: {markers['logout_link']}",
        f"profile_link: {markers['profile_link']}",
        "",
        body_text,
    ]

    path.write_text("\n".join(text), encoding="utf-8")
    logger.info(f"[quick_dump] Wrote {path}")


# ---------- Main login ----------

def login(page: Page) -> bool:
    """
    Simplified login flow:
    - Navigate to site
    - Solve captcha if needed
    - If /login redirects to /user → already logged in
    - Otherwise, submit login form
    - Success if premium modal (#premiumloginmodal) appears and is dismissed
    """

    try:
        logger.info("Navigating to main page...")
        page.goto("https://zachestnyibiznes.ru/", wait_until="domcontentloaded", timeout=60000)
        captcha_handler.handle_browser_check(page, timeout=30)

        logger.info("Going to login page...")
        page.goto("https://zachestnyibiznes.ru/login", wait_until="domcontentloaded", timeout=60000)
        captcha_handler.handle_browser_check(page, timeout=30)

        # --- Case 1: redirected automatically to /user → already logged in
        if "/user" in page.url.lower():
            logger.success(f"Already logged in (redirected to {page.url})")
            return True

        # --- Case 2: need to submit credentials ---
        page.get_by_role("textbox", name="Email или номер телефона").fill(LOGIN)
        page.get_by_role("textbox", name="Пароль").fill(PWD)
        logger.debug("Filled credentials.")

        page.get_by_role("button", name="Войти").click()
        logger.info("Clicked 'Войти'.")

        # Wait a bit for server response / captcha
        time.sleep(2)
        captcha_handler.handle_browser_check(page, timeout=20)

        # --- Premium modal handling ---
        modal = page.locator("#premiumloginmodal")
        try:
            modal.wait_for(state="visible", timeout=10000)
            logger.success("Premium login modal detected.")

            # Click "Понятно" to dismiss it
            page.get_by_role("button", name="Понятно").click(timeout=3000)
            logger.info("Dismissed premium modal.")

            modal.wait_for(state="detached", timeout=8000)

            logger.success(f"Login successful as {LOGIN}")
            return True

        except TimeoutError:
            logger.error("Premium login modal did not appear after login.")
            quick_dump(page, "after_login_fail")
            return False

    except Exception as e:
        logger.error(f"Login error: {e}")
        quick_dump(page, "exception")
        return False
