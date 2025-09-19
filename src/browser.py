from patchright.async_api import async_playwright, Browser as PlaywrightBrowser, BrowserContext
from loguru import logger

class Browser:
    """Manages a persistent Playwright browser instance and context."""

    def __init__(self, headless: bool = True, datadir: str | None = None):
        self._headless = headless
        self._datadir = datadir
        self._playwright_context_manager: async_playwright | None = None
        self._playwright: async_playwright | None = None
        self.context: BrowserContext | None = None

    async def launch(self):
        """
        Launches a persistent browser context using the provided datadir.
        """
        if self.is_connected():
            logger.info("Browser context is already launched and connected.")
            return

        logger.info("Starting Playwright driver...")
        self._playwright_context_manager = async_playwright()
        self._playwright = await self._playwright_context_manager.start()

        logger.info(f"Launching persistent browser context with user data dir: '{self._datadir}'...")
        self.context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self._datadir,
            headless=self._headless,
            channel="chrome",
        )

        logger.success("Persistent browser context is launched and ready.")

    async def close(self):
        """Closes the browser context and stops the Playwright driver."""
        if self.context:
            await self.context.close()
            logger.info("Browser context closed.")
            self.context = None
        
        if self._playwright_context_manager:
            await self._playwright_context_manager.stop()
            logger.info("Playwright driver stopped.")
            self._playwright_context_manager = None
            self._playwright = None

    def is_connected(self) -> bool:
        """
        Checks if the browser context is initialized.
        With launch_persistent_context, the context is the primary object.
        If it exists, we consider it 'connected'.
        """
        # CORRECTED: For launch_persistent_context, a non-None context is our indicator of being connected.
        return self.context is not None