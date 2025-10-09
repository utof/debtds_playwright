#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os

from loguru import logger

INPUT_FILE = "debug/lot_details_full_ai.json"
OUTPUT_FILE = "debug/lot_details_with_inn_orgn_check.json"

def load_json(path: str):
    """Load JSON file with error handling."""
    if not os.path.exists(path):
        logger.error(f"Input file not found: {path}")
        return None
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.exception(f"Failed to load {path}: {e}")
        return None

def save_json(data, path: str):
    """Save JSON to file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved to {path}")
    except Exception as e:
        logger.exception(f"Failed to save {path}: {e}")

def check_inn_orgn_mismatch(lot_data: dict) -> bool:
    """Check if debtor_inn is empty but debtor_ogrn is not empty."""
    debtor_inn = lot_data.get("debtor_inn", [])
    debtor_ogrn = lot_data.get("debtor_ogrn", [])
    
    # Check if debtor_inn is empty (empty list or missing)
    inn_empty = not debtor_inn or len(debtor_inn) == 0
    
    # Check if debtor_ogrn is not empty
    ogrn_not_empty = bool(debtor_ogrn) and len(debtor_ogrn) > 0
    
    return inn_empty and ogrn_not_empty

def check_empty_individuals_no_inn_orgn(lot_data: dict) -> bool:
    """Check if individuals is empty string but both debtor_inn and debtor_ogrn are empty."""
    individuals = lot_data.get("individuals", "")
    debtor_inn = lot_data.get("debtor_inn", [])
    debtor_ogrn = lot_data.get("debtor_ogrn", [])
    
    # Check if individuals is empty string
    individuals_empty = individuals == ""
    
    # Check if both debtor_inn and debtor_ogrn are empty
    inn_empty = not debtor_inn or len(debtor_inn) == 0
    ogrn_empty = not debtor_ogrn or len(debtor_ogrn) == 0
    
    return individuals_empty and inn_empty and ogrn_empty

def main():
    """Main function to analyze INN/OGRN mismatch and individuals classification issues."""
    logger.info(f"Analyzing {INPUT_FILE}")
    
    # Load input data
    data = load_json(INPUT_FILE)
    if data is None:
        return
    
    items = data.get("items", [])
    total_items = len(items)
    logger.info(f"Loaded {total_items} lots")
    
    if total_items == 0:
        logger.warning("No items to process")
        return
    
    # Process each lot
    mismatch_count = 0
    individuals_issue_count = 0
    
    for i, lot in enumerate(items, 1):
        # Get the data dict from the lot structure
        lot_data = lot.get("data", {})
        
        # Check 1: Empty INN but non-empty OGRN
        has_inn_orgn_mismatch = check_inn_orgn_mismatch(lot_data)
        lot["empty_inn_but_nonempty_orgn"] = has_inn_orgn_mismatch
        
        if has_inn_orgn_mismatch:
            mismatch_count += 1
            logger.info(f"Found INN/OGRN mismatch at lot {i}: {lot['url']}")
        
        # Check 2: Empty individuals but no INN/OGRN
        has_individuals_issue = check_empty_individuals_no_inn_orgn(lot_data)
        lot["empty_individuals_but_no_inn_orgn"] = has_individuals_issue
        
        if has_individuals_issue:
            individuals_issue_count += 1
            logger.info(f"Found individuals classification issue at lot {i}: {lot['url']}")
    
    # Update the main data structure
    data["count"] = total_items
    data["items"] = items
    
    # Save result
    save_json(data, OUTPUT_FILE)
    
    # Summary
    logger.info(f"Analysis complete:")
    logger.info(f"  - Total lots: {total_items}")
    logger.info(f"  - Lots with empty INN but non-empty OGRN: {mismatch_count}")
    logger.info(f"  - Percentage: {(mismatch_count/total_items*100):.1f}%")
    logger.info(f"  - Lots with empty individuals but no INN/OGRN: {individuals_issue_count}")
    logger.info(f"  - Percentage: {(individuals_issue_count/total_items*100):.1f}%")
    logger.info(f"  - Output file: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()