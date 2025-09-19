import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Optional
from loguru import logger
from patchright.async_api import Page, expect

from .browser import Browser

DATE_RX = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")

def _parse_ru_date(s: str) -> Optional[datetime]:
    m = DATE_RX.search(s or "")
    if not m:
        return None
    try:
        # treat as naive date; compare as date only
        return datetime.strptime(m.group(1), "%d.%m.%Y")
    except ValueError:
        return None

async def is_disqualified_on(page: Page, name: str, date_str: str) -> bool:
    """
    Returns True if the given date falls within ANY of the 'Дата начала'/'Дата окончания'
    ranges found in valid 'prop prop--details' blocks on service.nalog.ru/disqualified.html.
    Inclusive comparison. If one date is missing -> open-ended interval.
    If no valid blocks found -> False.
    """
    target_date = datetime.strptime(date_str, "%d.%m.%Y")

    # 1) Open page and perform search
    await page.goto("https://service.nalog.ru/disqualified.html", wait_until="domcontentloaded")
    search_box = page.get_by_role("textbox", name="Введите ФИО ФЛ, наименование или ИНН ЮЛ")
    await search_box.click()
    await search_box.fill(name)
    await page.get_by_role("button", name="Найти").click()

    # Wait for either results to show or an empty-state; then proceed.
    # We wait for any .prop.prop--details to appear OR for the search area to settle.
    # (Short-circuit after a reasonable timeout.)
    try:
        await page.locator("div.prop.prop--details").first.wait_for(timeout=2000)
    except Exception:
        # No blocks at all => definitely False
        return False

    # 2) Collect valid detail blocks (ignore the plain text fluke block)
    blocks = page.locator("div.prop.prop--details")
    count = await blocks.count()

    valid_found = False
    for i in range(count):
        block = blocks.nth(i)

        # Ignore the fluke: it's exactly the plain text "Сведения о дисквалификации"
        raw_text = (await block.inner_text()).strip()
        if raw_text == "Сведения о дисквалификации":
            continue

        # Look for 'Дата начала' and 'Дата окончания' dd via adjacent sibling selector
        start_dd = block.locator('dt:has-text("Дата начала") + dd')
        end_dd   = block.locator('dt:has-text("Дата окончания") + dd')

        start_text = (await start_dd.inner_text()) if await start_dd.count() > 0 else ""
        end_text   = (await end_dd.inner_text()) if await end_dd.count() > 0 else ""

        start_dt = _parse_ru_date(start_text)
        end_dt   = _parse_ru_date(end_text)

        # keep only blocks that have at least one of the two dates
        if not start_dt and not end_dt:
            continue

        valid_found = True

        # Open-ended handling:
        #  - missing start => (-inf, end]
        #  - missing end   => [start, +inf)
        if start_dt is None:
            # effectively -inf
            in_range = target_date <= end_dt
        elif end_dt is None:
            # effectively +inf
            in_range = target_date >= start_dt
        else:
            in_range = (start_dt <= target_date <= end_dt)  # inclusive

        if in_range:
            return True

    # If we saw zero valid blocks (besides the fluke) -> False per spec
    if not valid_found:
        return False

    # Otherwise, none of the intervals covered the date
    return False





async def main(name: str, date_str: str):

    # Ensure log dir exists for the error writer below
    os.makedirs(os.path.join("data", "logs"), exist_ok=True)

    try:
        browser = Browser(headless=False, datadir="datadir")
        await browser.launch()

        try:
            # Use the persistent context provided by your wrapper
            page = await browser.context.new_page()
            result = await is_disqualified_on(page, name, date_str)
            print(f"Is '{name}' disqualified on {date_str}? {result}")
        finally:
            # Prefer the wrapper's close(); if the environment lacks .stop(), use a safe fallback
            try:
                await browser.close()
            except AttributeError as e:
                logger.warning(f"browser.close() raised {e!r}; attempting graceful fallback cleanup.")
                try:
                    if browser.context:
                        await browser.context.close()
                finally:
                    # If your wrapper had set _playwright, stop it directly when available
                    if getattr(browser, "_playwright", None):
                        await browser.close()

    except Exception as e:
        logger.exception(f"Unhandled exception in main execution: {e}")
        # Save error details to timestamped file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        error_filename = f"error_{timestamp}.log"
        error_path = os.path.join("data", "logs", error_filename)
        try:
            with open(error_path, "w", encoding="utf-8") as f:
                f.write(str(e))
        except Exception as write_err:
            logger.error(f"Failed writing error log to {error_path}: {write_err}")

if __name__ == "__main__":
    name = "МИРОНОВ РУСЛАН МАРСОВИЧ"
    date_str = "26.03.2025"
    asyncio.run(main(name, date_str))