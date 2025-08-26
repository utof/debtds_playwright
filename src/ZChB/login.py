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
                # Try to continue anyway as sometimes we might already be past the CAPTCHA

            # Check if already logged in (email somewhere in the DOM)
            if page.get_by_text(LOGIN, exact=True).count() > 0:
                logger.info(f"Already logged in as {LOGIN}")
                return True

            logger.info("Not logged in. Going to login page...")
            page.goto("https://zachestnyibiznes.ru/login", wait_until="domcontentloaded", timeout=60000)
            
            # Handle browser verification and CAPTCHA on login page
            if not captcha_handler.handle_browser_check(page, timeout=30):
                logger.warning("Browser verification/CAPTCHA handling failed on login page")
                # Try to continue anyway

            # Wait a moment for the page to settle
            time.sleep(2)
            
            # Check if we're actually on the login page
            if "login" not in page.url.lower():
                logger.warning(f"Not on login page, URL is: {page.url}")
                continue

            # Fill login form
            page.get_by_role("textbox", name="Email или номер телефона").fill(LOGIN)
            page.get_by_role("textbox", name="Пароль").fill(PWD)
            logger.debug("Filled login credentials.")

            # Optional: Add a small delay to ensure form is fully populated
            time.sleep(1)
            
            # Take screenshot before clicking login for debugging
            try:
                page.screenshot(path=f"before_login_attempt_{attempt}.png")
            except:
                pass

            page.get_by_role("button", name="Войти").click()
            logger.info("Clicked 'Войти'.")

            # Wait for potential redirects or form submissions
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            
            # Handle potential CAPTCHA after login attempt
            if not captcha_handler.handle_browser_check(page, timeout=30):
                logger.warning("CAPTCHA appeared after login attempt")

            # Wait a bit longer for the login process to complete
            time.sleep(3)
            
            # Take screenshot after login attempt for debugging
            try:
                page.screenshot(path=f"after_login_attempt_{attempt}.png")
            except:
                pass

            # Check if "другого устройства" message is shown (session conflict)
            if page.get_by_text("В Ваш аккаунт выполнен вход с другого устройства", exact=False).count() > 0:
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
                        captcha_handler.handle_browser_check(page, timeout=20)
                except Exception as e:
                    logger.error(f"Could not read timeout countdown: {e}")
                
                # After redirect, check again if login persisted
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            
            # Check if "Вы вошли в Платный доступ" confirmation appears
            if page.get_by_text("Вы вошли в Платный доступ", exact=False).count() > 0:
                logger.info("Detected premium login confirmation.")
                try:
                    page.get_by_role("button", name="Понятно").click(timeout=3000)
                    logger.debug("Clicked 'Понятно'.")
                    # Wait a moment after clicking
                    time.sleep(2)
                except TimeoutError:
                    logger.debug("No 'Понятно' button to click.")

            # More comprehensive check for login success
            # Check for multiple indicators of successful login
            login_indicators = [
                page.get_by_text(LOGIN, exact=True).count() > 0,
                page.get_by_text("Выйти", exact=False).count() > 0,  # Logout button
                page.get_by_text("Мой профиль", exact=False).count() > 0,  # Profile link
                page.get_by_text("Личный кабинет", exact=False).count() > 0,  # Personal account
            ]
            
            if any(login_indicators):
                logger.success(f"Login successful as {LOGIN}")
                return True
            else:
                logger.warning(f"Login attempt {attempt} did not succeed - trying again")
                # Wait before next attempt
                time.sleep(5)
                continue

        except Exception as e:
            logger.error(f"Error during login attempt {attempt}: {e}")
            # Take screenshot for debugging
            try:
                page.screenshot(path=f"login_error_attempt_{attempt}.png")
            except:
                pass
            # Wait before next attempt
            time.sleep(5)
            continue

    logger.error("All login attempts failed")
    return False