import asyncio
import datetime
import json
import os
import re

from loguru import logger
from patchright.async_api import Browser as PlaywrightBrowser
from patchright.async_api import Page
from typing_extensions import OrderedDict

from ..browser import Browser
from ..nalog_ru import is_disqualified_on
from ..utils import calculate_financial_coefficients, process_inn
from .flows import (
    extract_founders,
    extract_main_activity,
    find_company_data,
    find_inn_by_orgn,
    handle_captcha,
    parse_financial_data,
)

_PERCENT_RE = re.compile(r'([0-9]+(?:[.,][0-9]+)?)\s*%')

def _parse_share_percent(s: str | None) -> float | None:
    if not s:
        return None
    m = _PERCENT_RE.search(str(s))
    if not m:
        return None
    return float(m.group(1).replace(',', '.'))

def _normalize_name(s: str | None) -> str:
    if not s:
        return ''
    # Collapse spaces, uppercase for robust deduping
    return re.sub(r'\s+', ' ', s).strip().upper()

def _is_konkursny(text: str | None) -> bool:
    if not text:
        return False
    t = text.lower()
    # robust contains check (covers cases like "конкурсный управляющий", "и.о. конкурсного управляющего", etc.)
    return 'конкурсн' in t and 'управля' in t

async def _goto_search_and_validate(
    browser: Browser, value: str | int
) -> tuple[Page, bool]:
    """
    Navigates to list-org.com search by INN or ORGN and handles captcha.

    Returns:
        Tuple[Page, bool]: The page object and a boolean indicating if results were found.
    """
    page = await browser.goto_with_retry(
        f"https://www.list-org.com/search?val={value}", wait_until="domcontentloaded"
    )
    await handle_captcha(page)

    if await page.locator("p:has-text('Найдено 0 организаций')").count() > 0:
        logger.warning(f"No organizations found for search value={value}")
        return page, False
    return page, True

async def run(
    browser: Browser,
    inn: str,
    method: str,
    years_filter: str | None = None,
    publish_date: str | None = None,
    orgn: str | None = None,
    codes_filter: str | None = None,
) -> dict:
    """
    Scrapes company data from list-org.com based on the INN.

    Args:
        browser: The Playwright browser instance.
        inn: The company's INN.
        method: The type of data to retrieve ('card' or 'finances').

    Returns:
        A dictionary containing the requested company data.
    """
    inn = process_inn(inn) if inn else inn
    logger.info(f"Processing method={method} for INN={inn} ORGN={orgn}")

    # Don't create page here - _goto_search_and_validate will create and return one
    page = None
    
    try:
        # ---- ORGN → INN mode ----
        if method == "find_inn_by_orgn":
            if orgn is None or str(orgn).strip() in ("", "0"):
                return {"data": "оргн пуст"}

            page, found = await _goto_search_and_validate(browser, orgn)
            if not found:
                return {"data": "нет данных о компании"}

            data = await find_inn_by_orgn(page, orgn)
            return {"data": data}

        # ---- INN-based modes ----
        page, found = await _goto_search_and_validate(browser, inn)
        if not found:
            return {"data": "нет данных о компании"}
        
        # Navigate to the company page
        await page.locator("a[href*='/company/']").first.click()
        await page.wait_for_load_state("domcontentloaded")
        await handle_captcha(page)

        if method == 'finances':
            if codes_filter:
                code_parts = [code.strip() for code in codes_filter.split(',')]
                required_codes = []
                for part in code_parts:
                    if part.startswith('24'):
                        required_codes.append(f'Ф2.{part}')
                    else:
                        required_codes.append(f'Ф1.{part}')
            else:
                required_codes = [
                    'Ф1.1200', 'Ф1.1240', 'Ф1.1250', 'Ф1.1400', 
                    'Ф1.1500', 'Ф1.1520', 'Ф1.1530', 'Ф1.1600', 'Ф2.2400']

            financial_data = await parse_financial_data(page, required_codes, years_filter)
            logger.info(f"Successfully retrieved financial data for INN: {inn}")
            coefficients = calculate_financial_coefficients(financial_data)
            return {"financials": financial_data, "coefficients": coefficients}

        elif method == 'card':
            company_data = await find_company_data(page)
            main_activity = await extract_main_activity(page)
            # Combine the results into a single dictionary
            result = {**company_data, "main_activity": main_activity}
            logger.info(f"Successfully retrieved card data for INN: {inn}")
            return result
        
        elif method == 'rdl':
            if not publish_date:
                return {"error": "publish_date is required in format dd.mm.yyyy"}

            # 1) On the same list-org page: get CEO + founders
            company_data = await find_company_data(page)  # expected: {"Руководитель": {"должность": "...", "имя": "..."}, ...}
            founders_block = await extract_founders(page) # expected: {"Учредители": [ { "учредитель": "...", "доля": "42.8%", ... }, ... ]}

            # Defensive compatibility with earlier schema variants
            ceo_obj = None
            if isinstance(company_data, dict):
                ceo_obj = company_data.get("Руководитель") or company_data.get("ceo") or {}
            ceo_name = (
                (ceo_obj.get("имя") if isinstance(ceo_obj, dict) else None)
                or (ceo_obj.get("name") if isinstance(ceo_obj, dict) else None)
                or (ceo_obj.get("руководитель") if isinstance(ceo_obj, dict) else None)
            )
            ceo_position = (
                (ceo_obj.get("должность") if isinstance(ceo_obj, dict) else None)
                or (ceo_obj.get("position") if isinstance(ceo_obj, dict) else None)
            )

            founders_list = []
            if isinstance(founders_block, dict):
                founders_list = founders_block.get("Учредители") or founders_block.get("founders") or []
            elif isinstance(founders_block, list):
                founders_list = founders_block

            # 2) Build ordered, unique list of names — CEO first (if not конкурсный), then founders with share ≥ 20%
            ordered_names: list[str] = []
            seen = set()

            # Include CEO first unless "конкурсный управляющий" in name/position
            include_ceo = bool(ceo_name) and not (_is_konkursny(ceo_name) or _is_konkursny(ceo_position))
            if include_ceo:
                nkey = _normalize_name(ceo_name)
                if nkey and nkey not in seen:
                    ordered_names.append(ceo_name.strip())
                    seen.add(nkey)

            # Founders (≥20%)
            for f in founders_list or []:
                try:
                    fname = (f.get("учредитель") or f.get("founder") or "").strip()
                    share = _parse_share_percent(f.get("доля") or f.get("share_percent"))
                    # keep only share >= 20%
                    if not fname or share is None or share < 20.0:
                        continue
                    nkey = _normalize_name(fname)
                    if nkey not in seen:
                        ordered_names.append(fname)
                        seen.add(nkey)
                except Exception:
                    # Be permissive; skip malformed rows
                    continue

            # 3) Run is_disqualified_on for each name on publish_date (dedicated page for nalog service)
            input_data: "OrderedDict[str, bool]" = OrderedDict()
            check_page: Page | None = None
            try:
                check_page = await browser.context.new_page()
                for idx, person in enumerate(ordered_names):
                    try:
                        res = await is_disqualified_on(check_page, person, publish_date)
                    except Exception as e1:
                        logger.warning(f"is_disqualified_on failed for '{person}' (1st try) on {publish_date}: {e1}")
                        try:
                            res = await is_disqualified_on(check_page, person, publish_date)
                        except Exception as e2:
                            logger.error(f"is_disqualified_on failed again for '{person}' on {publish_date}: {e2}")
                            return {"error": f"is_disqualified_on failed for '{person}' twice: {e2}"}

                    # Decide label
                    role_parts = []
                    if include_ceo and idx == 0:  # first entry is always CEO if included
                        role_parts.append("CEO")
                    # check if this same person also appeared as founder (>=20%)
                    if person in [f.get("учредитель") or f.get("founder") for f in founders_list]:
                        role_parts.append("Основатель")

                    if role_parts:
                        label = f"{', '.join(role_parts)}: {person}"
                    else:
                        label = person

                    input_data[label] = bool(res)
            finally:
                if check_page:
                    await check_page.close()

            # 4) Aggregations per spec
            # CEO_RDL:
            ceo_rdl = "нет"
            if include_ceo:
                # The CEO is the FIRST key in input_data by construction
                first_person = next(iter(input_data.keys()), None)
                if first_person is not None:
                    ceo_rdl = "да" if input_data.get(first_person, False) else "нет"
                else:
                    ceo_rdl = "нет"  # no checks ran (unlikely if include_ceo True)
            else:
                ceo_rdl = "нет"  # CEO skipped (конкурсный управляющий or missing)

            # Founders_RDL: any founder True
            founders_any = False
            # Slice everything after CEO if CEO included; otherwise from start
            names_iter = list(input_data.items())
            start_idx = 1 if include_ceo else 0
            for _, val in names_iter[start_idx:]:
                if val:
                    founders_any = True
                    break
            founders_rdl = "да" if founders_any else "нет"

            final_rdl = "да" if (ceo_rdl == "да" or founders_rdl == "да") else "нет"

            payload = {
                "debtor_inn": inn,
                "CEO_RDL": ceo_rdl,
                "Founders_RDL": founders_rdl,
                "final_RDL": final_rdl,
                "input_data": input_data,  # OrderedDict preserves CEO-first order
            }
            logger.info(f"RDL check complete for INN {inn}: {payload}")
            return payload
        
        else:
            # Handle invalid method
            logger.error(f"Invalid method specified: {method}")
            return {"error": "Invalid method specified."}

    except Exception as e:
        logger.exception(f"An error occurred during scraping for INN {inn}: {e}")
        if page:
            await page.screenshot(path=f"error_{inn}.png")
        return {"error": str(e)}
    
    finally:
        if page:
            await page.close()
            logger.debug("Page closed.")


async def main():
    # inn = "1400013278"
    inn = "6312126585" # RDL simple
    inn = "3328452719" # RDL complex
    try:
        browser = Browser(headless=False, datadir="datadir")
        await browser.launch()
        try:
            jsonn = await run(browser, inn, "rdl", publish_date="26.03.2025")
        finally:
            with open(f"{inn}_founders_data.json", "w", encoding="utf-8") as f:
                json.dump(jsonn, f, ensure_ascii=False, indent=4)
            logger.info(f"Data for INN {inn} written to {inn}_founders_data.json")
            await browser.close()
    except Exception as e:
        logger.exception(f"Unhandled exception in main execution: {e}")
        # Save error details to timestamped file
        os.makedirs("data/error_logs", exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        error_file = f"data/error_logs/error_{timestamp}.log"
        logger.add(error_file, level="ERROR")
        logger.error(f"Error details: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())