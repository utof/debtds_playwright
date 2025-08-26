import os
import re
import time
from patchright.sync_api import Page, TimeoutError
from loguru import logger
from dotenv import load_dotenv
from .handle_captcha import handle_captcha

load_dotenv()
LOGIN = os.getenv("LOGIN")
PWD = os.getenv("PWD")

def login(page: Page) -> bool:
    """
    Ensure we are logged into zachestnyibiznes.ru.
    Uses LOGIN and PWD from .env file.

    Returns:
        True if login successful, False otherwise.
    """

    logger.info("Navigating to main page...")
    page.goto("https://zachestnyibiznes.ru/", wait_until="domcontentloaded")
    handle_captcha(page, timeout=15)

    # Check if already logged in (email somewhere in the DOM)
    if page.get_by_text(LOGIN, exact=True).count() > 0:
        logger.info(f"Already logged in as {LOGIN}")
        return True

    logger.info("Not logged in. Going to login page...")
    page.goto("https://zachestnyibiznes.ru/login", wait_until="domcontentloaded")
    handle_captcha(page, timeout=15)

    try:
        # Fill login form
        page.get_by_role("textbox", name="Email или номер телефона").fill(LOGIN)
        page.get_by_role("textbox", name="Пароль").fill(PWD)
        logger.debug("Filled login credentials.")

        page.get_by_role("button", name="Войти").click()
        handle_captcha(page, timeout=15)
        logger.info("Clicked 'Войти'.")

        # Wait for either main page or error/timeout message
        page.wait_for_load_state("domcontentloaded", timeout=10000)

        # Check if "другого устройства" message is shown
        if page.get_by_text("В Ваш аккаунт выполнен вход с другого устройства").count() > 0:
            logger.warning("Detected 'другого устройства' session conflict.")

            # Extract timeout countdown from <span id="t">5:07</span>
            try:
                timer_text = page.locator("span#t").inner_text()
                logger.debug(f"Timeout countdown: {timer_text}")
                # crude sleep for the countdown duration
                if re.match(r"^\d+:\d{2}$", timer_text):
                    minutes, seconds = map(int, timer_text.split(":"))
                    wait_time = minutes * 60 + seconds + 2
                    logger.info(f"Waiting {wait_time}s for redirect...")
                    time.sleep(wait_time)
            except Exception as e:
                logger.error(f"Could not read timeout countdown: {e}")
            handle_captcha(page, timeout=15)
            # After redirect, check again if login persisted
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            if page.get_by_text(LOGIN, exact=True).count() == 0:
                logger.warning("Still not logged in after timeout. Retrying login...")
                return login(page)

        # Check if "Вы вошли в Платный доступ" confirmation appears
        if page.get_by_text("Вы вошли в Платный доступ").count() > 0:
            logger.info("Detected premium login confirmation.")
            try:
                page.get_by_role("button", name="Понятно").click(timeout=3000)
                logger.debug("Clicked 'Понятно'.")
                page.wait_for_url("https://zachestnyibiznes.ru/**", timeout=10000)
            except TimeoutError:
                logger.debug("No 'Понятно' button to click.")

        # page.wait_for_load_state("domcontentloaded", timeout=10000)
        # Final check: is our email present?
        if page.get_by_text(LOGIN, exact=True).count() > 0:
            logger.success(f"Login successful as {LOGIN}")
            return True
        else:
            logger.error("Login attempt did not succeed.")
            return False

    except Exception as e:
        logger.error(f"Error during login: {e}")
        return False
