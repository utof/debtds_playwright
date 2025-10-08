import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.browser import Browser
from src.listorg.main import run


def _atomic_write_json(data: dict, path: Path | str):
    """Custom atomic write that handles Path objects and dict data."""
    if isinstance(path, Path):
        path_str = str(path)
    else:
        path_str = path

    os.makedirs(os.path.dirname(path_str), exist_ok=True)
    tmp = f"{path_str}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path_str)


def _load_json_safely(path: Path | str) -> dict:
    """Safely load JSON file, return empty dict if not exists or invalid."""
    path_str = str(path)
    if not os.path.exists(path_str):
        return {}
    try:
        with open(path_str, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load existing JSON '{path_str}': {e}")
        return {}


def _normalize_progress(existing_data: dict) -> tuple[dict, dict]:
    """
    Normalize existing data to standard schema:
    {"count": int, "items": [{"url": str, "success": bool, "error": str, "data": dict}]}
    Returns normalized payload and URL-to-index map.
    """
    items = existing_data.get("items", [])
    norm_items = []
    for item in items:
        if isinstance(item, dict) and "url" in item:
            # Ensure data has finances_data if success
            data = item.get("data", {})
            if item.get("success", False) and "finances_data" not in data:
                data["finances_data"] = {"error": "missing data"}
            norm_items.append({
                "url": item.get("url", ""),
                "success": bool(item.get("success", False)),
                "error": item.get("error", ""),
                "data": data
            })
    
    payload = {
        "count": len(norm_items),
        "items": norm_items
    }
    index = {it["url"]: i for i, it in enumerate(norm_items) if it.get("url")}
    return payload, index


def _upsert_item(progress: dict, index: dict, record: dict):
    """Upsert a record into progress by URL, updating count if new."""
    url = record.get("url", "")
    if not url:
        return
    if url in index:
        progress["items"][index[url]] = record
    else:
        progress["items"].append(record)
        index[url] = len(progress["items"]) - 1
        progress["count"] = len(progress["items"])


INPUT_FILE = Path("debug/lot_details_filtered_without_invalid_inn.json")
OUTPUT_FILE = Path("debug/lot_details_with_finances.json")

FINANCE_PARAMS = {
    "method": "finances",
    "years_filter": "2022:",
    "codes_filter": "1150,1170,1200,1210,1230,1240,1250,1300,1410,1500,1510,1520,1600,1700,2110,2200,2330"
}

INN_REGEX = re.compile(r'ИНН (\d{10})')

async def fetch_finances_for_inn(inn: str, context) -> Dict[str, Any]:
    """Fetch financial data for a given INN using listorg run function."""
    logging.info(f"Fetching finances for INN: {inn}")
    try:
        result = await run(context, inn, **FINANCE_PARAMS)
        return result
    except Exception as e:
        logging.error(f"Error fetching finances for INN {inn}: {e}")
        return {"error": str(e)}


async def process_lot(item: Dict[str, Any], context, skip_if_exists: bool = True) -> tuple[bool, str]:
    """
    Process a single lot: extract INN and fetch finances if needed.
    Returns (success: bool, error: str).
    """
    data = item.get("data", {})
    bankrupt_inn = data.get("bankrupt_inn", "")
    
    if not bankrupt_inn or bankrupt_inn.strip() == "":
        # Try to extract INN from announcement_text if bankrupt_inn is empty
        announcement_text = data.get("announcement_text", "")
        match = INN_REGEX.search(announcement_text)
        if not match:
            return False, "No INN found in announcement_text"
        inn = match.group(1)
    else:
        inn = bankrupt_inn.strip()
    
    # Skip if already has valid finances_data
    if skip_if_exists and "finances_data" in data and data["finances_data"] is not None:
        if isinstance(data["finances_data"], dict) and "error" not in data["finances_data"]:
            return True, ""  # Already successful
        elif data.get("success", False):
            return True, ""
    
    # Validate INN length
    inn_digits = re.sub(r'\D', '', inn)
    if len(inn_digits) not in (9, 10):
        data["finances_data"] = {"error": "ошибка: физлицо"}
        return False, "INN not 9 or 10 digits"
    
    # Fetch finances
    result = await fetch_finances_for_inn(inn, context)
    data["finances_data"] = result
    return True, ""


async def main() -> None:
    """Main function to process the batch with recovery mechanisms."""
    logging.basicConfig(level=logging.INFO)
    
    if not INPUT_FILE.exists():
        print(f"Input file {INPUT_FILE} does not exist.")
        return
    
    # Load input
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        input_data: Dict[str, Any] = json.load(f)
    
    input_items: List[Dict[str, Any]] = input_data.get("items", [])
    if not input_items:
        print("No items found in JSON.")
        return
    
    # Load and normalize existing output if exists
    existing_raw = _load_json_safely(OUTPUT_FILE)
    progress, url_index = _normalize_progress(existing_raw)
    
    # Merge input items with existing progress (add missing fields)
    items = []
    processed_count = 0
    skipped_count = 0
    for input_item in input_items:
        url = input_item.get("url", "")
        if not url:
            continue
        
        # Ensure standard structure
        record = {
            "url": url,
            "success": False,
            "error": "",
            "data": input_item.get("data", {})
        }
        
        if url in url_index:
            # Merge with existing
            existing_record = progress["items"][url_index[url]]
            record["success"] = existing_record.get("success", False)
            record["error"] = existing_record.get("error", "")
            record["data"].update(existing_record.get("data", {}))
        
        items.append(record)
        
        if record["success"]:
            skipped_count += 1
        else:
            processed_count += 1
    
    logging.info(f"Loaded {len(items)} items: {skipped_count} skipped (existing success), {processed_count} to process")
    
    # Launch browser
    browser = Browser(headless=False, datadir="datadir")
    await browser.launch()

    try:
        # Process items that need processing
        for i, item in enumerate(items):
            url = item["url"]
            if item["success"]:
                print(f"Skipping lot {i + 1}/{len(items)} (already processed): {url}")
                continue
            
            print(f"Processing lot {i + 1}/{len(items)}: {url}")
            
            success, error_msg = await process_lot(item, browser.context)
            
            if success:
                item["success"] = True
                item["error"] = ""
                logging.info(f"Successfully processed: {url}")
            else:
                item["success"] = False
                item["error"] = error_msg
                item["data"]["finances_data"] = {"error": error_msg} if "finances_data" not in item["data"] else item["data"]["finances_data"]
                logging.error(f"Error processing {url}: {error_msg}")
            
            # Upsert and atomic save after each item
            _upsert_item({"count": len(items), "items": items}, url_index, item)
            _atomic_write_json({"count": len(items), "items": items}, OUTPUT_FILE)
        
        print(f"Batch processing complete. Output saved to {OUTPUT_FILE}")

    finally:
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())