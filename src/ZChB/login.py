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
    - Submit login form
    - If "Вы вошли в Платный доступ" appears -> success
    """

    try:
        logger.info("Navigating to main page...")
        page.goto("https://zachestnyibiznes.ru/", wait_until="domcontentloaded", timeout=60000)

        captcha_handler.handle_browser_check(page, timeout=30)

        logger.info("Going to login page...")
        page.goto("https://zachestnyibiznes.ru/login", wait_until="domcontentloaded", timeout=60000)
        captcha_handler.handle_browser_check(page, timeout=30)

        # Fill form
        page.get_by_role("textbox", name="Email или номер телефона").fill(LOGIN)
        page.get_by_role("textbox", name="Пароль").fill(PWD)
        logger.debug("Filled credentials.")

        # Submit
        page.get_by_role("button", name="Войти").click()
        logger.info("Clicked 'Войти'.")

        # Wait a bit for server response / redirect
        time.sleep(3)
        captcha_handler.handle_browser_check(page, timeout=20)

        # Look for premium confirmation
        try:
            premium_locator = page.get_by_text("Вы вошли в Платный доступ", exact=False)
            premium_locator.wait_for(timeout=8000)
            logger.success("Login successful: detected premium confirmation.")
            return True
        except TimeoutError:
            logger.error("Did not see premium confirmation after login.")
            return False

    except Exception as e:
        logger.error(f"Login error: {e}")
        return False
