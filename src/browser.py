from patchright.sync_api import sync_playwright, Playwright, Browser as PlaywrightBrowser
from loguru import logger

class Browser:
    """A context manager for the Playwright browser."""
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright_context = None
        self._playwright: Playwright | None = None
        self.browser: PlaywrightBrowser | None = None

    def __enter__(self):
        logger.debug("Launching browser.")
        self._playwright_context = sync_playwright()
        self._playwright = self._playwright_context.__enter__()
        self.browser = self._playwright.chromium.launch_persistent_context(user_data_dir="datadir", 
                                                                           channel="chrome", 
                                                                           headless=self._headless)
        return self.browser

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            self.browser.close()
            logger.debug("Browser closed.")
        if self._playwright_context:
            self._playwright_context.__exit__(exc_type, exc_val, exc_tb)
