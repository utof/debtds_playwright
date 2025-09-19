from patchright.async_api import async_playwright, Playwright, BrowserContext
from loguru import logger

class Browser:
    """Manages a persistent Playwright browser instance and context."""

    def __init__(self, headless: bool = True, datadir: str | None = None):
        self._headless = headless
        self._datadir = datadir
        self._playwright_context_manager = None  # type: object | None
        self._playwright: Playwright | None = None
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
        # Close the persistent context first
        if self.context:
            try:
                await self.context.close()
                logger.info("Browser context closed.")
            finally:
                self.context = None

        # Then stop Playwright (note: call stop() on the Playwright instance)
        if self._playwright:
            try:
                await self._playwright.stop()
                logger.info("Playwright driver stopped.")
            finally:
                self._playwright = None

        # We don't actually need the context manager after start(), but clear it anyway
        self._playwright_context_manager = None

    def is_connected(self) -> bool:
        """
        Checks if the browser context is initialized.
        With launch_persistent_context, the context is the primary object.
        If it exists, we consider it 'connected'.
        """
        # CORRECTED: For launch_persistent_context, a non-None context is our indicator of being connected.
        return self.context is not None