#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from typing import Any, Dict

from loguru import logger

from .ai_request import update_debtor_data, update_debtor_flags

INPUT_FILE = "debug/lot_details_enriched.json"
OUTPUT_FILE = "debug/lot_details_full_ai.json"

# Configuration - set to True/False to enable/disable each step
RUN_STEP_1 = False  # update_debtor_data (debtor_name, inn, ogrn, etc.)
RUN_STEP_2 = True  # update_debtor_flags (foreign_debtor_flag, individuals)


def load_json(path: str) -> Dict[str, Any]:
    """Load JSON file with error handling."""
    if not os.path.exists(path):
        logger.error(f"Input file not found: {path}")
        return {"count": 0, "items": []}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.exception(f"Failed to load {path}: {e}")
        return {"count": 0, "items": []}

def save_json(data: Dict[str, Any], path: str):
    """Save JSON atomically to avoid corruption."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        logger.info(f"Saved {len(data.get('items', []))} items to {path}")
    except Exception as e:
        logger.exception(f"Failed to save {path}: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)

def has_step1_data(lot: Dict[str, Any]) -> bool:
    """Check if lot already has step 1 data (debtor_name)."""
    data = lot.get("data", {})
    debtor_names = data.get("debtor_name", [])
    return bool(debtor_names)  # Non-empty list means step 1 already processed


def has_step2_data(lot: Dict[str, Any]) -> bool:
    """Check if lot already has step 2 data (foreign_debtor_flag and individuals)."""
    data = lot.get("data", {})
    return "foreign_debtor_flag" in data and "individuals" in data


def process_step1(lot: Dict[str, Any]) -> Dict[str, Any]:
    """Step 1: Process debtor data extraction if announcement_text is non-empty."""
    data = lot.get("data", {})
    announcement_text = data.get("announcement_text", "").strip()
    
    if not announcement_text:
        # Ensure empty lists for empty announcement
        for key in ["debtor_name", "debtor_inn", "debtor_ogrn", "case_number", "nominal_debt"]:
            if key not in data:
                data[key] = []
        return lot
    
    # Call AI to enrich data
    try:
        enriched_data = update_debtor_data(data)
        lot["data"] = enriched_data
        debtor_count = len(enriched_data.get("debtor_name", []))
        logger.info(
            f"Step 1 - Processed lot {lot['url']}: extracted {debtor_count} debtor names"
        )
    except Exception as e:
        logger.exception(f"Step 1 - Failed to process lot {lot['url']}: {e}")
        # Ensure empty lists even on error
        for key in ["debtor_name", "debtor_inn", "debtor_ogrn", "case_number", "nominal_debt"]:
            if key not in data:
                data[key] = []
    
    return lot

def process_step2(lot: Dict[str, Any]) -> Dict[str, Any]:
    """Step 2: Process debtor flags classification."""
    data = lot.get("data", {})

    # Ensure defaults if not present
    if "foreign_debtor_flag" not in data:
        data["foreign_debtor_flag"] = 0
    if "individuals" not in data:
        data["individuals"] = ""

    announcement_text = data.get("announcement_text", "").strip()
    if not announcement_text:
        logger.debug(f"Step 2 - Skipping empty announcement for {lot['url']}")
        return lot

    # Call AI to classify flags
    try:
        enriched_data = update_debtor_flags(data)
        lot["data"] = enriched_data
        foreign_flag = enriched_data.get("foreign_debtor_flag", 0)
        individuals = enriched_data.get("individuals", "")
        logger.info(
            f"Step 2 - Processed lot {lot['url']}: foreign_flag={foreign_flag}, individuals={individuals}"
        )
    except Exception as e:
        logger.exception(f"Step 2 - Failed to process lot {lot['url']}: {e}")
        # Keep defaults even on error

    return lot


def process_lot(lot: Dict[str, Any]) -> Dict[str, Any]:
    """Process single lot based on enabled steps."""
    processed = False

    if RUN_STEP_1:
        lot = process_step1(lot)
        processed = True

    if RUN_STEP_2:
        lot = process_step2(lot)
        processed = True

    if not processed:
        logger.warning("No steps enabled - nothing to process")

    return lot


def main():
    """Main processing function with incremental updates."""
    # Validate configuration
    if not RUN_STEP_1 and not RUN_STEP_2:
        logger.error("No steps enabled! Set RUN_STEP_1=True or RUN_STEP_2=True")
        return

    steps_enabled = []
    if RUN_STEP_1:
        steps_enabled.append("Step 1 (debtor_data)")
    if RUN_STEP_2:
        steps_enabled.append("Step 2 (debtor_flags)")

    logger.info(
        f"Starting enrichment: steps={steps_enabled}, input={INPUT_FILE}, output={OUTPUT_FILE}"
    )
    
    # Load input data
    input_data = load_json(INPUT_FILE)
    items = input_data.get("items", [])
    total_items = len(items)
    logger.info(f"Loaded {total_items} lots from input")
    
    if total_items == 0:
        logger.warning("No items to process")
        return

    # Initialize variables
    existing_items = []
    processed_urls_step1 = set()
    processed_urls_step2 = set()

    # Load existing output if it exists
    if os.path.exists(OUTPUT_FILE):
        output_data = load_json(OUTPUT_FILE)
        existing_items = output_data.get("items", [])

        # Track which URLs already have data for each step
        for item in existing_items:
            if RUN_STEP_1 and has_step1_data(item):
                processed_urls_step1.add(item["url"])
            if RUN_STEP_2 and has_step2_data(item):
                processed_urls_step2.add(item["url"])

        logger.info(f"Found existing output with {len(existing_items)} items")
    else:
        logger.info("No existing output file found - starting fresh")

    if RUN_STEP_1:
        logger.info(f"  - Step 1: {len(processed_urls_step1)} lots already processed")
    if RUN_STEP_2:
        logger.info(f"  - Step 2: {len(processed_urls_step2)} lots already processed")
    
    # Process new items incrementally
    new_items = []
    skipped_count = 0
    processed_count = 0
    save_interval = 10  # Save every 10 items

    for i, lot in enumerate(items, 1):
        url = lot["url"]

        # Skip if both steps are already done for this lot
        skip_this_lot = False
        if RUN_STEP_1 and url in processed_urls_step1:
            skip_this_lot = True
        if RUN_STEP_2 and url in processed_urls_step2:
            skip_this_lot = True
        if RUN_STEP_1 and RUN_STEP_2 and skip_this_lot:
            skipped_count += 1
            continue
        
        logger.info(f"Processing {i}/{total_items}: {url}")
        enriched_lot = process_lot(lot)
        new_items.append(enriched_lot)
        processed_count += 1
        
        # Save progress every N items to avoid losing work
        if processed_count % save_interval == 0:
            # Merge new items with existing items
            all_items = existing_items + new_items
            save_data = {
                "count": len(all_items),
                "items": all_items
            }
            save_json(save_data, OUTPUT_FILE)
            logger.info(f"Incremental save: {processed_count} new items processed, total {len(all_items)} items")
            
            # Update existing_items to include the new ones for next merge
            # Also update processed_urls sets
            for item in new_items:
                item_url = item["url"]
                if RUN_STEP_1 and has_step1_data(item):
                    processed_urls_step1.add(item_url)
                if RUN_STEP_2 and has_step2_data(item):
                    processed_urls_step2.add(item_url)

            existing_items = all_items
            new_items = []  # Clear to avoid duplicates
    
    # Final merge and save
    if new_items:
        all_items = existing_items + new_items
        # Update processed_urls for final batch
        for item in new_items:
            item_url = item["url"]
            if RUN_STEP_1 and has_step1_data(item):
                processed_urls_step1.add(item_url)
            if RUN_STEP_2 and has_step2_data(item):
                processed_urls_step2.add(item_url)
    else:
        all_items = existing_items
    
    final_data = {
        "count": len(all_items),
        "items": all_items
    }
    
    save_json(final_data, OUTPUT_FILE)
    
    logger.info(f"Completed enrichment:")
    logger.info(f"  - Steps enabled: {steps_enabled}")
    logger.info(f"  - Total input lots: {total_items}")
    logger.info(f"  - Skipped (already processed): {skipped_count}")
    logger.info(f"  - Newly processed: {processed_count}")
    logger.info(f"  - Final processed Step 1: {len(processed_urls_step1)}")
    logger.info(f"  - Final processed Step 2: {len(processed_urls_step2)}")
    logger.info(f"  - Output file: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()