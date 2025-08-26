import os
import re
import time
import base64
from typing import Optional
from dotenv import load_dotenv
from playwright.sync_api import Page, TimeoutError
from loguru import logger
from twocaptcha import TwoCaptcha


class CaptchaHandler:
    """Handler for DDOS-Guard browser verification and CAPTCHA challenges."""
    
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv('APIKEY_2CAPTCHA')
        if not self.api_key:
            logger.error("APIKEY_2CAPTCHA environment variable not set")
            raise ValueError("APIKEY_2CAPTCHA environment variable not set")

    def _is_browser_check_page(self, page: Page) -> bool:
        """
        Detect browser verification page using heuristics.
        """
        try:
            # Check for typical DDOS-Guard selectors and text patterns
            selectors_to_check = [
                '#ddg-iframe',
                '#ddg-l10n-title',
                '#ddg-img-loading',
                '.ddg-captcha__checkbox',
                '.ddg-modal__captcha-image',
                '.ddg-modal__input',
                '.ddg-modal__submit'
            ]
            
            for selector in selectors_to_check:
                if page.locator(selector).count() > 0:
                    return True
            
            # Check for text patterns in both English and Russian
            text_patterns = [
                "Проверка браузера",
                "Browser verification",
                "Подождите несколько секунд",
                "Please wait a few seconds",
                "Request ID:",
                "DDOS-GUARD"
            ]
            
            for pattern in text_patterns:
                if page.get_by_text(pattern, exact=False).count() > 0:
                    return True
            
            # Check body attributes that indicate DDOS-Guard
            body = page.locator("body")
            if body.count() > 0:
                attrs = body.get_attribute("data-ddg-origin") or body.get_attribute("data-ddg-l10n")
                if attrs:
                    return True
                    
        except Exception as e:
            logger.debug(f"Error checking browser verification page: {e}")
            
        return False

    def _wait_for_captcha_to_load(self, iframe) -> bool:
        """
        Wait for the CAPTCHA to finish loading and be ready for interaction.
        """
        try:
            # Wait for the pending state to disappear
            iframe.wait_for_selector('.ddg-captcha--pending', state='detached', timeout=10000)
            logger.info("CAPTCHA finished loading")
            return True
        except TimeoutError:
            logger.warning("CAPTCHA loading timed out")
            return False

    def _solve_captcha(self, page: Page) -> bool:
        """
        Solve the DDOS-Guard CAPTCHA challenge.
        """
        logger.info("Attempting to solve CAPTCHA")
        
        try:
            # Wait for the iframe containing the CAPTCHA
            iframe_element = page.wait_for_selector('#ddg-iframe', timeout=15000)
            iframe = iframe_element.content_frame()
            logger.info("CAPTCHA iframe found")

            # Click the initial checkbox
            checkbox_selector = '.ddg-captcha__checkbox'
            checkbox = iframe.wait_for_selector(checkbox_selector, timeout=10000)
            checkbox.click()
            logger.info("Checkbox clicked, waiting for challenge to load")

            # Wait for the CAPTCHA to finish loading
            if not self._wait_for_captcha_to_load(iframe):
                return False
                
            # Wait for the challenge modal
            challenge_modal_selector = '#ddg-challenge'
            try:
                iframe.wait_for_selector(challenge_modal_selector, state='visible', timeout=10000)
                logger.info("Challenge modal visible")
            except TimeoutError:
                # Sometimes the CAPTCHA solves itself after checkbox click
                logger.info("No challenge modal appeared - CAPTCHA may have auto-resolved")
                # Check if the iframe is still there or if we've been redirected
                try:
                    page.wait_for_selector('#ddg-iframe', state='hidden', timeout=5000)
                    logger.info("CAPTCHA resolved automatically")
                    return True
                except TimeoutError:
                    logger.warning("CAPTCHA did not auto-resolve")
                    return False

            # Extract the CAPTCHA image
            captcha_image_element = iframe.wait_for_selector(
                '.ddg-modal__captcha-image', state='visible', timeout=10000
            )
            logger.info("CAPTCHA image found")
            
            # Let's try a different approach to get the image data
            # Wait for the image to be fully loaded
            logger.info("Waiting for image to be fully loaded...")
            iframe.wait_for_function("""
                () => {
                    const img = document.querySelector('.ddg-modal__captcha-image');
                    return img && img.complete && img.naturalWidth > 0;
                }
            """, timeout=10000)
            
            # Get the base64 source with additional error checking
            img_src = captcha_image_element.get_attribute('src')
            
            if not img_src:
                # Try to get the source via JavaScript evaluation
                img_src = iframe.evaluate("""
                    () => {
                        const img = document.querySelector('.ddg-modal__captcha-image');
                        return img ? img.src : null;
                    }
                """)
            
            if not img_src or not img_src.startswith('data:image'):
                logger.error(f"Invalid image source: {img_src}")
                return False
            
            base64_content = img_src.split(',')[1]
            logger.info("Successfully extracted CAPTCHA image data")

            # Solve using 2Captcha
            solver = TwoCaptcha(self.api_key)
            logger.info("Sending CAPTCHA to solver...")
            
            try:
                result = solver.normal(base64_content)
                captcha_text = result['code']
                logger.info(f"CAPTCHA solved: {captcha_text}")
            except Exception as e:
                logger.error(f"2Captcha API error: {e}")
                return False

            # Submit the solution
            input_field = iframe.query_selector('.ddg-modal__input')
            submit_button = iframe.query_selector('.ddg-modal__submit')

            if input_field and submit_button:
                input_field.fill(captcha_text)
                submit_button.click()
                
                # Wait for CAPTCHA to be validated
                try:
                    page.wait_for_selector('#ddg-iframe', state='hidden', timeout=20000)
                    logger.success("CAPTCHA solved successfully")
                    return True
                except TimeoutError:
                    logger.warning("Timeout waiting for CAPTCHA to resolve")
                    # Sometimes the page might still have loaded despite the iframe
                    # Check if we're on the expected page
                    current_url = page.url
                    if "zachestnyibiznes.ru" in current_url and "ddg" not in current_url:
                        logger.info("Appears to be on target site despite iframe visibility")
                        return True
                    return False
            else:
                logger.error("Could not find input field or submit button")
                return False

        except Exception as e:
            logger.error(f"Error solving CAPTCHA: {e}")
            return False

    def handle_browser_check(self, page: Page, timeout: float = 30.0) -> bool:
        """
        Handle browser verification and CAPTCHA challenges.
        Returns True if successful, False otherwise.
        """
        logger.info("Checking for browser verification/CAPTCHA")
        
        start_time = time.time()
        check_interval = 1.0
        
        while time.time() - start_time < timeout:
            if not self._is_browser_check_page(page):
                logger.info("No browser verification detected")
                return True
                
            # Check if CAPTCHA iframe is present
            try:
                if page.locator('#ddg-iframe').count() > 0:
                    logger.info("CAPTCHA detected, attempting to solve")
                    result = self._solve_captcha(page)
                    if result:
                        return True
                    else:
                        logger.warning("CAPTCHA solution failed")
                        return False
            except Exception as e:
                logger.debug(f"Error checking for CAPTCHA iframe: {e}")
                
            # Wait a bit before checking again
            time.sleep(check_interval)
        
        logger.warning("Browser verification/CAPTCHA handling timed out")
        return False