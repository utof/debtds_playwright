#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from typing import Any, Dict

from loguru import logger

from .ai_request import update_debtor_data

INPUT_FILE = "debug/lot_details.json"
OUTPUT_FILE = "debug/lot_details_enriched.json"

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

def has_debtor_data(lot: Dict[str, Any]) -> bool:
    """Check if lot already has debtor_name data."""
    data = lot.get("data", {})
    debtor_names = data.get("debtor_name", [])
    return bool(debtor_names)  # Non-empty list means already processed

def process_lot(lot: Dict[str, Any]) -> Dict[str, Any]:
    """Process single lot: call AI if announcement_text is non-empty."""
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
        logger.info(f"Processed lot {lot['url']}: extracted {len(enriched_data.get('debtor_name', []))} debtor names")
    except Exception as e:
        logger.exception(f"Failed to process lot {lot['url']}: {e}")
        # Ensure empty lists even on error
        for key in ["debtor_name", "debtor_inn", "debtor_ogrn", "case_number", "nominal_debt"]:
            if key not in data:
                data[key] = []
    
    return lot

def main():
    """Main processing function with incremental updates."""
    logger.info(f"Starting enrichment: input={INPUT_FILE}, output={OUTPUT_FILE}")
    
    # Load input data
    input_data = load_json(INPUT_FILE)
    items = input_data.get("items", [])
    total_items = len(items)
    logger.info(f"Loaded {total_items} lots from input")
    
    if total_items == 0:
        logger.warning("No items to process")
        return
    
    # Load existing output if it exists
    output_data = {"count": 0, "items": []}
    processed_urls = set()
    if os.path.exists(OUTPUT_FILE):
        output_data = load_json(OUTPUT_FILE)
        existing_items = output_data.get("items", [])
        # Track which URLs already have debtor data
        for item in existing_items:
            if has_debtor_data(item):
                processed_urls.add(item["url"])
        logger.info(f"Found existing output with {len(existing_items)} items, {len(processed_urls)} already processed")
    
    # Process new items incrementally
    new_items = []
    skipped_count = 0
    processed_count = 0
    save_interval = 1  # Save every 10 items
    
    for i, lot in enumerate(items, 1):
        url = lot["url"]
        if url in processed_urls:
            skipped_count += 1
            continue
        
        logger.info(f"Processing {i}/{total_items}: {url}")
        enriched_lot = process_lot(lot)
        new_items.append(enriched_lot)
        processed_count += 1
        
        # Save progress every N items to avoid losing work
        if processed_count % save_interval == 0:
            # Merge new items with ALL existing items (not just output_data items)
            all_items = existing_items + new_items
            save_data = {
                "count": len(all_items),
                "items": all_items
            }
            save_json(save_data, OUTPUT_FILE)
            logger.info(f"Incremental save: {processed_count} new items processed, total {len(all_items)} items")
            
            # Update existing_items to include the new ones for next merge
            existing_items = all_items
            new_items = []  # Clear to avoid duplicates
    
    # Final merge and save
    if new_items:
        all_items = existing_items + new_items
    else:
        all_items = existing_items
    
    final_data = {
        "count": len(all_items),
        "items": all_items
    }
    
    save_json(final_data, OUTPUT_FILE)
    
    logger.info(f"Completed enrichment:")
    logger.info(f"  - Total input lots: {total_items}")
    logger.info(f"  - Skipped (already processed): {skipped_count}")
    logger.info(f"  - Newly processed: {processed_count}")
    logger.info(f"  - Output file: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()