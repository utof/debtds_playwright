import re
from patchright.async_api import Page
from dotenv import load_dotenv
import os
from twocaptcha import TwoCaptcha
from loguru import logger
import asyncio

load_dotenv()

async def find_company_data(page: Page) -> dict[str, str]:
    """
    Extracts company data from a details page using a robust and universal algorithm.
    This function specifically targets the main details table by looking for an anchor text.

    Args:
        page: The Playwright page object, already navigated to the company's detail page.

    Returns:
        A dictionary containing the extracted key-value pairs from the table.
    """
    company_data = {}

    # --- THIS IS THE KEY CHANGE ---
    # Use a more specific locator to find the correct tbody.
    # The :has-text() pseudo-class ensures we select the tbody that contains
    # the unique text "Полное юридическое наименование:", anchoring our search.
    tbody_locator = page.locator('tbody:has-text("Полное юридическое наименование:")')
    
    # Wait for this specific table body to be visible to ensure it has loaded.
    await tbody_locator.wait_for(timeout=10000)

    # Now, find all `tr` elements *only within that specific tbody*.
    # This prevents the loop from iterating over rows from other tables.
    row_locators = tbody_locator.locator("tr")

    # The rest of the logic remains the same
    for row in await row_locators.all():
        cells = row.locator("td")
        
        if await cells.count() >= 2:
            key_cell = cells.nth(0)
            value_cell = cells.nth(1)

            # Extract and clean the key
            key_text = await key_cell.text_content() or ""
            key = key_text.strip().removesuffix(':').strip()

            # Extract and clean the value
            value_text = await value_cell.inner_text() or ""
            value = re.sub(r'\s+', ' ', value_text).strip()

            if not key:
                continue

            # --- CEO extraction (special case) ---
            # If this row is "Руководитель", DO NOT store the flat string to avoid redundancy.
            # Instead, extract a structured object and put it under "ceo".
            if key == "Руководитель":
                try:
                    pos_loc = value_cell.locator("span.upper").first
                    name_loc = value_cell.locator("a.upper").first

                    position = (await pos_loc.inner_text() or "").strip() if await pos_loc.count() > 0 else ""
                    person = (await name_loc.inner_text() or "").strip() if await name_loc.count() > 0 else ""

                    # Only set if we have at least one meaningful value
                    if position or person:
                        company_data["Руководитель"] = {
                            "должность": position,
                            "имя": person, 
                        }
                except Exception:
                    # Don't fail the whole card parse if CEO parsing hiccups
                    pass
                continue  # Skip assigning company_data["Руководитель"] = value

            # Default behavior for regular rows
            company_data[key] = value
                
    return company_data


import re
from playwright.async_api import Page

async def extract_founders(page: Page) -> dict:
    """
    Extracts founders from the '#founders' card.

    Returns:
        {
          "Учредители": [
            {"учредитель": "...", "инн": "...", "доля": "...", "доля_руб": "..."},
            ...
          ]
        }
        or {} if the section isn't present.
    """
    founders_card = page.locator("div#founders")
    if await founders_card.count() == 0:
        return {}

    # Ensure the card is visible/loaded.
    await founders_card.wait_for(state="visible", timeout=10000)

    def clean(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    rows = founders_card.locator("table tbody tr")
    items: list[dict[str, str]] = []

    for row in await rows.all():
        # Skip header rows (td.tth) and the "...показать все..." row (typically <td colspan>).
        if await row.locator("td.tth").count() > 0:
            continue
        cells = row.locator("td")
        cell_count = await cells.count()
        if cell_count < 3:
            continue  # nothing to parse

        # Map columns robustly:
        #  - Most pages: 4 tds => name, inn, share, amount
        #  - Compact layouts may hide INN => 3 tds => name, share, amount
        if cell_count >= 4:
            name_el, inn_el, share_el, amount_el = cells.nth(0), cells.nth(1), cells.nth(2), cells.nth(3)
            inn_text = await inn_el.inner_text()
        else:  # cell_count == 3
            name_el, share_el, amount_el = cells.nth(0), cells.nth(1), cells.nth(2)
            inn_text = ""

        name_text = await name_el.inner_text()
        share_text = await share_el.inner_text()
        amount_text = await amount_el.inner_text()

        name = clean(name_text or "")
        if not name:
            continue  # skip malformed row

        item = {
            "учредитель": name,
            "инн": clean(inn_text or ""),
            "доля": clean(share_text or ""),
            "доля_руб": clean(amount_text or ""),
        }
        items.append(item)

    return {"Учредители": items} if items else {}


async def extract_main_activity(page: Page) -> dict:
    """
    Extracts the main business activity (ОКВЭД) from the company details page.

    It finds the paragraph containing the main activity, extracts the code from
    a specific link, and then gets the descriptive text that follows.

    Args:
        page: The Playwright page object, assumed to be on the company details page.

    Returns:
        A dictionary with the main activity, or an empty dictionary if not found.
        Example: {"Основная деятельность": "49.41 - Деятельность автомобильного грузового транспорта"}
    """
    # Locator for the paragraph containing the main activity information.
    # :has-text() makes this very specific and robust.
    p_locator = page.locator('p:has-text("Основной (по коду ОКВЭД ред.2)")')

    # Check if the element exists on the page before trying to extract data.
    if await p_locator.count() > 0:
        # Within that paragraph, find the link containing the activity code.
        anchor_locator = p_locator.locator("a[href*='/list?okved']")

        if await anchor_locator.count() > 0:
            # Extract the code (e.g., "49.41") from the link.
            activity_code = await anchor_locator.inner_text()
            
            # Get the full text of the paragraph to extract the description.
            full_text = await p_locator.text_content()
            
            description = ""
            # Split the string by the activity code to isolate the description part.
            parts = full_text.split(activity_code, 1)
            if len(parts) > 1:
                # The description is the second part of the split.
                # Clean it by removing leading/trailing whitespace and the hyphen.
                description = parts[1].strip().removeprefix('-').strip()

            # Format the final string. If a description exists, combine them.
            final_value = f"{activity_code} - {description}" if description else activity_code
            
            return {"Основная деятельность": final_value}

    # Return an empty dictionary if the main activity section wasn't found.
    return {}

async def parse_financial_data(page: Page, target_indicators: list[str] | None = None, years_filter: str | None = None) -> dict:
    """
    Parses the financial data table from the company's report page.
    The data is keyed by the financial indicator code.

    Args:
        page: The Playwright page object, on a company's main page.
        target_indicators: An optional list of financial indicators (names or codes) to parse.
                           If provided, only these indicators are extracted.
        years_filter: An optional string to filter columns by year.
                      Examples: "2020,2021" or "2020:".

    Returns:
        A dictionary with financial indicators and their values over the years, keyed by indicator code.
        Example: {'Ф2.2110': {'name': 'Выручка', 'values': {'2023': '94208', '2022': '24755'}}}
    """
    report_link_locator = page.locator('a[href*="/report"]')
    if await report_link_locator.count() == 0:
        logger.warning("No report link found on the page.")
        return {}
    
    report_url = f"{page.url.rstrip('/')}/report"
    await page.goto(report_url, wait_until="domcontentloaded")
    
    await handle_captcha(page) # Check for captcha on the report page

    try:
        table_locator = page.locator("table#rep_table")
        await table_locator.wait_for(timeout=10000)
    except Exception:
        logger.error("Financial report table (#rep_table) not found on the page.")
        return {}

    # --- MODIFIED: Extract and filter years ---
    header_row = table_locator.locator('tr:has-text("Показатель")').first
    header_cells_locators = header_row.locator("td.tth")
    all_header_texts = await header_cells_locators.all_text_contents()
    
    try:
        pokazatel_index = all_header_texts.index('Показатель')
        # Store original years and their column indices relative to the start of year columns
        original_years_with_indices = {
            year.strip(): i for i, year in enumerate(all_header_texts[pokazatel_index + 1:]) if year.strip().isdigit()
        }
        all_original_years = list(original_years_with_indices.keys())
    except (ValueError, IndexError):
        logger.error("Could not parse years from the table header.")
        return {}

    # Apply year filtering
    target_years = all_original_years
    if years_filter:
        if ':' in years_filter:
            start_year = int(years_filter.strip().replace(':', ''))
            target_years = [y for y in all_original_years if int(y) >= start_year]
        else:
            filter_years_set = {y.strip() for y in years_filter.split(',')}
            target_years = [y for y in all_original_years if y in filter_years_set]
    
    # Map target years back to their column indices
    year_indices_to_extract = {original_years_with_indices[y]: y for y in target_years}
    # --- END MODIFICATION ---

    financial_data = {}

    async def parse_row(row_locator) -> tuple[str | None, dict | None]:
        """
        Helper function to parse a single row locator.
        This is now more robust and doesn't rely on fixed cell indices for code/name.
        """
        all_cells = await row_locator.locator("td").all()
        if not all_cells or len(all_cells) < 3:
            return None, None

        # Explicitly find the code: the first 'td' with class 'tt_hide'
        code_cell = row_locator.locator("td.tt_hide").first
        code = (await code_cell.text_content() or "").strip()

        # Explicitly find the name: the 'td' that contains an 'a' tag
        name_cell = row_locator.locator("td > a").first
        name_html = (await name_cell.inner_html() or "").strip()
        name = re.sub('<[^<]+?>', '', name_html).strip()

        if not code or not name:
            logger.warning(f"Could not parse code or name for a row. HTML: {await row_locator.inner_html()}")
            return None, None

        # Data cells start after the first three columns (code, name, unit)
        data_cells = all_cells[3:]
        values = {}
        for i, year in year_indices_to_extract.items():
            if i < len(data_cells):
                value = (await data_cells[i].text_content() or "").strip()
                values[year] = value
        
        return code, {"name": name, "values": values}

    if target_indicators:
        # Optimized path: Search only for the specified indicators by name or code
        for indicator in target_indicators:
            logger.info(f"Processing target indicator: {indicator}")
            # Use a comma for OR condition, separating two full selectors.
            selector = f'tr:has(a:text-is("{indicator}")), tr:has(td.tt_hide:text-is("{indicator}"))'
            rows = table_locator.locator(selector)
            if await rows.count() > 0:
                row_locator = rows.first
                code, data = await parse_row(row_locator)
                if code and data:
                    financial_data[code] = data
            else:
                logger.warning(f"Could not find row for target indicator: {indicator}")

    else:
        # Original path: Iterate through all rows
        rows = await table_locator.locator("tbody > tr").all()
        for row in rows:
            if "Другие показатели:" in await row.inner_text():
                break
            
            # Skip header-like rows that don't contain the necessary structure
            if await row.locator("td.tt_hide").count() == 0 or await row.locator("td > a").count() == 0:
                continue

            code, data = await parse_row(row)
            if code and data:
                financial_data[code] = data
    
    return financial_data

async def handle_captcha(page: Page):
    """
    Detects and solves a reCAPTCHA v2 on the page.
    """
    captcha_locator = page.locator("span.h1:has-text('Проверка, что Вы не робот')")
    if await captcha_locator.count() > 0:
        logger.info("Captcha detected, attempting to solve...")
        
        # 1. Get website details for 2Captcha
        website_url = page.url
        sitekey_locator = page.locator(".g-recaptcha")
        sitekey = await sitekey_locator.get_attribute("data-sitekey")

        if not sitekey:
            logger.warning("Could not find reCAPTCHA sitekey.")
            return

        # 2. Solve reCAPTCHA using 2Captcha
        # Make sure to set the APIKEY_2CAPTCHA environment variable
        api_key = os.getenv('APIKEY_2CAPTCHA')
        if not api_key:
            raise ValueError("APIKEY_2CAPTCHA environment variable is not set.")
            
        solver = TwoCaptcha(api_key)
        
        try:
            logger.info(f"Submitting captcha to 2Captcha for URL: {website_url} with sitekey: {sitekey}")
            # Run the blocking call in a separate thread
            result = await asyncio.to_thread(solver.recaptcha, sitekey=sitekey, url=website_url)
            
            if result and 'code' in result:
                token = result['code']
                logger.info("Captcha solved, token received.")
                
                # 3. Inject the token and submit the form
                await page.evaluate(f"document.getElementById('g-recaptcha-response').innerHTML = '{token}';")
                await page.locator('input[type="submit"][name="submit"]').click()
                
                logger.info("Submitted captcha. Waiting for navigation...")
                await page.wait_for_load_state('domcontentloaded', timeout=60000)
                logger.info("Page reloaded after captcha.")
            else:
                logger.warning("2Captcha did not return a valid solution.")

        except Exception as e:
            logger.error(f"An error occurred while solving captcha: {e}")