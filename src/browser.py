from playwright.async_api import async_playwright, Browser as PlaywrightBrowser, BrowserContext
from loguru import logger

class Browser:
    """Manages a persistent Playwright browser instance and context."""
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright_context_manager: async_playwright | None = None
        self._playwright: async_playwright | None = None
        self._browser: PlaywrightBrowser | None = None
        self.context: BrowserContext | None = None

    async def launch(self):
        """Launches the browser, the Playwright driver, and a persistent context."""
        if not self._playwright:
            logger.info("Starting Playwright driver...")
            self._playwright_context_manager = async_playwright()
            self._playwright = await self._playwright_context_manager.start()
        
        if not self._browser or not self._browser.is_connected():
            logger.info("Launching browser...")
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                channel="chrome"
            )

        if not self.context:
             logger.info("Creating persistent browser context...")
             self.context = await self._browser.new_context(
                 storage_state="datadir/state.json" if await self._check_storage_state() else None
             )

        logger.success("Browser and context are launched and ready.")

    async def _check_storage_state(self):
        """Helper to check if storage state file exists."""
        import os
        return os.path.exists("datadir/state.json")

    async def close(self):
        """Closes the browser and stops the Playwright driver."""
        if self.context:
            await self.context.storage_state(path="datadir/state.json")
            await self.context.close()
            logger.info("Browser context closed and state saved.")
        if self._browser:
            await self._browser.close()
            logger.info("Browser closed.")
        if self._playwright_context_manager:
            await self._playwright_context_manager.stop()
            logger.info("Playwright driver stopped.")
        self.context = None
        self._browser = None
        self._playwright_context_manager = None

    def is_connected(self) -> bool:
        """Checks if the browser instance is running and connected."""
        return self._browser is not None and self._browser.is_connected()