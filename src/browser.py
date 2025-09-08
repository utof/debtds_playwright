from patchright.async_api import async_playwright, Browser as PlaywrightBrowser
from loguru import logger

class Browser:
    """Manages a persistent Playwright browser instance."""
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright_context: async_playwright | None = None
        self._playwright: async_playwright | None = None
        self.browser: PlaywrightBrowser | None = None

    async def launch(self):
        """Launches the browser and the Playwright driver."""
        if not self._playwright:
            logger.info("Starting Playwright driver...")
            self._playwright_context = async_playwright()
            self._playwright = await self._playwright_context.start()
        
        if not self.browser or not self.browser.is_connected():
            logger.info("Launching persistent browser context...")
            self.browser = await self._playwright.chromium.launch_persistent_context(
                user_data_dir="datadir",
                channel="chrome",
                headless=self._headless
            )
        logger.success("Browser is launched and ready.")

    async def close(self):
        """Closes the browser and stops the Playwright driver."""
        if self.browser:
            await self.browser.close()
            logger.info("Browser context closed.")
        if self._playwright_context:
            await self._playwright_context.stop()
            logger.info("Playwright driver stopped.")
        self.browser = None
        self._playwright_context = None

    def is_connected(self) -> bool:
        """Checks if the browser instance is running and connected."""
        return self.browser is not None and self.browser.is_connected()