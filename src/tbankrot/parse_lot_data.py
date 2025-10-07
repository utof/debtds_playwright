#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import math
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from .api_client import APIClient

# ---------- Logging: per-run error file ----------
os.makedirs("data/error_logs", exist_ok=True)
_run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_error_file = f"data/error_logs/error_{_run_ts}.log"
logger.remove()
logger.add(_error_file, level="ERROR")
logger.add(lambda msg: print(msg, end=""), level="INFO")  # mirror to stdout/stderr

# ---------- Helpers ----------
DATE_RX_ANY = re.compile(r"(\d{2})[./-](\d{2})[./-](\d{4})")

def _clean_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _parse_price_to_float(s: str) -> float:
    """Convert strings like '95 000,00' → 95000.00; returns NaN on failure."""
    try:
        cleaned = (s or "").replace(" ", "").replace("\xa0", "").replace(",", ".")
        return float(cleaned)
    except Exception:
        return float("nan")

def _parse_date_text(s: str) -> Optional[datetime]:
    """
    Accepts dd.mm.yyyy / dd/mm/yyyy / dd-mm-yyyy; returns datetime (naive) or None.
    """
    if not s:
        return None
    m = DATE_RX_ANY.search(s)
    if not m:
        return None
    dd, mm, yyyy = m.groups()
    try:
        return datetime.strptime(f"{dd}.{mm}.{yyyy}", "%d.%m.%Y")
    except Exception:
        return None

def parse_api_datetime(dt_str: str) -> str:
    """Parse ISO datetime string 'YYYY-MM-DD HH:MM:SS' to 'dd.mm.yyyy' format."""
    if not dt_str:
        return ""
    try:
        # Extract date part and reformat
        date_part = dt_str.split(" ")[0]  # 'YYYY-MM-DD'
        dt = datetime.strptime(date_part, "%Y-%m-%d")
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return ""


def parse_api_auction_status(
    api_data: Dict[str, Any], auction_start_date: str, auction_end_date: str
) -> str:
    """Use direct API status if available, otherwise infer from auction dates using new parse_auction_status."""
    try:
        # Check for direct API status field (assume 'status' or similar)
        if "status" in api_data:
            status_map = {
                "Завершенные": "Торги закончились",
                "Активные": "Проведение торгов",
                "Запланированные": "Торги еще не начались",
                # Add more mappings as needed
            }
            return status_map.get(api_data["status"], api_data["status"])

        # Fallback to date-based inference using new synchronous function
        return parse_auction_status(auction_start_date, auction_end_date)
    except Exception as e:
        logger.exception(f"parse_api_auction_status failed: {e}")
        return "Ошибка: невозможно определить статус"


def parse_api_price(price_str_or_num: Any) -> float:
    """Parse API price field using existing helper."""
    try:
        if isinstance(price_str_or_num, (int, float)):
            return float(price_str_or_num)
        return _parse_price_to_float(str(price_str_or_num))
    except Exception:
        return float("nan")


def parse_api_bankrupt_info(api_data: Dict[str, Any]) -> Dict[str, str]:
    """Map API bankrupt fields from debtor object."""
    try:
        debtor = api_data.get("debtor", {})
        return {
            "bankrupt_name": _clean_spaces(debtor.get("name", "")),
            "bankrupt_inn": str(debtor.get("inn", "")),
        }
    except Exception as e:
        logger.exception(f"parse_api_bankrupt_info failed: {e}")
        return {"bankrupt_name": "", "bankrupt_inn": ""}


def parse_api_announcement_text(api_data: Dict[str, Any]) -> str:
    """Map API announcement field and clean with existing helper."""
    try:
        text = api_data.get("text", "") or ""
        return _clean_spaces(str(text))
    except Exception as e:
        logger.exception(f"parse_api_announcement_text failed: {e}")
        return ""

def parse_api_protocol_link(api_data: Dict[str, Any]) -> str:
    """Find protocol URL in etpDocuments array where name contains 'protocol' or first PDF/XML."""
    try:
        documents = api_data.get("etpDocuments", [])
        for doc in documents:
            name = doc.get("name", "").lower()
            if "protocol" in name or name.endswith((".pdf", ".xml")):
                return doc.get("url", "")
        return ""
    except Exception as e:
        logger.exception(f"parse_api_protocol_link failed: {e}")
        return ""

def parse_api_prev_lots_count(api_data: Dict[str, Any]) -> int:
    """Map API previous lots from debtor.closedLotCount or default to -1."""
    try:
        debtor = api_data.get("debtor", {})
        prev_count = debtor.get("closedLotCount", -1)
        return int(prev_count) if prev_count != -1 else -1
    except Exception:
        return -1

def parse_api_publish_date(api_data: Dict[str, Any]) -> str:
    """Map API publish date from tstart or fallback to error message."""
    try:
        tstart = api_data.get("tstart", "")
        if tstart:
            return parse_api_datetime(tstart)
        return "ошибка: не удалось извлечь дату размещения"
    except Exception as e:
        logger.exception(f"parse_api_publish_date failed: {e}")
        return "ошибка: не удалось извлечь дату размещения"

async def parse_lot(lot_url: str) -> Dict[str, object]:
    """
    API-based version: Extract lot ID, fetch via APIClient, map to existing output format.
    Preserves exact dict structure and types. Returns defaults on API failure.
    """
    data = {
        "lot_link": lot_url,
        "publish_date": "ошибка: не удалось извлечь дату размещения",
        "auction_status": "Ошибка: невозможно определить статус",
        "auction_start_date": "",
        "auction_end_date": "",
        "application_start_date": "",
        "application_end_date": "",
        "start_price": float("nan"),
        "protocol_link": "",
        "bankrupt_name": "",
        "bankrupt_inn": "",
        "announcement_text": "",
        "prev_lots_count": -1,
        "raw_api_response": {},
    }

    try:
        lot_id = extract_lot_id_from_url(lot_url)
        if not lot_id:
            logger.error(f"Could not extract lot ID from URL: {lot_url}")
            return data

        # Initialize API client
        client = APIClient()
        try:
            api_response = client.fetch_trade_details(lot_id)
            if not isinstance(api_response, dict) or not api_response.get(
                "status", False
            ):
                logger.warning(f"API response invalid for lot {lot_id}: {api_response}")
                data["raw_api_response"] = {}
                return data

            # Extract trade data from response['result']['trade']
            result = api_response.get("result", {})
            trade_data = result.get("trade", {})
            if not trade_data:
                logger.warning(f"No trade data in API response for lot {lot_id}")
                data["raw_api_response"] = api_response
                return data

            # Set raw response before parsing
            data["raw_api_response"] = api_response

            # Map fields using helpers with error handling
            try:
                publish_date = parse_api_publish_date(trade_data)
                auction_start_date = parse_api_datetime(trade_data.get("tstart", ""))
                auction_end_date = parse_api_datetime(trade_data.get("tend", ""))
                application_start_date = parse_api_datetime(
                    trade_data.get("zstart", "")
                )
                application_end_date = parse_api_datetime(trade_data.get("zend", ""))
                auction_status = parse_api_auction_status(
                    trade_data, auction_start_date, auction_end_date
                )
                start_price = _parse_price_to_float(str(trade_data.get("price", "")))
                protocol_link = parse_api_protocol_link(trade_data)
                bankrupt_info = parse_api_bankrupt_info(trade_data)
                announcement_text = parse_api_announcement_text(trade_data)
                prev_lots_count = parse_api_prev_lots_count(trade_data)

                # Update data with parsed values
                data.update(
                    {
                        "publish_date": publish_date,
                        "auction_status": auction_status,
                        "auction_start_date": auction_start_date,
                        "auction_end_date": auction_end_date,
                        "application_start_date": application_start_date,
                        "application_end_date": application_end_date,
                        "start_price": float(start_price)
                        if not math.isnan(start_price)
                        else float("nan"),
                        "protocol_link": protocol_link,
                        "bankrupt_name": bankrupt_info["bankrupt_name"],
                        "bankrupt_inn": bankrupt_info["bankrupt_inn"],
                        "announcement_text": announcement_text,
                        "prev_lots_count": prev_lots_count,
                    }
                )
            except Exception as parse_e:
                logger.error(f"Parsing failed for lot {lot_id}: {parse_e}")
                # Keep defaults on parsing failure

        finally:
            client.close()

        return data

    except Exception as e:
        logger.exception(f"API parsing failed for {lot_url}: {e}")
        return data


# ---------- new synchronous parse_auction_status to replace the undefined extract_auction_status using date-based inference with the existing _parse_date_text helper ----------
def parse_auction_status(auction_start_date: str, auction_end_date: str) -> str:
    """Infer auction status based on current date vs auction dates using date inference."""
    try:
        start_dt = _parse_date_text(auction_start_date)
        end_dt = _parse_date_text(auction_end_date)
        if not start_dt or not end_dt:
            return "Ошибка: невозможно определить статус"

        now = datetime.now()

        if now < start_dt:
            return "Торги еще не начались"
        elif start_dt <= now <= end_dt:
            return "Проведение торгов"
        else:
            return "Торги закончились"
    except Exception as e:
        logger.exception(f"parse_auction_status failed: {e}")
        return "Ошибка: невозможно определить статус"


# ---------- API-based parse_lot ----------
def extract_lot_id_from_url(lot_url: str) -> str:
    """Extract lot ID from URL like https://tbankrot.ru/item?id=6936255 -> '6936255'."""
    try:
        m = re.search(r"id=([0-9]+)", lot_url)
        return m.group(1) if m else ""
    except Exception:
        return ""


def parse_api_dates(api_data: Dict[str, Any]) -> Dict[str, str]:
    """Map API date fields to the expected string format using _parse_date_text helper."""
    result = {
        "application_start_date": "",
        "application_end_date": "",
        "auction_start_date": "",
        "auction_end_date": "",
    }
    try:
        # Assume API fields like 'application_start', 'application_end', 'auction_start', 'auction_end'
        # Convert datetime objects or strings to dd.mm.yyyy format
        for key, api_key in [
            ("application_start_date", "application_start"),
            ("application_end_date", "application_end"),
            ("auction_start_date", "auction_start"),
            ("auction_end_date", "auction_end"),
        ]:
            if api_key in api_data and api_data[api_key]:
                dt = _parse_date_text(str(api_data[api_key]))
                result[key] = dt.strftime("%d.%m.%Y") if dt else ""
        return result
    except Exception as e:
        logger.exception(f"parse_api_dates failed: {e}")
        return result


# ---------- Updated Standalone runner ----------
async def _run_once(test_url: str, outfile: str):
    """
    Use new API-based parse_lot(lot_url) directly, no browser.
    Always writes JSON with best-effort fields.
    """
    data = {
        "lot_link": test_url,
        "publish_date": "ошибка: не удалось извлечь дату размещения",
        "auction_status": "Ошибка: невозможно определить статус",
        "auction_start_date": "",
        "auction_end_date": "",
        "application_start_date": "",
        "application_end_date": "",
        "start_price": float("nan"),
        "protocol_link": "",
        "bankrupt_name": "",
        "bankrupt_inn": "",
        "announcement_text": "",
        "prev_lots_count": -1,
    }

    try:
        # Use new API-based function
        parsed = await parse_lot(test_url)
        # Merge parsed values over defaults
        data.update(parsed)
    except Exception as e:
        logger.exception(f"API parsing failure: {e}")

    # Always write a file, even if partially filled.
    os.makedirs(os.path.dirname(outfile), exist_ok=True)
    try:
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Wrote: {outfile}")
    except Exception as e:
        logger.exception(f"Writing output failed: {e}")


if __name__ == "__main__":
    # Test URL you provided
    # url = "https://tbankrot.ru/item?id=6936255"
    # url = "https://tbankrot.ru/item?id=7133530"
    url = "https://tbankrot.ru/item?id=7003711"
    # Overwrite file every run, as requested
    out_path = os.path.join("debug", "lot_7003711.json")
    asyncio.run(_run_once(url, out_path))
