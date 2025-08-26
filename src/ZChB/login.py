import os
import re
import time
from patchright.sync_api import Page, TimeoutError
from loguru import logger
from dotenv import load_dotenv
from .handle_captcha import CaptchaHandler  # Import the new handler

load_dotenv()
LOGIN = os.getenv("LOGIN")
PWD = os.getenv("PWD")

# Initialize the captcha handler
captcha_handler = CaptchaHandler()

def login(page: Page) -> bool:
    """
    Ensure we are logged into zachestnyibiznes.ru.
    Uses LOGIN and PWD from .env file.

    Returns:
        True if login successful, False otherwise.
    """

    logger.info("Navigating to main page...")
    page.goto("https://zachestnyibiznes.ru/", wait_until="domcontentloaded")
    
    # Handle browser verification and CAPTCHA with the comprehensive handler
    if not captcha_handler.handle_browser_check(
        page, 
        timeout=30
    ):
        logger.warning("Browser verification/CAPTCHA handling failed on main page")
        return False

    # Check if already logged in (email somewhere in the DOM)
    if page.get_by_text(LOGIN, exact=True).count() > 0:
        logger.info(f"Already logged in as {LOGIN}")
        return True

    logger.info("Not logged in. Going to login page...")
    page.goto("https://zachestnyibiznes.ru/login", wait_until="domcontentloaded")
    
    # Handle browser verification and CAPTCHA on login page
    if not captcha_handler.handle_browser_check(
        page, 
        timeout=30
    ):
        logger.warning("Browser verification/CAPTCHA handling failed on login page")

    try:
        # Fill login form
        page.get_by_role("textbox", name="Email или номер телефона").fill(LOGIN)
        page.get_by_role("textbox", name="Пароль").fill(PWD)
        logger.debug("Filled login credentials.")

        page.get_by_role("button", name="Войти").click()
        logger.info("Clicked 'Войти'.")

        # Handle potential CAPTCHA after login attempt
        if not captcha_handler.handle_browser_check(
            page, 
            timeout=30
        ):
            logger.warning("CAPTCHA appeared after login attempt")

        # Wait for page to load after login
        page.wait_for_load_state("domcontentloaded", timeout=15000)

        # Check if "другого устройства" message is shown (session conflict)
        if page.get_by_text("В Ваш аккаунт выполнен вход с другого устройства").count() > 0:
            logger.warning("Detected 'другого устройства' session conflict.")

            # Extract timeout countdown from <span id="t">5:07</span>
            try:
                timer_text = page.locator("span#t").inner_text(timeout=5000)
                logger.debug(f"Timeout countdown: {timer_text}")
                # crude sleep for the countdown duration
                if re.match(r"^\d+:\d{2}$", timer_text):
                    minutes, seconds = map(int, timer_text.split(":"))
                    wait_time = minutes * 60 + seconds + 5  # Add buffer time
                    logger.info(f"Waiting {wait_time}s for redirect...")
                    time.sleep(wait_time)
                    
                    # Check if we need to handle CAPTCHA after waiting
                    if not captcha_handler.handle_browser_check(
                        page, 
                        timeout=20
                    ):
                        logger.warning("CAPTCHA appeared after session conflict timeout")
                        
            except Exception as e:
                logger.error(f"Could not read timeout countdown: {e}")
            
            # After redirect, check again if login persisted
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            if page.get_by_text(LOGIN, exact=True).count() == 0:
                logger.warning("Still not logged in after timeout. Retrying login...")
                return login(page)  # Recursive retry

        # Check if "Вы вошли в Платный доступ" confirmation appears
        if page.get_by_text("Вы вошли в Платный доступ").count() > 0:
            logger.info("Detected premium login confirmation.")
            try:
                page.get_by_role("button", name="Понятно").click(timeout=3000)
                logger.debug("Clicked 'Понятно'.")
            except TimeoutError:
                logger.debug("No 'Понятно' button to click.")

        # page.wait_for_load_state("domcontentloaded", timeout=10000)
        # Final check: is our email present?
        if page.get_by_text(LOGIN, exact=True).count() > 0:
            logger.success(f"Login successful as {LOGIN}")
            return True
        else:
            logger.error("Login attempt did not succeed - user not found on page")
            # Take screenshot for debugging
            try:
                page.screenshot(path="login_failed.png")
                logger.debug("Screenshot saved as login_failed.png")
            except:
                pass
            return False

    except Exception as e:
        logger.error(f"Error during login: {e}")
        # Take screenshot for debugging
        try:
            page.screenshot(path="login_error.png")
            logger.debug("Screenshot saved as login_error.png")
        except:
            pass
        return False