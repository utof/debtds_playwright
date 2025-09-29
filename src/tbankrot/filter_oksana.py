#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
filter_oksana.py

Purpose
-------
1) Pure filter:
   - Keep only lots where debt > 2,000,000:
       * Use `nominal_debt` if present/parsable; otherwise fall back to `total_debt_amount`.
   - Keep only lots where `auction_end_date` is between 21 and 90 days from today (inclusive).
   - Returns a dict of {lot_id: lot} without side effects.

2) Optional enrichment (async):
   - Given an existing Playwright Page (to avoid reopening the browser), go through debtor INNs
     and append company status into `lot["data"]["company_statuses"] = [{ "inn": ..., "company_status": ..., "Сырые Данные": ... }, ...]`.
   - Designed to support multiple INNs per lot, but by default only fetches the FIRST INN
     (set `fetch_all=True` to fetch all).

3) CLI behavior (only when __main__):
   - Loads cache from "cache/lots_cache.json"
   - Applies the pure filter
   - Launches a single browser instance, creates a page, enriches filtered lots (FIRST INN per lot)
   - Applies post-enrichment pruning by company_status rules
   - Saves to "debug/oksana_filter.json"
   - Prints a summary

Notes
-----
- Keep `filter_lots` pure — reusable from other modules.
- `enrich_with_status` requires a `page` and a callable `get_status(page, inn) -> awaitable[str]`.
- We try a couple of common import paths for Browser and get_company_status in __main__.
"""

import os
import re
import json
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, Callable, Awaitable, Iterable, List, Optional, Union

from .filter_oksana_status_utils import _norm_spaces, _normalize_company_status

# ---------- Constants ----------
CACHE_FILE = "cache/lots_cache.json"
OUTPUT_FILE = "debug/oksana_filter.json"
DATE_FMT = "%d.%m.%Y"  # e.g. "02.12.2025"

NumberLike = Union[int, float, str]

# For parsing a date from raw status text (first occurrence wins)
DATE_RX = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")


# ---------- Helpers (pure) ----------
def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), DATE_FMT)
    except Exception:
        return None


def _to_float(x: Optional[NumberLike]) -> Optional[float]:
    """
    Best-effort conversion to float. Returns None on failure/empty.
    Accepts strings with spaces (e.g., "2 345 000.00") and commas.
    """
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip().replace(" ", "").replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _as_list(v: Any) -> List[Any]:
    """Normalize a value into a list. Strings become [string]. None -> []."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _first_date_in_text(text: str) -> Optional[datetime]:
    """Extract the first dd.mm.yyyy in a string, if any."""
    if not text:
        return None
    m = DATE_RX.search(text)
    if not m:
        return None
    return _parse_date(m.group(1))


# ---------- Core: Pure filter ----------
def filter_lots(all_lots: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Filter lots by:
      - Debt > 2_000_000: use nominal_debt; if absent/unparsable, fallback to total_debt_amount.
      - auction_end_date within [21, 90] days from today (inclusive).

    Parameters
    ----------
    all_lots : dict
        The entire cache dict, expected shape:
        { lot_id: { "url": ..., "parsed_at": ..., "data": { ...fields... } } }

    Returns
    -------
    dict
        Filtered dict of the same shape.
    """
    today = datetime.today()
    min_days = 21
    max_days = 90

    result: Dict[str, Dict[str, Any]] = {}

    for lot_id, lot in all_lots.items():
        data = lot.get("data", {}) or {}

        # Debt check
        nominal_debt_val = _to_float(data.get("nominal_debt"))
        total_debt_val = _to_float(data.get("total_debt_amount"))

        debt_ok = False
        if nominal_debt_val is not None:
            debt_ok = nominal_debt_val > 2_000_000
        elif total_debt_val is not None:
            debt_ok = total_debt_val > 2_000_000

        if not debt_ok:
            continue

        # Date check
        end_date = _parse_date(data.get("auction_end_date"))
        if not end_date:
            continue

        delta_days = (end_date - today).days
        if delta_days < min_days or delta_days > max_days:
            continue

        result[lot_id] = lot

    return result


# ---------- Async: Enrichment (requires Playwright Page + get_status) ----------
async def enrich_with_status(
    page: Any,
    lots: Dict[str, Dict[str, Any]],
    *,
    get_status: Callable[[Any, str], Awaitable[str]],
    fetch_all: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Append normalized company status info to each filtered lot.

    - Reads data["debtor_inn"] (str or list).
    - By default, fetches only the first INN per lot (fetch_all=False).
    - Saves results under data["company_statuses"] = [
          { "inn": str, "company_status": str, "Сырые Данные": str },
          ...
      ]
    - Replaces the old 'status' field entirely.
    """
    for lot_id, lot in lots.items():
        data = lot.get("data", {}) or {}
        inns = [str(x).strip() for x in _as_list(data.get("debtor_inn")) if str(x).strip()]
        if not inns:
            data["company_statuses"] = []
            lot["data"] = data
            continue

        inns_to_fetch = inns if fetch_all else inns[:1]
        statuses: List[Dict[str, str]] = []

        for inn in inns_to_fetch:
            try:
                raw = await get_status(page, inn)
            except Exception as e:
                # Keep a consistent structure even on error
                raw = f"error: {e}"

            normalized = _normalize_company_status(raw)
            statuses.append({
                "inn": inn,
                "company_status": normalized,
                "Сырые Данные": _norm_spaces(raw),
            })

        data["company_statuses"] = statuses
        lot["data"] = data

    return lots


# ---------- Post-enrichment pruning ----------
# Immediate exclusions (status alone is enough)
_IMMEDIATE_EXCLUDE = {
    "признан банкротом",
    "исключен из егрюл: конкурсное производство",
}

# Conditional exclusions: exclude only if (today - date_in_raw) > 1095 days
_CONDITIONAL_EXCLUDE = {
    "исключен из егрюл: реорганизация",
    "исключен из егрюл: недостоверность сведений",
    "исключен из егрюл: иное",
}

def _should_exclude_status(company_status: str, raw_text: str, today: Optional[datetime] = None) -> bool:
    """
    Returns True if the given status (and raw text) matches the exclusion rules.
    """
    s = (company_status or "").strip().lower()
    if not s:
        return False

    if s in _IMMEDIATE_EXCLUDE:
        return True

    if s in _CONDITIONAL_EXCLUDE:
        dt = _first_date_in_text(company_status or "")
        if not dt:
            return False  # need a date to apply the 3-year rule
        ref = today or datetime.today()
        return (ref - dt).days > 1095

    return False


def prune_lots_by_company_status(lots: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Remove lots where ANY fetched company_status entry (for the fetched INNs)
    triggers the exclusion rules.
    """
    pruned: Dict[str, Dict[str, Any]] = {}
    today = datetime.today()

    for lot_id, lot in lots.items():
        data = lot.get("data", {}) or {}
        statuses = data.get("company_statuses") or []

        exclude = False
        for entry in statuses:
            cstat = (entry or {}).get("company_status", "")
            raw = (entry or {}).get("Сырые Данные", "")
            if _should_exclude_status(cstat, raw, today=today):
                exclude = True
                break

        if not exclude:
            pruned[lot_id] = lot

    return pruned


# ---------- Public convenience API ----------
def run_filter_only(cache: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Pure convenience wrapper for reuse from other modules.
    """
    return filter_lots(cache)


async def run_filter_and_enrich_with_page(
    page: Any,
    cache: Dict[str, Dict[str, Any]],
    *,
    get_status: Callable[[Any, str], Awaitable[str]],
    fetch_all: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Reusable from other code that already has a Page instance.
    - Does NOT save to disk.
    - Returns the enriched, filtered lots (post-pruned by company_status rules).
    """
    filtered = filter_lots(cache)
    enriched = await enrich_with_status(page, filtered, get_status=get_status, fetch_all=fetch_all)
    pruned = prune_lots_by_company_status(enriched)
    return pruned


# ---------- CLI (__main__) ----------
async def _main_async():
    # Lazy imports to avoid hard coupling when this module is imported purely for filtering.
    # Resolve Browser
    Browser = None
    try:
        from ..browser import Browser as _B  # type: ignore
        Browser = _B
    except Exception:
        try:
            from .browser import Browser as _B  # type: ignore
            Browser = _B
        except Exception:
            from browser import Browser as _B  # type: ignore
            Browser = _B

    # Resolve get_company_status
    get_company_status = None
    try:
        from ..companium_company_status import get_company_status as _G  # type: ignore
        get_company_status = _G
    except Exception:
        try:
            from .companium_company_status import get_company_status as _G  # type: ignore
            get_company_status = _G
        except Exception:
            from companium_company_status import get_company_status as _G  # type: ignore
            get_company_status = _G

    # Load cache
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)

    filtered = filter_lots(cache)

    # Ensure output dir
    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)

    # Open one browser instance and one page
    browser = Browser(headless=False, datadir="datadir")
    await browser.launch()
    page = await browser.context.new_page()
    try:
        enriched = await enrich_with_status(
            page,
            filtered,
            get_status=get_company_status,
            fetch_all=False,  # currently only the first INN per lot; set True to fetch all
        )
    finally:
        await browser.close()

    # Post-enrichment pruning
    final_lots = prune_lots_by_company_status(enriched)

    # Save result
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_lots, f, ensure_ascii=False, indent=2)

    print(f"Enriched & pruned {len(final_lots)} lots saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(_main_async())
