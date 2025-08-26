import os
import re
import time
from typing import Optional
from dotenv import load_dotenv
from patchright.sync_api import Page, TimeoutError
from loguru import logger
from twocaptcha import TwoCaptcha

class CaptchaHandler:
    def __init__(self):
        """Initialize the CAPTCHA handler with environment variables."""
        load_dotenv()  # Ensure environment variables are loaded
        self.api_key = os.getenv('APIKEY_2CAPTCHA')
        if not self.api_key:
            logger.warning("APIKEY_2CAPTCHA environment variable not set. CAPTCHA solving will be disabled.")
    
    def _is_browser_check_page(self, page: Page) -> bool:
        """
        Detect browser check page with support for both English and Russian languages.
        Returns True if characteristic elements/texts are found.
        """
        try:
            # Check for common elements (language-independent)
            if page.locator("#ddg-l10n-title").count() > 0:
                return True
            if page.locator("img#ddg-img-loading").count() > 0:
                return True
            
            # Check body attributes
            body = page.locator("body")
            if body.count() > 0:
                attr_flag = body.get_attribute("data-ddg-origin") or body.get_attribute("data-ddg-l10n")
                if attr_flag:
                    return True
            
            # Check for text patterns in both Russian and English
            text_patterns = [
                # Russian texts
                "Проверка браузера перед переходом",
                "Подождите несколько секунд",
                # English texts
                "Browser check before proceeding",
                "Please wait a few seconds",
                "Checking your browser"
            ]
            
            for pattern in text_patterns:
                if page.get_by_text(pattern, exact=False).count() > 0:
                    return True
            
            # Check for request info pattern (common in both languages)
            if page.get_by_text(re.compile(r"Request ID: .* \| IP: .* \| Time:")).count() > 0:
                return True
                
        except Exception as e:
            logger.debug(f"Failed to check for browser check page: {e}")
        
        return False

    def _solve_ddg_captcha(self, page: Page) -> bool:
        """
        Solve DDOS-Guard CAPTCHA if present.
        Returns True if CAPTCHA was solved successfully, False otherwise.
        """
        logger.info("Checking for CAPTCHA challenge...")
        try:
            # Wait for CAPTCHA iframe
            iframe_element = page.wait_for_selector('#ddg-iframe', timeout=10000)
            iframe = iframe_element.content_frame()
            logger.info("CAPTCHA iframe found")
            
            # Click the initial checkbox
            checkbox_selector = '.ddg-captcha__checkbox'
            logger.info(f"Waiting for checkbox: {checkbox_selector}")
            checkbox = iframe.wait_for_selector(checkbox_selector, timeout=10000)
            checkbox.click()
            logger.info("Checkbox clicked, waiting for challenge...")
            
            # Wait for challenge modal
            challenge_modal_selector = '#ddg-challenge'
            iframe.wait_for_selector(
                challenge_modal_selector, state='visible', timeout=10000
            )
            logger.info("Challenge modal appeared")
            
            # Extract CAPTCHA image
            captcha_image_element = iframe.wait_for_selector(
                '.ddg-modal__captcha-image', state='visible', timeout=10000
            )
            logger.info("CAPTCHA image found")
            
            img_src = captcha_image_element.get_attribute('src')
            if not img_src or not img_src.startswith('data:image'):
                logger.error("Could not extract valid image data from CAPTCHA")
                return False
            
            base64_content = img_src.split(',')[1]
            logger.info("Extracted base64 image data")
            
            # Solve CAPTCHA using 2Captcha
            if not self.api_key:
                logger.error("Cannot solve CAPTCHA - API key not configured")
                return False
                
            solver = TwoCaptcha(self.api_key)
            logger.info("Sending CAPTCHA to 2Captcha service...")
            
            try:
                result = solver.normal(base64_content)
                captcha_text = result['code']
                logger.info(f"CAPTCHA solved: {captcha_text}")
            except Exception as e:
                logger.error(f"Failed to solve CAPTCHA: {e}")
                return False
            
            # Submit the solution
            input_field = iframe.query_selector('.ddg-modal__input')
            submit_button = iframe.query_selector('.ddg-modal__submit')
            
            if input_field and submit_button:
                input_field.fill(captcha_text)
                submit_button.click()
                logger.info("Submitted CAPTCHA solution")
                
                # Wait for CAPTCHA to complete
                page.wait_for_selector('#ddg-iframe', state='hidden', timeout=15000)
                logger.success("CAPTCHA successfully solved")
                return True
            else:
                logger.error("Could not find CAPTCHA input elements")
                return False
                
        except TimeoutError:
            logger.info("No CAPTCHA challenge detected within timeout")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during CAPTCHA solving: {e}")
            return False

    def handle_browser_check(self, page: Page, expected_url: Optional[str] = None, timeout: float = 30.0) -> bool:
        """
        Handle browser verification and CAPTCHA challenges.
        Returns True if successful, False if timed out or failed.
        """
        start_time = time.monotonic()
        deadline = start_time + timeout
        
        # First check if we're on a browser verification page
        if not self._is_browser_check_page(page):
            logger.debug("No browser verification detected")
            return True
        
        logger.info("Browser verification detected - handling CAPTCHA if present")
        
        # Attempt to solve CAPTCHA if present
        captcha_result = self._solve_ddg_captcha(page)
        
        if captcha_result:
            logger.success("CAPTCHA handling completed successfully")
        else:
            logger.info("No CAPTCHA present or CAPTCHA solving failed")
        
        # Wait for redirect or page change
        logger.info("Waiting for page redirect after verification...")
        
        if expected_url:
            remaining = max(0, deadline - time.monotonic())
            try:
                page.wait_for_url(expected_url, timeout=int(remaining * 1000))
                logger.success(f"Redirected to expected URL: {page.url}")
                return True
            except TimeoutError:
                logger.debug("Direct URL wait timed out, switching to polling")
        
        # Fallback to polling for page change
        check_interval = 0.25
        while time.monotonic() < deadline:
            try:
                if not self._is_browser_check_page(page):
                    logger.success(f"Browser verification completed. Current URL: {page.url}")
                    return True
                
                if expected_url:
                    try:
                        page.wait_for_url(expected_url, timeout=1000)  # Short check
                        logger.success(f"Reached expected URL: {page.url}")
                        return True
                    except TimeoutError:
                        pass
                
                time.sleep(check_interval)
            except Exception as e:
                logger.debug(f"Error during polling: {e}")
                time.sleep(check_interval)
        
        logger.warning(
            f"Timeout waiting for browser verification to complete. "
            f"Elapsed: {time.monotonic() - start_time:.2f}s, "
            f"Current URL: {page.url}"
        )
        return False