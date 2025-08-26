import os
import re
import time
from patchright.sync_api import Page, TimeoutError
from loguru import logger
from dotenv import load_dotenv
from .handle_captcha import CaptchaHandler

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
    max_attempts = 3
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        logger.info(f"Login attempt {attempt}/{max_attempts}")
        
        try:
            logger.info("Navigating to main page...")
            page.goto("https://zachestnyibiznes.ru/", wait_until="domcontentloaded", timeout=60000)
            
            # Handle browser verification and CAPTCHA with the comprehensive handler
            if not captcha_handler.handle_browser_check(page, timeout=30):
                logger.warning("Browser verification/CAPTCHA handling failed on main page")

            # Check if already logged in (email somewhere in the DOM)
            if page.get_by_text(LOGIN, exact=True).count() > 0:
                logger.info(f"Already logged in as {LOGIN}")
                return True

            logger.info("Not logged in. Going to login page...")
            page.goto("https://zachestnyibiznes.ru/login", wait_until="domcontentloaded", timeout=60000)
            
            # Handle browser verification and CAPTCHA on login page
            if not captcha_handler.handle_browser_check(page, timeout=30):
                logger.warning("Browser verification/CAPTCHA handling failed on login page")

            time.sleep(2)
            
            if "login" not in page.url.lower():
                logger.warning(f"Not on login page, URL is: {page.url}")
                continue

            # Fill login form
            page.get_by_role("textbox", name="Email или номер телефона").fill(LOGIN)
            page.get_by_role("textbox", name="Пароль").fill(PWD)
            logger.debug("Filled login credentials.")

            time.sleep(1)
            
            try:
                page.screenshot(path=f"before_login_attempt_{attempt}.png")
            except:
                pass

            page.get_by_role("button", name="Войти").click()
            logger.info("Clicked 'Войти'.")

            page.wait_for_load_state("domcontentloaded", timeout=15000)
            
            if not captcha_handler.handle_browser_check(page, timeout=30):
                logger.warning("CAPTCHA appeared after login attempt")

            time.sleep(3)
            
            try:
                page.screenshot(path=f"after_login_attempt_{attempt}.png")
            except:
                pass

            # Handle session conflict message
            if page.get_by_text("В Ваш аккаунт выполнен вход с другого устройства", exact=False).count() > 0:
                logger.warning("Detected 'другого устройства' session conflict.")
                try:
                    timer_text = page.locator("span#t").inner_text(timeout=5000)
                    logger.debug(f"Timeout countdown: {timer_text}")
                    if re.match(r"^\d+:\d{2}$", timer_text):
                        minutes, seconds = map(int, timer_text.split(":"))
                        wait_time = minutes * 60 + seconds + 5
                        logger.info(f"Waiting {wait_time}s for redirect...")
                        time.sleep(wait_time)
                        captcha_handler.handle_browser_check(page, timeout=20)
                except Exception as e:
                    logger.error(f"Could not read timeout countdown: {e}")
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            
            # Premium login confirmation
            if page.get_by_text("Вы вошли в Платный доступ", exact=False).count() > 0:
                logger.info("Detected premium login confirmation.")

            # --- MINIMAL CHANGE: canonical success check ---
            # After handling captcha, we succeed if "Вход / Регистрация" is NOT present
            if page.get_by_text("Вход / Регистрация", exact=False).count() == 0:
                logger.success(f"Login successful as {LOGIN}")
                return True
            # ------------------------------------------------

            logger.warning(f"Login attempt {attempt} did not succeed - trying again")
            time.sleep(5)
            continue

        except Exception as e:
            logger.error(f"Error during login attempt {attempt}: {e}")
            try:
                page.screenshot(path=f"login_error_attempt_{attempt}.png")
            except:
                pass
            time.sleep(5)
            continue

    logger.error("All login attempts failed")
    return False
