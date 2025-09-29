#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Crawl catalog → collect lot links → parse each lot with caching.

- Catalog page: the given tbankrot URL
- Saves all links (deduped) to: debug/all_lots.json (overwrites)
- Cache (by lot id) at: cache/lots_cache.json (human-readable JSON)
"""

import os
import re
import json
import asyncio
import tempfile
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from loguru import logger

from .ai_request import update_debtor_data

from .parse_lots_links import main as parse_lots_links
from .parse_lot_data import parse_lot
from ..browser import Browser


CATALOG_URL = (
    "https://tbankrot.ru/?page=1&sort=created&sort_order=desc"
    "&type_1=on&parent_cat[]=5&sub_cat[]=31&sub_cat[]=34&spec_search=1&show_period=all"
)

CACHE_DIR = "cache"
CACHE_FILE = os.path.join(CACHE_DIR, "lots_cache.json")
DEBUG_DIR = "debug"
ALL_LINKS_FILE = os.path.join(DEBUG_DIR, "all_lots.json")


# ---------- Logging setup: per-run error file, console info ----------
def _setup_logging():
    os.makedirs("data/error_logs", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    err_file = f"data/error_logs/error_{ts}.log"
    logger.remove()
    logger.add(err_file, level="ERROR")
    logger.add(lambda m: print(m, end=""), level="INFO")  # mirror to console


# ---------- Utilities ----------
def _ensure_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(DEBUG_DIR, exist_ok=True)

def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            logger.error("Cache file is not a dict; starting with empty cache.")
            return {}
    except Exception as e:
        logger.exception(f"Failed to load cache: {e}")
        return {}

def _atomic_write_json(path: str, obj: object):
    # Write to tmp file then replace, to reduce risk of corruption
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=d, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        # If anything goes wrong, try a best-effort direct write as fallback
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
        except Exception as e2:
            logger.exception(f"Atomic write failed and fallback write failed: {e2}")
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass

def _save_all_links(links: list[str]):
    try:
        _atomic_write_json(ALL_LINKS_FILE, {"count": len(links), "links": links})
        logger.info(f"Saved {len(links)} links to {ALL_LINKS_FILE}")
    except Exception as e:
        logger.exception(f"Failed to save all links: {e}")

LOT_ID_RX = re.compile(r"[?&]id=(\d+)\b")

def _extract_lot_id(href: str) -> str | None:
    """
    Extracts lot id from:
      - /item?id=7177968
      - https://tbankrot.ru/item?id=7177968
    Returns id as string or None.
    """
    if not href:
        return None
    # Fast regex path
    m = LOT_ID_RX.search(href)
    if m:
        return m.group(1)
    # Robust parse as fallback
    try:
        q = urlparse(href).query
        id_vals = parse_qs(q).get("id")
        if id_vals and id_vals[0].isdigit():
            return id_vals[0]
    except Exception:
        pass
    return None

def _to_absolute_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    # assume relative to tbankrot.ru
    if not href.startswith("/"):
        href = "/" + href
    return f"https://tbankrot.ru{href}"


# ---------- Main Orchestration ----------
async def run():
    _setup_logging()
    _ensure_dirs()

    browser = Browser(headless=False, datadir="datadir")
    cache: dict = _load_cache()
    logger.info(f"Cache loaded: {len(cache)} entries")

    try:
        await browser.launch()
        page = await browser.context.new_page()

        # 1) Collect lot links
        links_result = {"count": 0, "links": []}
        try:
            links_result = await parse_lots_links(page, CATALOG_URL)
        except Exception as e:
            logger.exception(f"parse_lots_links failed: {e}")
        # Deduplicate and sort
        unique_links = sorted(set(links_result.get("links", [])))
        # Save all found links (overwrite each run)
        _save_all_links(unique_links)

        # 2) For each lot: check cache, else parse and update cache
        total = len(unique_links)
        for idx, href in enumerate(unique_links, start=1):
            lot_id = _extract_lot_id(href)
            if not lot_id:
                logger.error(f"[{idx}/{total}] Could not extract lot id from href: {href}")
                continue

            if lot_id in cache:
                logger.info(f"[{idx}/{total}] Lot {lot_id} in cache — skipping.")
                continue

            try:
                lot_url = _to_absolute_url(href)
                logger.info(f"[{idx}/{total}] Parsing lot {lot_id}: {lot_url}")
                await page.goto(lot_url, wait_until="domcontentloaded")
                data = await parse_lot(page)
                # Store under lot_id
                cache[lot_id] = {
                    "url": lot_url,
                    "parsed_at": datetime.now().isoformat(timespec="seconds"),
                    "data": data,
                }
                # Save cache after each successful lot
                _atomic_write_json(CACHE_FILE, cache)

                if not data.get("debtor_inn"):
                    try:
                        logger.info(f"[{idx}/{total}] Running AI enrichment for lot {lot_id}")
                        enriched = update_debtor_data(data)
                        cache[lot_id]["data"] = enriched
                        _atomic_write_json(CACHE_FILE, cache)
                        logger.info(f"[{idx}/{total}] AI enrichment done and saved for lot {lot_id}")
                    except Exception as e:
                        logger.exception(f"[{idx}/{total}] AI enrichment failed for lot {lot_id}: {e}")
                        # Do not overwrite raw parse; keep it as-is
                        continue
                    
            except Exception as e:
                logger.exception(f"[{idx}/{total}] Failed to parse lot {lot_id}: {e}")
                # Try to persist current cache even on failure
                try:
                    _atomic_write_json(CACHE_FILE, cache)
                except Exception as e2:
                    logger.exception(f"Cache save after failure also failed: {e2}")
                # Continue with next lot
                continue

    except Exception as e:
        logger.exception(f"Top-level run() failure: {e}")
        # Best-effort save of current cache
        try:
            _atomic_write_json(CACHE_FILE, cache)
        except Exception as e2:
            logger.exception(f"Cache save in top-level failure also failed: {e2}")
    finally:
        try:
            await browser.close()
        except Exception as e:
            logger.exception(f"Browser close failed: {e}")

    logger.info(f"Done. Cache entries: {len(cache)} → {CACHE_FILE}")


# ---------- CLI ----------
if __name__ == "__main__":
    asyncio.run(run())
