import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.browser import Browser
from src.listorg.main import run


def _is_valid_inn(inn_string: str) -> bool:
    """Validate if a string is a valid INN (9 or 10 digits)."""
    if not isinstance(inn_string, str):
        return False
    # Trim whitespace
    inn_string = inn_string.strip()

    # Check if the string contains ONLY 9 or 10 digits, nothing else.
    return bool(re.fullmatch(r"^\d{9,10}$", inn_string))


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
        # Find the actual index in current items list
        current_items = progress["items"]
        current_index = None
        for j, it in enumerate(current_items):
            if it.get("url") == url:
                current_index = j
                break
        if current_index is not None:
            current_items[current_index] = record
    else:
        progress["items"].append(record)
        index[url] = len(progress["items"]) - 1
        progress["count"] = len(progress["items"])


INPUT_FILE = Path("debug/lot_details_with_inn_ogrn_check.json")
OUTPUT_FILE = Path("debug/lot_details_with_finances2.json")

FINANCE_PARAMS = {
    "method": "finances",
    "years_filter": "2022:",
    "codes_filter": "1150,1170,1200,1210,1230,1240,1250,1300,1410,1500,1510,1520,1600,1700,2110,2200,2330"
}

INN_REGEX = re.compile(r'ИНН (\d{10})')

async def fetch_finances_for_inn(inn: str, browser: Browser) -> Dict[str, Any]:
    """Fetch financial data for a given INN using listorg run function."""
    logging.info(f"Fetching finances for INN: {inn}")
    try:
        # The `run` function now expects the custom Browser object
        result = await run(browser, inn, **FINANCE_PARAMS)
        return result
    except Exception as e:
        logging.error(f"Error fetching finances for INN {inn}: {e}")
        return {"error": str(e)}


async def process_lot(
    item: Dict[str, Any], browser: Browser, skip_if_exists: bool = True
) -> tuple[bool, str, bool]:
    """
    Process a single lot: extract INN and fetch finances if needed.
    Returns (success: bool, error: str, used_browser: bool).
    """
    data = item.get("data", {})

    # Add skip conditions before any INN extraction or fetching
    if (
        data.get("individuals") == "физлицо"
        or data.get("empty_individuals_but_no_inn_orgn") == True
        or data.get("empty_inn_but_nonempty_orgn") == True
    ):
        data["finances_data"] = {}
        return True, "", False  # No browser used

    # Change from bankrupt_inn to debtor_inn array
    debtor_inn = data.get("debtor_inn", [])

    valid_inns: list[str] = []

    # Process all INNs in debtor_inn array
    if debtor_inn and isinstance(debtor_inn, list) and len(debtor_inn) > 0:
        for potential_inn in debtor_inn:
            if _is_valid_inn(potential_inn):
                valid_inns.append(potential_inn.strip())


    # If no valid INNs found, set empty finances_data and return success
    if not valid_inns:
        data["finances_data"] = {}
        return True, "", False  # No browser used

    # Updated skip_if_exists check for dict format
    if (
        skip_if_exists
        and "finances_data" in data
        and isinstance(data["finances_data"], dict)
        and len(data["finances_data"]) > 0
    ):
        has_success = False
        for inn_key, result in data["finances_data"].items():
            # Check if this result is valid (no explicit error)
            # Success means having "financials" key (even if empty) without "error"
            if (
                isinstance(result, dict)
                and "financials" in result
                and "error" not in result
            ):
                has_success = True
                break
        if has_success:
            return True, "", False  # Already has data, no browser used

    # Fetch finances for ALL valid INNs
    finances_results = {}
    overall_success = False
    
    for inn in valid_inns:
        # The new Browser object handles retries and proxy switching internally
        result = await fetch_finances_for_inn(inn, browser)

        # Check if result is valid (has financials key without error)
        # Success means having "financials" key (even if empty) without explicit error
        if (
            isinstance(result, dict)
            and "financials" in result
            and "error" not in result
        ):
            # Success - valid financial data (even if empty)
            finances_results[inn] = result
            overall_success = True
            logging.info(f"Successfully fetched finances for INN {inn}")
        elif "error" in result:
            # Explicit error
            error_msg = str(result["error"])
            finances_results[inn] = {"error": error_msg}
            logging.error(f"Error for INN {inn}: {error_msg}")
        else:
            # No financials and no error - treat as error
            finances_results[inn] = {"error": "No financial data returned"}
            logging.error(f"No financial data returned for INN {inn}")

    # Set finances_data as dict with INN keys
    data["finances_data"] = finances_results

    # Return success only if we had at least one successful fetch with actual data
    if overall_success:
        return True, "", True  # Browser was used
    else:
        # All attempts failed - mark as error
        error_summary = (
            "All finance fetches failed - no valid financial data retrieved."
        )
        return False, error_summary, True  # Browser was used


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

    # Start with ALL existing items to preserve progress
    all_items = progress["items"].copy()

    # Track items that need processing
    items_to_process = []
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
            # Merge with existing data
            existing_record = progress["items"][url_index[url]]
            record["status"] = existing_record.get("status", "error")
            record["error"] = existing_record.get("error", "")
            record["data"].update(existing_record.get("data", {}))

            # Update the record in all_items
            if url_index[url] < len(all_items):
                all_items[url_index[url]] = record
        else:
            # New item - add to all_items
            all_items.append(record)
            url_index[url] = len(all_items) - 1

        # Check if this item needs processing
        # Skip only if status is "success" AND finances_data contains valid financial data
        if record["status"] == "success":
            # Validate that success items actually have valid financial data
            finances_data = record.get("data", {}).get("finances_data", {})
            has_valid_data = False

            if isinstance(finances_data, dict):
                for inn_key, result in finances_data.items():
                    if (
                        isinstance(result, dict)
                        and "financials" in result
                        and "error" not in result
                    ):
                        has_valid_data = True
                        break

            if has_valid_data:
                skipped_count += 1
            else:
                # Mark as error - success status but no valid data
                record["status"] = "error"
                record["error"] = "Success status but no valid financial data"
                items_to_process.append(record)
                logging.warning(
                    f"Re-processing {record['url']}: marked success but has no valid financial data"
                )
        else:
            items_to_process.append(record)

    # Separate items to process: errors first, then new
    error_items = [item for item in items_to_process if item["status"] == "error"]
    new_items = [item for item in items_to_process if item["status"] != "error"]
    items_to_process = error_items + new_items

    error_count = len(error_items)
    new_count = len(new_items)
    logging.info(
        f"Loaded {len(all_items)} total items: {skipped_count} skipped (success), {error_count} errors to retry, {new_count} new"
    )

    if not items_to_process:
        print("No items to process.")
        return

    # Launch browser
    browser = Browser(headless=False, datadir="datadir")
    await browser.launch()

    try:
        # Track accumulated lots for batched saving
        accumulated_lots: List[str] = []
        browser_used_count: int = 0
        no_browser_count: int = 0
        
        # Process items that need work (errors first, then new)
        for i, item in enumerate(items_to_process):
            url = item["url"]
            is_error_retry = i < error_count
            print(
                f"Processing {'error retry' if is_error_retry else 'new'} lot {i + 1}/{len(items_to_process)}: {url}"
            )

            success, error_msg, used_browser = await process_lot(item, browser)
            
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

            # Update the item in all_items
            _upsert_item({"count": len(all_items), "items": all_items}, url_index, item)
            
            # Accumulate this lot
            accumulated_lots.append(url)
            
            if used_browser:
                browser_used_count += 1
                # Save all accumulated lots when browser was used
                logging.info(f"Browser used - saving {len(accumulated_lots)} accumulated lot(s)")
                _atomic_write_json(
                    {"count": len(all_items), "items": all_items}, OUTPUT_FILE
                )
                accumulated_lots = []  # Reset accumulator
            else:
                no_browser_count += 1
                logging.info(f"No browser used - accumulated {len(accumulated_lots)} lot(s) for next save")
        
        # Save any remaining accumulated lots at the end
        if accumulated_lots:
            logging.info(f"Final save - saving {len(accumulated_lots)} remaining accumulated lot(s)")
            _atomic_write_json(
                {"count": len(all_items), "items": all_items}, OUTPUT_FILE
            )
        
        print(f"Batch processing complete. Browser used: {browser_used_count}, No browser: {no_browser_count}")
        print(f"Output saved to {OUTPUT_FILE}")

    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())