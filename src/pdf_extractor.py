# ========================== IMPORTANT WARNING FOR DEVELOPERS ==========================
#
# This script is highly fragile and specifically tuned to bypass bot detection
# on sites like kad.arbitr.ru. Do not modify the core request logic without
# understanding the following points.
#
# --- How It Works ---
# 1. A full Selenium browser session ("robot helper") visits the URL to appear
#    like a real user and acquire valid session cookies ("library card").
# 2. These cookies are then copied to a separate, lightweight `requests` session
#    ("delivery drone").
# 3. The `requests` session downloads the PDF using the copied cookies.
#
# --- How It Broke (The "Incident") ---
# The script failed when we tried to make the `requests` call "smarter" by
# adding a `User-Agent` header copied from the Selenium browser.
#
# --- Why It Broke (Root Cause) ---
# The server's security flagged an inconsistency. The `requests` library has its
# own default `User-Agent`. By adding the browser's User-Agent, we created a
# mismatched request fingerprint (e.g., browser User-Agent but with the header
# structure of a Python script). This anomaly was detected as bot behavior,
# and the server blocked the request.
#
# --- THE GOLDEN RULE ---
# DO NOT add custom headers (especially 'User-Agent') to the `requests` call.
# Its success depends on its simplicity. Just transfer the cookies and let
# `requests` use its own default headers.
#
# ======================================================================================

import random
import time
import logging
from io import BytesIO
from typing import Optional
import sys

import requests
from PyPDF2 import PdfReader
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

# Using the logger configured by the main FastAPI app
logger = logging.getLogger("uvicorn.error")

# --- NEW: Global session management ---
_global_pdf_session: Optional["PDFSession"] = None
# --- END NEW ---

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.91 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
]

class PDFSession:
    def __init__(self, wait_sec: float = 15, headless: bool = True, retries: int = 2):
        self.wait_sec = wait_sec
        self.headless = headless
        self.retries = retries
        self.driver = self._init_browser(headless=self.headless)
    
    def _init_browser(self, headless: bool):
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless=new")
        
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--lang=ru-RU")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-popup-blocking")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--ignore-certificate-errors")

        user_agent = random.choice(USER_AGENTS)
        chrome_options.add_argument(f"user-agent={user_agent}")
        logger.info(f"Using user-agent: {user_agent}")

        try:
            logger.info("Initializing new browser instance...")
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()), 
                options=chrome_options
            )
            logger.info("Browser instance initialized.")
            return driver
        except WebDriverException as e:
            logger.warning("Headless browser failed. Trying headful mode.")
            if headless:
                return self._init_browser(headless=False)
            else:
                raise e

    def _simulate_wait(self):
        sleep_time = self.wait_sec + random.uniform(0.5, 2.5)
        logger.info(f"Sleeping for {sleep_time:.2f} seconds")
        time.sleep(sleep_time)

    def close(self):
        if self.driver:
            logger.info("Closing browser instance...")
            self.driver.quit()
            logger.info("Browser instance closed.")

    def fetch_pdf_content(self, url: str) -> Optional[str]:
        for attempt in range(1, self.retries + 1):
            try:
                logger.info(f"[Attempt {attempt}] Navigating to {url}")
                self.driver.get(url)
                self._simulate_wait()

                cookies = self.driver.get_cookies()
                session = requests.Session()
                for cookie in cookies:
                    session.cookies.set(cookie["name"], cookie["value"])

                response = session.get(url, timeout=20)
                content_type = response.headers.get("Content-Type", "").lower()
                
                if content_type.startswith("application/pdf"):
                    reader = PdfReader(BytesIO(response.content))
                    texts = [page.extract_text() or "" for page in reader.pages]
                    final_text = "\n".join(texts).strip()
                    if final_text:
                        logger.info(f"Direct download successful: {url}")
                        return final_text
                
                logger.error("Direct download failed.")

            except (WebDriverException, TimeoutException, requests.RequestException) as e:
                logger.error(f"Attempt {attempt} failed: {str(e)}")
                self._simulate_wait()
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}")
                self._simulate_wait()
        
        logger.error(f"All attempts failed for: {url}")
        return None

# --- NEW: Functions to manage the global session ---
def get_global_pdf_session() -> PDFSession:
    """
    Initializes the global PDFSession if it doesn't exist, and returns it.
    This is lazy initialization - the browser only starts on the first request.
    """
    global _global_pdf_session
    if _global_pdf_session is None:
        _global_pdf_session = PDFSession(wait_sec=5, headless=True)
    return _global_pdf_session

def close_global_pdf_session():
    """Closes the global PDF session if it was initialized."""
    global _global_pdf_session
    if _global_pdf_session is not None:
        _global_pdf_session.close()
        _global_pdf_session = None

def extract_text_from_url(url: str) -> dict:
    """
    A wrapper function to extract text from a PDF URL using the GLOBAL PDFSession.
    """
    try:
        # Get the single, shared browser session
        session = get_global_pdf_session()
        pdf_text = session.fetch_pdf_content(url)
        if pdf_text:
            return {"success": True, "text": pdf_text}
        else:
            return {"success": False, "error": "Failed to extract text from the PDF."}
    except Exception as e:
        logger.error(f"An exception occurred in the extraction process for {url}: {e}")
        return {"success": False, "error": f"An internal error occurred: {str(e)}"}
# --- END NEW ---