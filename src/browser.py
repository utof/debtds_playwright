from patchright.async_api import async_playwright, async_playwright, Browser as PlaywrightBrowser
from loguru import logger

class Browser:
    """A context manager for the Playwright browser."""
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright_context = None
        self._playwright: async_playwright | None = None
        self.browser: PlaywrightBrowser | None = None

    async def __aenter__(self):
        logger.debug("Launching browser.")
        self._playwright_context = async_playwright()
        self._playwright = await self._playwright_context.__aenter__()
        self.browser = await self._playwright.chromium.launch_persistent_context(user_data_dir="datadir", 
                                                                           channel="chrome", 
                                                                           headless=self._headless)
        return self.browser

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            await self.browser.close()
            logger.debug("Browser closed.")
        if self._playwright_context:
            await self._playwright_context.__aexit__(exc_type, exc_val, exc_tb)