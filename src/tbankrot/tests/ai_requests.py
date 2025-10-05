#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os

from ..ai_request import update_debtor_data, update_debtor_flags

def main(n: int = 3):
    cache_path = os.path.join("cache", "lots_cache.json")
    with open(cache_path, "r", encoding="utf-8") as f:
        lots_cache = json.load(f)

    lot_items = list(lots_cache.items())[:n]

    for lot_id, lot_data in lot_items:
        print(f"\n--- Processing lot {lot_id} ---")
        announcement_text = lot_data.get("data", {}).get("announcement_text", "")
        if not announcement_text:
            print("No announcement_text found, skipping")
            continue

        enriched = update_debtor_data({"announcement_text": announcement_text})
        enriched = update_debtor_flags(enriched)
        # Save enriched data back into the lot’s "data" section
        lots_cache[lot_id]["data"].update(enriched)

    # Write to a new file (so you don’t overwrite original)
    out_path = os.path.join("cache", "lots_cache_enriched.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(lots_cache, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Enriched cache saved to {out_path}")

if __name__ == "__main__":
    main(n=1)
