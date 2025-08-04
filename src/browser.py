from contextlib import contextmanager
from typing import Iterator, Optional
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from .config import HEADLESS, DEFAULT_TIMEOUT_MS

@contextmanager
def playwright_session(headless: Optional[bool] = None) -> Iterator[tuple[Browser, BrowserContext, Page]]:
    """
    Context manager that launches Playwright Chromium and yields (browser, context, page).
    Ensures cleanup even if exceptions occur.
    """
    if headless is None:
        headless = HEADLESS
    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=headless)
        context: BrowserContext = browser.new_context()
        page: Page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            yield browser, context, page
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass