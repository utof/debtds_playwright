import os
import time
from patchright.sync_api import Page, TimeoutError
from loguru import logger
from dotenv import load_dotenv
from .handle_captcha import CaptchaHandler

load_dotenv()
LOGIN = os.getenv("LOGIN")
PWD = os.getenv("PWD")

captcha_handler = CaptchaHandler()

def login(page: Page) -> bool:
    """
    Simplified login flow:
    - Navigate to site
    - Solve captcha if needed
    - If /login redirects to /user → already logged in → success
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
        # Fill form
        page.get_by_role("textbox", name="Email или номер телефона").fill(LOGIN)
        page.get_by_role("textbox", name="Пароль").fill(PWD)
        logger.debug("Filled credentials.")

        # Submit
        page.get_by_role("button", name="Войти").click()
        logger.info("Clicked 'Войти'.")

        # Wait for modal or captcha
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

            # Wait for modal to close
            modal.wait_for(state="detached", timeout=8000)

            logger.success(f"Login successful as {LOGIN}")
            return True

        except TimeoutError:
            logger.error("Premium login modal did not appear after login.")
            return False

    except Exception as e:
        logger.error(f"Login error: {e}")
        return False
