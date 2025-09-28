#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RDL updater: reads an input JSON with auctions, calls local API per auction to
enrich with RDL results, and writes a copy to an output file (input_outN.json).

Key behaviors:
- Does NOT modify the input file.
- Creates output file with suffix _out1 (or _out2, ... if exists).
- Saves progress after EACH processed auction via atomic write (temp -> rename).
- Skips auctions that already have a definitive 'final_RDL' value.
- Retries auctions with empty or 'error' results.
- If required fields are missing, writes 'final_RDL': 'недостаточно данных: ...'
  (and treats that as terminal — skipped in future runs).
- Flattens API 'data' keys into the auction (excluding 'debtor_inn', but includes 'input_data').

API shape (GET):
  http://127.0.0.1:8000/company_rdl/{inn}?publish_date=dd.mm.yyyy
Response (success):
{
  "success": true,
  "data": {
    "debtor_inn": "...",
    "CEO_RDL": "да"/"нет",
    "Founders_RDL": "да"/"нет",
    "final_RDL": "да"/"нет",
    "input_data": {...}
  }
}
"""

from __future__ import annotations

import time
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import requests
from loguru import logger


# ---------------------------- Configuration -------------------------------- #

API_BASE = "http://127.0.0.1:8000/company_rdl"
API_TIMEOUT_SECS = 600

LOGS_DIR = "logs"
LOG_FILE = os.path.join(LOGS_DIR, "rdl_updater.log")

# ---------------------------- Utilities ------------------------------------ #

def ensure_logs():
    os.makedirs(LOGS_DIR, exist_ok=True)
    logger.remove()
    # Console
    logger.add(sys.stderr, level="INFO", format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {message}")
    # Rotating file (daily)
    logger.add(LOG_FILE, rotation="1 day", level="INFO",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")


def determine_output_path(input_path: str) -> str:
    """
    Choose output path by appending _out1, _out2, ... before the .json extension.
    """
    base, ext = os.path.splitext(input_path)
    n = 1
    while True:
        candidate = f"{base}_out{n}{ext or '.json'}"
        if not os.path.exists(candidate):
            return candidate
        n += 1


def atomic_write_json(obj: Any, target_path: str, retries: int = 5, delay: float = 0.2):
    dir_ = os.path.dirname(os.path.abspath(target_path)) or "."
    tmp_path = os.path.join(dir_, f".{os.path.basename(target_path)}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

    for attempt in range(1, retries + 1):
        try:
            os.replace(tmp_path, target_path)
            return
        except PermissionError as e:
            if attempt == retries:
                raise
            time.sleep(delay)


def convert_publish_date(date_str: str) -> Optional[str]:
    """
    Convert 'dd-mm-yyyy' -> 'dd.mm.yyyy'. If already 'dd.mm.yyyy', return as-is.
    Returns None if parsing fails.
    """
    if not isinstance(date_str, str):
        return None

    # Already with dots?
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", date_str):
        return date_str

    # Try hyphen format
    try:
        dt = datetime.strptime(date_str, "%d-%m-%Y")
        return dt.strftime("%d.%m.%Y")
    except Exception:
        pass

    # Last-chance: try to normalize non-digit separators to dots if obviously dd?mm?yyyy
    m = re.fullmatch(r"(\d{2})\D(\d{2})\D(\d{4})", date_str)
    if m:
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"

    return None


def get_first_inn(debtor_inn_field: Any) -> Optional[str]:
    """
    debtor_inn can be a list[str], a single string, or something else. Extract first INN string if present.
    """
    if debtor_inn_field is None:
        return None
    if isinstance(debtor_inn_field, list):
        for v in debtor_inn_field:
            if isinstance(v, (str, int)):
                s = str(v).strip()
                if s:
                    return s
        return None
    if isinstance(debtor_inn_field, (str, int)):
        s = str(debtor_inn_field).strip()
        return s or None
    return None


def current_final_value(auction: Dict[str, Any]) -> Optional[str]:
    """
    Read existing final result, tolerant to casing: 'final_RDL' or 'final_rdl'.
    """
    v = auction.get("final_RDL")
    if v is None:
        v = auction.get("final_rdl")
    if isinstance(v, str):
        return v.strip()
    return None


def is_terminal_insufficient(val: Optional[str]) -> bool:
    """
    Treat terminal statuses as skip-forever:
    - 'недостаточно данных: ...'
    - 'пропуск: ...'
    """
    if not val:
        return False
    s = val.lower()
    return s.startswith("недостаточно данных") or s.startswith("пропуск")

def should_skip(auction: Dict[str, Any]) -> bool:
    """
    Skip if:
      - 'final_RDL' already a non-empty, non-'error' string
      - OR value is 'недостаточно данных: ...'
    Reprocess if empty or 'error'.
    """
    val = current_final_value(auction)
    if not val:
        return False  # missing/empty -> process
    if is_terminal_insufficient(val):
        return True   # skip forever
    return val.lower() != "error"  # skip if not 'error'


def call_rdl_api(inn: str, publish_date_dot: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Returns: (ok, data_dict_or_none, error_message_or_none)
    """
    url = f"{API_BASE}/{inn}"
    try:
        resp = requests.get(url, params={"publish_date": publish_date_dot}, timeout=API_TIMEOUT_SECS)
    except requests.RequestException as e:
        return False, None, f"request_failed: {e}"

    if not resp.ok:
        # Inspect JSON error for specific INN-length failure returned as HTTP 500
        try:
            err_payload = resp.json()
            if resp.status_code == 500 and isinstance(err_payload, dict):
                detail = str(err_payload.get("detail", ""))
                if "INN must be 9 or 10 digits long" in detail:
                    return False, None, "inn_too_long"
        except ValueError:
            pass
        return False, None, f"http_{resp.status_code}"

    try:
        payload = resp.json()
    except ValueError:
        return False, None, "invalid_json"

    if not isinstance(payload, dict) or not payload.get("success"):
        return False, None, "api_reported_failure"

    data = payload.get("data")
    if not isinstance(data, dict):
        return False, None, "invalid_data"
    
    if isinstance(data, str) and "нет данных" in data.lower():
        return False, None, "no_company_data"

    return True, data, None


def enrich_auction(auction: Dict[str, Any]) -> str:
    """
    Process a single auction dict in place.
    Returns a status string for logging: 'skipped', 'updated', 'error', or 'insufficient'.
    """
    # Skip logic
    if should_skip(auction):
        return "skipped"
    
    fp = auction.get("final_price")
    try:
        fp_val = float(fp)
    except (TypeError, ValueError):
        fp_val = None
    if fp_val is not None and fp_val == 0.0:
        auction["final_RDL"] = "пропуск: нулевая финальная цена"
        return "insufficient"
    
    # Validate inputs
    inn = get_first_inn(auction.get("debtor_inn"))
    publish_date_raw = auction.get("publish_date")

    missing = []
    if not inn:
        missing.append("debtor_inn")
    publish_date_dot = convert_publish_date(publish_date_raw) if publish_date_raw else None
    if not publish_date_dot:
        missing.append("publish_date")

    if missing:
        # Terminal: write reason and skip next time
        reason = f"недостаточно данных: {', '.join(missing)}"
        auction["final_RDL"] = reason
        # (Optional) keep legacy lowercase for compatibility if needed:
        # auction["final_rdl"] = reason
        return "insufficient"

    # Call API
    ok, data, err = call_rdl_api(inn, publish_date_dot)
    if not ok or not data:
        if err == "no_company_data":
            reason = "нет данных о компании"
            auction["final_RDL"] = reason
            return "insufficient"
        elif err == "inn_too_long":
            auction["final_RDL"] = "пропуск: длинный инн"
            return "insufficient"
        auction["final_RDL"] = "error"
        return "error"

    # Flatten data into auction (exclude debtor_inn)
    for k, v in data.items():
        if k == "debtor_inn":
            continue
        auction[k] = v

    return "updated"


def process_file(input_path: str, output_path: str):
    with open(input_path, "r", encoding="utf-8") as f:
        src = json.load(f)

    # Copy structure (shallow copy is fine; we'll write whole object each time)
    out = {"metadata": src.get("metadata", {}), "auctions": list(src.get("auctions", []))}

    total = len(out["auctions"])
    logger.info(f"Loaded {total} auctions from: {input_path}")
    logger.info(f"Writing output to: {output_path}")

    # Initial write (copy) so the file exists even if we crash immediately
    atomic_write_json(out, output_path)

    for idx, auction in enumerate(out["auctions"], start=1):
        ident = auction.get("lot_link") or f"auction#{idx}"
        pre_status = current_final_value(auction)
        logger.info(f"[{idx}/{total}] Processing {ident} | pre-final={pre_status!r}")

        status = enrich_auction(auction)

        if status == "skipped":
            logger.info(f"[{idx}/{total}] SKIP {ident}")
        elif status == "updated":
            logger.info(f"[{idx}/{total}] OK   {ident} | final={auction.get('final_RDL')!r}")
        elif status == "insufficient":
            logger.warning(f"[{idx}/{total}] INSUFF {ident} | {auction.get('final_RDL')!r}")
        else:  # error
            logger.error(f"[{idx}/{total}] ERROR {ident} | final={auction.get('final_RDL')!r}")

        # Save progress atomically after each auction
        atomic_write_json(out, output_path)

    logger.info("Done.")


# ---------------------------- Main ----------------------------------------- #

if __name__ == "__main__":
    ensure_logs()

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # Set your INPUT JSON path here:
    INPUT_JSON = "debug/rdl.json"
    # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

    if not os.path.exists(INPUT_JSON):
        logger.error(f"Input file not found: {INPUT_JSON}")
        sys.exit(1)

    OUTPUT_JSON = determine_output_path(INPUT_JSON)

    try:
        process_file(INPUT_JSON, OUTPUT_JSON)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(2)
