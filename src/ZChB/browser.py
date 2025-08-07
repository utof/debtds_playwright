from contextlib import contextmanager
from typing import Iterator, Optional
from .config import HEADLESS, DEFAULT_TIMEOUT_MS
# from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from patchright.sync_api import sync_playwright, Browser, BrowserContext, Page

@contextmanager
def playwright_session(headless: Optional[bool] = None) -> Iterator[tuple[Browser, BrowserContext, Page]]:
    """
    Context manager that launches Playwright Chromium and yields (browser, context, page).
    Ensures cleanup even if exceptions occur.
    """
    if headless is None:
        headless = HEADLESS
    with sync_playwright() as p:
        browser: Browser = p.chromium.launch_persistent_context(headless=headless, channel="chrome", no_viewport=True, user_data_dir="datadir")
        # context: BrowserContext = browser.new_context()
        page: Page = browser.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            yield browser, page
        finally:
            try:
                browser.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass