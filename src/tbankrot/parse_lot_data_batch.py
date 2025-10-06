# ---------- Batch harvester: resume + incremental save ----------
from urllib.parse import urljoin
from typing import List
import os
import asyncio
import json
from patchright.async_api import Page  # or "from playwright.async_api import Page" if that’s what Browser uses
from .parse_lot_data import parse_lot
from ..browser import Browser  # your wrapper
from loguru import logger

def _atomic_write_json(data: dict, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def _load_json_safely(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.exception(f"Failed to load existing JSON '{path}': {e}")
        return {}

def _extract_urls_from_index(index_payload: dict) -> List[str]:
    """
    Accepts either:
      {"links": ["/item?id=..."]}
      or
      {"lots": [{"url": "/item?id=..."}]}
    Returns a de-duplicated, sorted list of relative/absolute URLs.
    """
    urls = []
    if isinstance(index_payload, dict):
        if isinstance(index_payload.get("links"), list):
            urls.extend([u for u in index_payload["links"] if isinstance(u, str)])
        if isinstance(index_payload.get("lots"), list):
            for item in index_payload["lots"]:
                if isinstance(item, dict) and isinstance(item.get("url"), str):
                    urls.append(item["url"])
    # Dedup + stabilize order
    return sorted(set(urls))

def _normalize_progress(progress_payload: dict) -> dict:
    """
    Normalize progress JSON to:
    {
      "count": int,
      "items": [
        { "url": str, "success": bool, "error": str|"", "data": {...} }
      ]
    }
    Also return an index map for fast lookups.
    """
    items = []
    if isinstance(progress_payload.get("items"), list):
        items = progress_payload["items"]
    elif isinstance(progress_payload.get("lots"), list):
        # Backward-compat if earlier name used
        items = progress_payload["lots"]
    else:
        items = []

    # Ensure all entries have required fields
    norm_items = []
    for it in items:
        if not isinstance(it, dict) or "url" not in it:
            continue
        norm_items.append({
            "url": it.get("url", ""),
            "success": bool(it.get("success", False)),
            "error": it.get("error", ""),
            "data": it.get("data", None),
        })

    payload = {
        "count": len(norm_items),
        "items": norm_items
    }

    index = { it["url"]: i for i, it in enumerate(norm_items) if it.get("url") }
    return payload, index

def _upsert_item(progress_payload: dict, index: dict, record: dict):
    """
    record = { "url": str, "success": bool, "error": str, "data": dict|None }
    """
    url = record.get("url", "")
    if not url:
        return
    if url in index:
        progress_payload["items"][index[url]] = record
    else:
        progress_payload["items"].append(record)
        index[url] = len(progress_payload["items"]) - 1
        progress_payload["count"] = len(progress_payload["items"])

async def harvest_from_index(
    list_json_path: str,
    output_path: str,
    base_url: str = "https://tbankrot.ru",
    headless: bool = False,
    sleep_between: float = 0.0,
):
    """
    - Load the index file that contains links/lots (produced by your list scraper).
    - Incrementally parse each lot page using parse_lot(page).
    - Save progress atomically after EACH lot.
    - Resume on reruns: skip entries with success=True in output JSON.

    Output schema:
    {
      "count": N,
      "items": [
        {
          "url": "/item?id=123",
          "success": true|false,
          "error": "",
          "data": { ... result of parse_lot(...) ... }  # only when success
        },
        ...
      ]
    }
    """
    # 1) Load index (list of URLs to process)
    index_payload = _load_json_safely(list_json_path)
    target_urls = _extract_urls_from_index(index_payload)
    logger.info(f"Index contains {len(target_urls)} lot URLs to process.")

    # 2) Load existing progress (for resume)
    progress_raw = _load_json_safely(output_path)
    progress, p_index = _normalize_progress(progress_raw)
    logger.info(f"Loaded progress: {progress['count']} items recorded; "
                f"{sum(1 for it in progress['items'] if it.get('success'))} successful.")

    if not target_urls:
        # Still save normalized payload (may just be what's already there)
        _atomic_write_json(progress, output_path)
        logger.info(f"No targets; wrote progress to {output_path}")
        return progress

    # 3) Launch browser once, reuse the page
    browser = None
    page = None
    try:
        browser = Browser(headless=headless, datadir="datadir")
        await browser.launch()
        page = await browser.context.new_page()

        for idx, rel_or_abs in enumerate(target_urls, 1):
            # Skip already successful
            rec_existing = progress["items"][p_index[rel_or_abs]] if rel_or_abs in p_index else None
            if rec_existing and rec_existing.get("success"):
                logger.info(f"[{idx}/{len(target_urls)}] Skip (already success): {rel_or_abs}")
                continue

            url = urljoin(base_url, rel_or_abs)
            logger.info(f"[{idx}/{len(target_urls)}] Parsing: {url}")

            record = {
                "url": rel_or_abs,
                "success": False,
                "error": "",
                "data": None,
            }

            try:
                await page.goto(url, wait_until="domcontentloaded")
                parsed = await parse_lot(page)  # uses your existing extractor pipeline
                record["data"] = parsed
                record["success"] = True
                record["error"] = ""
                logger.info(f"OK: {rel_or_abs}")
            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}"
                record["success"] = False
                record["error"] = err_msg
                record["data"] = None
                logger.exception(f"Failed to parse {rel_or_abs}: {e}")

            # Upsert + incremental save
            _upsert_item(progress, p_index, record)
            _atomic_write_json(progress, output_path)

            if sleep_between > 0:
                await asyncio.sleep(sleep_between)

    except Exception as e:
        logger.exception(f"Harvester fatal error: {e}")
    finally:
        if browser:
            try:
                await browser.close()
            except Exception as e:
                logger.exception(f"Browser close failed: {e}")

    # Final write (already incremental, but ensure final snapshot)
    _atomic_write_json(progress, output_path)
    logger.info(f"Harvest complete: {progress['count']} items -> {output_path}")
    return progress


# ---------- CLI example for batch mode ----------
async def _run_batch():
    """
    Example usage:
      - list_json_path: produced by your "status" scraper (e.g., debug/lot_statuses.json)
      - output_path: progress file (reruns will resume using the same file)
    """
    list_json_path = os.path.join("debug", "lot_statuses.json")   # input with URLs
    output_path    = os.path.join("debug", "lot_details.json")    # incremental progress output

    await harvest_from_index(
        list_json_path=list_json_path,
        output_path=output_path,
        base_url="https://tbankrot.ru",
        headless=False,
        sleep_between=0.0,  # add a pause if rate-limiting is needed
    )


# Allow running batch from CLI:
#   python this_file.py --batch
if __name__ == "__main__":
    import sys
    if "--batch" in sys.argv:
        asyncio.run(_run_batch())
