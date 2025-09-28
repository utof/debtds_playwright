#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import asyncio
from datetime import datetime
from loguru import logger

from ..browser import Browser


# ---------------- Scroll Helper ----------------
async def scroll_to_bottom(page, pause: float = 0.5, max_attempts: int = 20):
    """
    Simulates natural scrolling until the bottom of the page is reached.
    Stops when document.body.scrollHeight stops increasing.
    """
    try:
        last_height = await page.evaluate("() => document.body.scrollHeight")
        stable_rounds = 0

        for _ in range(max_attempts):
            await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(pause)
            new_height = await page.evaluate("() => document.body.scrollHeight")
            if new_height == last_height:
                stable_rounds += 1
                if stable_rounds >= 2:
                    break
            else:
                stable_rounds = 0
            last_height = new_height

    except Exception as e:
        logger.exception(f"scroll_to_bottom failed: {e}")


# ---------------- Extractors ----------------
async def ensure_page_size_100(page):
    """Ensure select#pageItemCount is set to 100; reload if needed."""
    try:
        selected = await page.locator("#pageItemCount option[selected]").inner_text()
        if selected.strip() == "100":
            return
        await page.select_option("#pageItemCount", "100")
        await page.wait_for_load_state("domcontentloaded")
    except Exception as e:
        logger.exception(f"ensure_page_size_100 failed: {e}")


async def get_total_pages(page) -> int:
    """Return number of pages from .pages > ul > li > a (last link)."""
    try:
        pages = page.locator("div.pages ul li a")
        count = await pages.count()
        if count == 0:
            return 1
        last_text = await pages.nth(count - 1).inner_text()
        return int(last_text.strip())
    except Exception as e:
        logger.exception(f"get_total_pages failed: {e}")
        return 1


async def collect_links_from_page(page) -> set[str]:
    """Extract all lot links from a single page."""
    links = set()
    try:
        await scroll_to_bottom(page)
        anchors = page.locator("a.lot_num")
        count = await anchors.count()
        for i in range(count):
            href = await anchors.nth(i).get_attribute("href")
            if href:
                links.add(href.strip())
    except Exception as e:
        logger.exception(f"collect_links_from_page failed: {e}")
    return links


# ---------------- Orchestrator ----------------
async def main(page, base_url: str) -> dict:
    """
    Main routine: navigate, enforce 100 items/page, loop through all pages,
    collect lot_num links, return {"count": N, "links": [...] }.
    """
    all_links: set[str] = set()
    try:
        await page.goto(base_url, wait_until="domcontentloaded")
        await ensure_page_size_100(page)
        total_pages = await get_total_pages(page)
        logger.info(f"Detected {total_pages} pages.")
        page_links = await collect_links_from_page(page)
        all_links.update(page_links)


        for p in range(2, total_pages + 1):
            try:
                url = f"{base_url}&page={p}" if "?" in base_url else f"{base_url}?page={p}"
                logger.info(f"Scraping page {p}/{total_pages}: {url}")
                await page.goto(url, wait_until="domcontentloaded")
                page_links = await collect_links_from_page(page)
                all_links.update(page_links)
            except Exception as e:
                logger.exception(f"Failed on page {p}: {e}")
                continue

    except Exception as e:
        logger.exception(f"main routine failed: {e}")

    return {"count": len(all_links), "links": sorted(all_links)}


# ---------------- Standalone Runner ----------------
async def _run_once():
    test_url = "https://tbankrot.ru/?page=1&sort=created&sort_order=desc&type_1=on&parent_cat[]=5&sub_cat[]=31&sub_cat[]=34&spec_search=1&show_period=all"  # example base
    out_path = os.path.join("debug", "lot_links.json")
    os.makedirs("debug", exist_ok=True)

    browser = Browser(headless=False, datadir="datadir")
    data = {"count": 0, "links": []}

    try:
        await browser.launch()
        page = await browser.context.new_page()
        data = await main(page, test_url)
    except Exception as e:
        logger.exception(f"Unhandled exception in runner: {e}")
    finally:
        try:
            await browser.close()
        except Exception as e:
            logger.exception(f"Browser close failed: {e}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Wrote {len(data['links'])} links to {out_path}")


if __name__ == "__main__":
    asyncio.run(_run_once())
