# src/companium/status_scraper.py
import asyncio
from typing import Optional

from ..browser import Browser  # your wrapper
from patchright.async_api import Page  # or "from playwright.async_api import Page" if that’s what Browser uses


SEARCH_TIPS_URL = "https://companium.ru/search/tips?query="
BASE_URL = "https://companium.ru"


async def get_company_status(page: Page, inn: str) -> Optional[str]:
    """
    Navigate via companium search tips for a given INN and extract ONLY the company status.

    Returns:
        str | None: e.g. "Действующая", "Ликвидирована", or None if not found.
    """
    # Home first (helps ensure cookies/UI context). Wait for DOMContentLoaded.
    await page.goto(BASE_URL, wait_until="domcontentloaded")

    # Try the same JSON endpoint you used previously to get the first result's link.
    href = await page.evaluate(
        """async ({ baseUrl, inn }) => {
            try {
                const resp = await fetch(baseUrl + encodeURIComponent(inn), { credentials: 'include' });
                if (!resp.ok) return null;
                const data = await resp.json();
                if (!Array.isArray(data) || data.length === 0) return null;
                const content = data[0]?.content || '';
                const m = content.match(/href="([^"]+)"/);
                return m ? m[1] : null;
            } catch (_) {
                return null;
            }
        }""",
        {"baseUrl": SEARCH_TIPS_URL, "inn": inn},
    )

    if href:
        await page.goto(f"{BASE_URL}{href}", wait_until="domcontentloaded")
    else:
        # Fallback: use the site search UI — fill and press Enter, click the first company link.
        # Use broad, resilient selectors.
        search_input = page.locator(
            'input[type="search"], input[name="query"], input[placeholder*="Поиск"]'
        ).first
        await search_input.fill(inn)
        await search_input.press("Enter")
        await page.wait_for_load_state("domcontentloaded")

        first_result = page.locator('a.link-black[href^="/company"]').first
        if await first_result.count() == 0:
            return None
        await first_result.click()
        await page.wait_for_load_state("domcontentloaded")

    # Extract ONLY the status. Try green, red, then special-status.
    for sel in (
        "div.text-success.fw-bold",
        "div.text-danger.fw-bold",
        "div.fw-bold.special-status",
    ):
        loc = page.locator(sel).first
        if await loc.count() > 0:
            txt = (await loc.inner_text()).strip()
            if txt:
                return txt

    return None


# --- tiny demo runner (optional) ---
async def _demo():
    browser = Browser(headless=False, datadir="datadir")
    await browser.launch()
    page = await browser.context.new_page()
    try:
        status = await get_company_status(page, "7728168971")  # sample INN
        print("STATUS:", status)
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(_demo())
