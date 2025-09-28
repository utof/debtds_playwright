#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import math
import asyncio
from datetime import datetime
from typing import Dict, Tuple, Optional

from loguru import logger

from ..browser import Browser  # adjust if your Browser is namespaced

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

# ---------- Extractors ----------
async def extract_lot_link(page) -> str:
    try:
        return page.url or ""
    except Exception as e:
        logger.exception(f"extract_lot_link failed: {e}")
        return ""

async def extract_announcement_text(page) -> str:
    """Maps to div.lot_text inner text."""
    try:
        loc = page.locator("div.lot_text")
        if await loc.count() == 0:
            return ""
        text = await loc.first.inner_text()
        return _clean_spaces(text)
    except Exception as e:
        logger.exception(f"extract_announcement_text failed: {e}")
        return ""

async def extract_publish_date(page) -> str:
    """
    From .lot_head span.gray (the one showing 'Размещено: <date time>').
    On failure, return: 'ошибка: не удалось извлечь дату размещения'.
    """
    try:
        head = page.locator(".lot_head")
        if await head.count() == 0:
            return "ошибка: не удалось извлечь дату размещения"

        # 1) Prefer p.obtain span.gray (take the last if multiple)
        obtain_spans = head.locator("p.obtain span.gray")
        n = await obtain_spans.count()
        if n > 0:
            txt = await obtain_spans.nth(n - 1).inner_text()
            return _clean_spaces(txt)

        # 2) Fallback: any .gray inside .lot_head (take the first)
        any_gray = head.locator(".gray")
        m = await any_gray.count()
        if m > 0:
            txt = await any_gray.nth(0).inner_text()
            return _clean_spaces(txt)

        return "ошибка: не удалось извлечь дату размещения"

    except Exception as e:
        logger.exception(f"extract_publish_date failed: {e}")
        return "ошибка: не удалось извлечь дату размещения"


async def extract_dates(page) -> Dict[str, str]:
    """
    Finds dates in the .dates block. If .dates missing → all empty strings.
    application_start_date, application_end_date from 'Прием заявок'
    auction_start_date, auction_end_date from 'Проведение торгов'
    Only dates (discard times).
    """
    result = {
        "application_start_date": "",
        "application_end_date": "",
        "auction_start_date": "",
        "auction_end_date": "",
    }
    try:
        dates = page.locator("div.dates")
        if await dates.count() == 0:
            return result

        async def _extract_pair(row_locator, label_substring: str) -> Tuple[str, str]:
            # Find row containing the label (e.g., "Прием заявок" or "Проведение торгов")
            row = row_locator.filter(has_text=label_substring).first
            if await row.count() == 0:
                return "", ""
            date_spans = row.locator("span.date")
            cnt = await date_spans.count()
            if cnt == 0:
                return "", ""
            start_text = await date_spans.nth(0).inner_text()
            end_text = await date_spans.nth(1).inner_text() if cnt > 1 else ""
            # Normalize to dd.mm.yyyy if possible
            def _norm(s: str) -> str:
                m = DATE_RX_ANY.search(s or "")
                return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else ""
            return _norm(start_text), _norm(end_text)

        rows = dates.locator("table tbody tr")

        app_start, app_end = await _extract_pair(rows, "Прием заявок")
        auc_start, auc_end = await _extract_pair(rows, "Проведение торгов")

        result["application_start_date"] = app_start
        result["application_end_date"] = app_end
        result["auction_start_date"] = auc_start
        result["auction_end_date"] = auc_end
        return result
    except Exception as e:
        logger.exception(f"extract_dates failed: {e}")
        return result

async def extract_auction_status(page, auction_start_date: str, auction_end_date: str) -> str:
    """
    1) If .num .closed exists → return its text stripped of leading dashes/spaces.
    2) Else infer with current date vs auction dates:
       - Before start → "Торги еще не начались"
       - Between → "Проведение торгов"
       - After end → "Торги закончились"
       - Else → "Ошибка: невозможно определить статус"
    """
    try:
        # Direct closed label if present
        closed = page.locator(".num .closed")
        if await closed.count() > 0:
            txt = _clean_spaces(await closed.first.inner_text())
            # Often like "- Торги состоялись"
            return txt.lstrip("-").strip()

        # Inference via dates
        today = datetime.now().date()
        start_dt = _parse_date_text(auction_start_date)
        end_dt = _parse_date_text(auction_end_date)
        if start_dt and today < start_dt.date():
            return "Торги еще не начались"
        if start_dt and end_dt and start_dt.date() <= today <= end_dt.date():
            return "Проведение торгов"
        if end_dt and today > end_dt.date():
            return "Торги закончились"

        return "Ошибка: невозможно определить статус"
    except Exception as e:
        logger.exception(f"extract_auction_status failed: {e}")
        return "Ошибка: невозможно определить статус"

async def extract_start_price(page) -> float:
    """
    Click span.sum.ajax -> wait modal -> read last td.price -> parse float.
    Returns float('nan') if not found or on failure.
    """
    try:
        trigger = page.locator("span.sum.ajax")
        if await trigger.count() == 0:
            return float("nan")
        await trigger.first.click()
        await page.wait_for_selector("div#price_down_modal table tbody tr", timeout=6000)
        price_cells = page.locator("div#price_down_modal table tbody tr td.price")
        n = await price_cells.count()
        if n == 0:
            return float("nan")
        last_price_text = await price_cells.nth(n - 1).inner_text()
        return _parse_price_to_float(last_price_text)
    except Exception as e:
        logger.exception(f"extract_start_price failed: {e}")
        return float("nan")

async def extract_protocol_link(page) -> str:
    """
    Find div.addition_text_field and extract first <a href>. If none -> "".
    """
    try:
        block = page.locator("div.addition_text_field a[href]")
        if await block.count() == 0:
            return ""
        href = await block.first.get_attribute("href")
        return href or ""
    except Exception as e:
        logger.exception(f"extract_protocol_link failed: {e}")
        return ""

async def extract_bankrupt_info(page) -> Dict[str, str]:
    """
    From .trade_block:
      - Name appears in .head after the 'Должник:' label.
      - INN appears in body row where left cell is 'ИНН:'.
    """
    info = {"bankrupt_name": "", "bankrupt_inn": ""}
    try:
        trade_block = page.locator(".trade_block")
        if await trade_block.count() == 0:
            return info

        # Name
        head = trade_block.locator(".head").first
        head_text = _clean_spaces(await head.inner_text()) if await head.count() else ""
        # Remove leading 'Должник:' label and any trailing [ Реестр ] [ ЕФРС ] artifacts
        name = re.sub(r"^\s*Должник:\s*", "", head_text)
        name = re.sub(r"\[\s*Реестр\s*\]\s*\[\s*ЕФРС\s*\]\s*$", "", name).strip()
        # Also strip 'links' text if present in the captured inner_text (square-bracket labels or multiple spaces)
        name = re.sub(r"\[\s*[^]]+\s*\]", "", name).strip()
        info["bankrupt_name"] = name

        # INN
        row_labels = trade_block.locator(".body .row")
        rows_count = await row_labels.count()
        inn_val = ""
        for i in range(rows_count):
            row = row_labels.nth(i)
            left = row.locator("div").nth(0)
            right = row.locator("div").nth(1)
            if await left.count() and await right.count():
                left_text = _clean_spaces(await left.inner_text())
                if left_text.rstrip(":") == "ИНН":
                    inn_val = _clean_spaces(await right.inner_text())
                    break
        info["bankrupt_inn"] = inn_val
        return info
    except Exception as e:
        logger.exception(f"extract_bankrupt_info failed: {e}")
        return info

# ---------- Orchestrator ----------
async def parse_lot(page) -> Dict[str, object]:
    """
    Calls all extractors in the correct order (dates before status).
    Returns a dict with all requested fields.
    """
    lot_link = await extract_lot_link(page)
    publish_date = await extract_publish_date(page)
    dates = await extract_dates(page)
    auction_status = await extract_auction_status(
        page,
        dates.get("auction_start_date", ""),
        dates.get("auction_end_date", ""),
    )
    start_price = await extract_start_price(page)
    protocol_link = await extract_protocol_link(page)
    debtor = await extract_bankrupt_info(page)
    announcement_text = await extract_announcement_text(page)

    out = {
        "lot_link": lot_link,                               # string
        "publish_date": publish_date,                       # string (could include time)
        "auction_status": auction_status,                   # string
        "auction_start_date": dates["auction_start_date"],  # string
        "auction_end_date": dates["auction_end_date"],      # string
        "application_start_date": dates["application_start_date"],  # string
        "application_end_date": dates["application_end_date"],      # string
        "start_price": float(start_price),                  # float (NaN if not found)
        "protocol_link": protocol_link,                     # string
        "bankrupt_name": debtor["bankrupt_name"],           # string
        "bankrupt_inn": debtor["bankrupt_inn"],             # string ("" if not present)
        "announcement_text": announcement_text,             # string (from div.lot_text)
    }
    return out

# ---------- Standalone runner ----------
async def _run_once(test_url: str, outfile: str):
    """
    Launch Browser, navigate, parse, and write JSON.
    Never raises to caller; always writes out a JSON with best-effort fields.
    """
    data = {
        "lot_link": "",
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
    }

    try:
        browser = Browser(headless=False, datadir="datadir")
        await browser.launch()
        try:
            page = await browser.context.new_page()
            await page.goto(test_url, wait_until="domcontentloaded")

            # Best-effort: each extractor is isolated and safe.
            # Even if one fails, others still run.
            parsed = await parse_lot(page)
            # Merge parsed values over defaults
            data.update(parsed)

        except Exception as e:
            logger.exception(f"Page navigation / parsing failure: {e}")
        finally:
            try:
                await browser.close()
            except Exception as e:
                logger.exception(f"Browser close failed: {e}")

    except Exception as e:
        logger.exception(f"Browser launch/setup failed: {e}")

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
    url = "https://tbankrot.ru/item?id=6936255"
    # Overwrite file every run, as requested
    out_path = os.path.join("debug", "lot_6936255.json")
    asyncio.run(_run_once(url, out_path))
