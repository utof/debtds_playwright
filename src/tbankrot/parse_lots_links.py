#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import asyncio
import re
from datetime import datetime
from loguru import logger

from ..browser import Browser


# ---------------- IO helpers ----------------
def _atomic_write_json(data: dict, path: str):
    """Write JSON atomically to avoid corruption on crashes (path.tmp -> replace)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _save_progress(lots_by_url: dict[str, dict], path: str):
    """Prepare output structure and write it atomically."""
    lots_sorted = sorted(lots_by_url.values(), key=lambda x: x["url"])
    payload = {"count": len(lots_sorted), "lots": lots_sorted}
    _atomic_write_json(payload, path)
    logger.info(f"Progress saved: {payload['count']} lots -> {path}")


# ---------------- Scroll Helper ----------------
async def scroll_to_bottom(page, pause: float = 0.5, max_attempts: int = 20):
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
    try:
        selected = await page.locator("#pageItemCount option[selected]").inner_text()
        if selected.strip() == "100":
            return
        await page.select_option("#pageItemCount", "100")
        await page.wait_for_load_state("domcontentloaded")
    except Exception as e:
        logger.exception(f"ensure_page_size_100 failed: {e}")


async def get_total_pages(page) -> int:
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


def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def classify_inline_dates(text: str, titles: list[str]) -> str:
    """
    Text-first classifier (no date math).
    Priority:
      1) 'идут торги'
      2) 'осталось' => 'мало времени'
      3) 'приём заявок' (if not 'начало')
      4) 'начало' => 'ожидание начала'
      5) 'неизвестно'
    """
    t = (text or "").lower()
    joined_titles = " | ".join([x.lower() for x in titles if x])
    haystack = f"{t} || {joined_titles}"

    if "идут торги" in haystack:
        return "идут торги"
    if "осталось" in haystack:
        return "мало времени"

    has_priem = "приём заявок" in haystack or "прием заявок" in haystack
    has_nachalo = "начало" in haystack
    if has_priem and not has_nachalo:
        return "приём заявок"
    if has_nachalo:
        return "ожидание начала"

    return "неизвестно"


async def collect_lots_from_page(page) -> list[dict]:
    """
    Per `div.lot_container`:
      - url from `a.lot_num`
      - status from `.inline_dates`
      - snippet: text + any `title` attributes
    """
    lots: list[dict] = []
    try:
        await scroll_to_bottom(page)
        containers = page.locator("div.lot_container")
        total = await containers.count()

        for i in range(total):
            container = containers.nth(i)

            # URL
            href = None
            try:
                link = container.locator("a.lot_num").first
                if await link.count() > 0:
                    href = await link.get_attribute("href")
                    if href:
                        href = href.strip()
            except Exception:
                pass
            if not href:
                continue

            # Inline dates
            inline = container.locator("div.inline_dates").first
            inline_text = ""
            titles: list[str] = []
            if await inline.count() > 0:
                try:
                    inline_text = await inline.inner_text()
                except Exception:
                    inline_text = ""
                try:
                    with_titles = inline.locator("[title]")
                    n_titles = await with_titles.count()
                    for j in range(n_titles):
                        t = await with_titles.nth(j).get_attribute("title")
                        if t:
                            titles.append(t.strip())
                except Exception:
                    pass

            status = classify_inline_dates(inline_text, titles)

            lots.append(
                {
                    "url": href,
                    "status": status,
                    "snippet": {
                        "text": _normalize_space(inline_text),
                        "titles": titles,
                    },
                }
            )
    except Exception as e:
        logger.exception(f"collect_lots_from_page failed: {e}")

    return lots


# ---------------- Orchestrator ----------------
async def main(page, base_url: str, progress_path: str | None = None) -> dict:
    """
    Navigate, enforce 100 per page, loop all pages.
    After **each page**, save progress to `progress_path` (if provided) atomically.
    Return {"count": N, "lots": [...] } at the end.
    """
    lots_by_url: dict[str, dict] = {}

    def save_now():
        if progress_path:
            try:
                _save_progress(lots_by_url, progress_path)
            except Exception as e:
                logger.exception(f"Saving progress failed: {e}")

    try:
        await page.goto(base_url, wait_until="domcontentloaded")
        await ensure_page_size_100(page)
        total_pages = await get_total_pages(page)
        logger.info(f"Detected {total_pages} pages.")

        # Page 1
        page_lots = await collect_lots_from_page(page)
        for lot in page_lots:
            lots_by_url[lot["url"]] = lot
        save_now()

        # Remaining pages
        for p in range(2, total_pages + 1):
            try:
                url = f"{base_url}&page={p}" if "?" in base_url else f"{base_url}?page={p}"
                logger.info(f"Scraping page {p}/{total_pages}: {url}")
                await page.goto(url, wait_until="domcontentloaded")
                page_lots = await collect_lots_from_page(page)
                for lot in page_lots:
                    lots_by_url[lot["url"]] = lot
                save_now()
            except Exception as e:
                logger.exception(f"Failed on page {p}: {e}")
                save_now()  # save what we have even on failure
                continue

    except Exception as e:
        logger.exception(f"main routine failed: {e}")
        save_now()

    # Final payload
    lots_sorted = sorted(lots_by_url.values(), key=lambda x: x["url"])
    return {"count": len(lots_sorted), "lots": lots_sorted}


# ---------------- Standalone Runner ----------------
async def _run_once():
    test_url = (
        "https://tbankrot.ru/?page=1&sort=created&sort_order=desc&type_1=on"
        "&parent_cat[]=5&sub_cat[]=31&sub_cat[]=34&spec_search=1&show_period=all"
    )
    out_path = os.path.join("debug", "lot_statuses.json")
    os.makedirs("debug", exist_ok=True)

    browser = Browser(headless=False, datadir="datadir")
    data = {"count": 0, "lots": []}

    try:
        await browser.launch()
        page = await browser.context.new_page()
        data = await main(page, test_url, progress_path=out_path)
    except Exception as e:
        logger.exception(f"Unhandled exception in runner: {e}")
    finally:
        try:
            await browser.close()
        except Exception as e:
            logger.exception(f"Browser close failed: {e}")

    # Final save (overwrite with the final, sorted payload)
    _atomic_write_json(data, out_path)
    logger.info(f"Final write: {data['count']} lots -> {out_path}")


if __name__ == "__main__":
    asyncio.run(_run_once())
