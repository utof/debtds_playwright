import asyncio
import json
import logging
import os
import re
import time
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

    max_retries = 3
    retry_delay = 2  # seconds
    for attempt in range(max_retries):
        try:
            os.replace(tmp, path_str)
            logging.info(
                f"Successfully wrote JSON to {path_str} on attempt {attempt + 1}"
            )
            return
        except PermissionError as e:
            if attempt < max_retries - 1:
                logging.warning(
                    f"PermissionError on attempt {attempt + 1}/{max_retries} for {path_str}: {e}. Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)
            else:
                logging.error(
                    f"Failed to replace {tmp} with {path_str} after {max_retries} attempts: {e}. Falling back to direct write."
                )
                # Fallback: direct write (less atomic but should work)
                try:
                    with open(path_str, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    logging.info(f"Fallback direct write successful for {path_str}")
                    # Clean up tmp
                    os.remove(tmp)
                except Exception as fallback_e:
                    logging.error(
                        f"Fallback write also failed for {path_str}: {fallback_e}. Tmp file left at {tmp}"
                    )
                    raise
                break
        except Exception as e:
            logging.error(f"Unexpected error during replace for {path_str}: {e}")
            raise
    # Clean up tmp if it still exists after successful replace (edge case)
    if os.path.exists(tmp):
        os.remove(tmp)


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
    {"count": int, "items": [{"url": str, "status": str, "error": str, "data": dict}]}
    Returns normalized payload and URL-to-index map.
    """
    items = existing_data.get("items", [])
    norm_items = []
    for item in items:
        if isinstance(item, dict) and "url" in item:
            # Ensure data has finances_data if success
            data = item.get("data", {})
            if item.get("status") == "success" and "finances_data" not in data:
                data["finances_data"] = {"error": "missing data"}
            norm_items.append(
                {
                    "url": item.get("url", ""),
                    "status": item.get(
                        "status", "error" if item.get("error") else "new"
                    ),
                    "error": item.get("error", ""),
                    "data": data,
                }
            )
    
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
        elif data.get("status", "") == "success":
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

    # Separate items: errors first, then new
    error_items = []
    new_items = []
    skipped_count = 0
    for input_item in input_items:
        url = input_item.get("url", "")
        if not url:
            continue
        
        # Ensure standard structure
        record = {
            "url": url,
            "status": "error",
            "error": "",
            "data": input_item.get("data", {}),
        }
        
        if url in url_index:
            # Merge with existing
            existing_record = progress["items"][url_index[url]]
            record["status"] = existing_record.get("status", "error")
            record["error"] = existing_record.get("error", "")
            record["data"].update(existing_record.get("data", {}))

        if record["status"] == "success":
            skipped_count += 1
            continue

        if record["status"] == "error":
            error_items.append(record)
        else:
            new_items.append(record)

    all_items = error_items + new_items
    error_count = len(error_items)
    new_count = len(new_items)
    logging.info(
        f"Loaded {len(all_items)} items to process: {skipped_count} skipped (success), {error_count} errors to retry, {new_count} new"
    )

    if not all_items:
        print("No items to process.")
        return
    
    # Launch browser
    browser = Browser(headless=False, datadir="datadir")
    await browser.launch()

    try:
        # Process items (errors first)
        for i, item in enumerate(all_items):
            url = item["url"]
            is_error_retry = i < error_count
            print(
                f"Processing {'error retry' if is_error_retry else 'new'} lot {i + 1}/{len(all_items)}: {url}"
            )
            
            success, error_msg = await process_lot(item, browser.context)
            
            if success:
                item["status"] = "success"
                item["error"] = ""
                logging.info(f"Successfully processed: {url}")
            else:
                item["status"] = "error"
                item["error"] = error_msg
                if "finances_data" not in item["data"]:
                    item["data"]["finances_data"] = {"error": error_msg}
                logging.error(f"Error processing {url}: {error_msg}")
            
            # Upsert and atomic save after each item
            _upsert_item({"count": len(all_items), "items": all_items}, url_index, item)
            _atomic_write_json(
                {"count": len(all_items), "items": all_items}, OUTPUT_FILE
            )
        
        print(f"Batch processing complete. Output saved to {OUTPUT_FILE}")

    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())