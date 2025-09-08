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
            return webdriver.Chrome(
                service=Service(ChromeDriverManager().install()), 
                options=chrome_options
            )
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
            self.driver.quit()

    def fetch_pdf_content(self, url: str) -> Optional[str]:
        for attempt in range(1, self.retries + 1):
            try:
                logger.info(f"[Attempt {attempt}] Navigating to {url}")
                self.driver.get(url)
                self._simulate_wait()

                # Copy cookies to requests session
                cookies = self.driver.get_cookies()
                session = requests.Session()
                for cookie in cookies:
                    session.cookies.set(cookie["name"], cookie["value"])

                # Try direct download first
                response = session.get(url, timeout=20)
                content_type = response.headers.get("Content-Type", "").lower()
                
                if content_type.startswith("application/pdf"):
                    reader = PdfReader(BytesIO(response.content))
                    texts = [page.extract_text() or "" for page in reader.pages]
                    final_text = "\n".join(texts).strip()
                    if final_text:
                        logger.info(f"Direct download successful: {url}")
                        return final_text
                
                # Fallback to CDP if direct download fails (original logging)
                logger.error("Direct download failed.")

            except (WebDriverException, TimeoutException, requests.RequestException) as e:
                logger.error(f"Attempt {attempt} failed: {str(e)}")
                self._simulate_wait()
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}")
                self._simulate_wait()
        
        logger.error(f"All attempts failed for: {url}")
        return None

def extract_text_from_url(url: str) -> dict:
    """
    A wrapper function to extract text from a PDF URL using the PDFSession class.
    """
    session = None
    try:
        # The session logic is kept as it was in the original `main` block
        session = PDFSession(wait_sec=5, headless=True)
        pdf_text = session.fetch_pdf_content(url)
        if pdf_text:
            return {"success": True, "text": pdf_text}
        else:
            return {"success": False, "error": "Failed to extract text from the PDF."}
    except Exception as e:
        logger.error(f"An exception occurred in the extraction process for {url}: {e}")
        return {"success": False, "error": f"An internal error occurred: {str(e)}"}
    finally:
        if session:
            session.close()
