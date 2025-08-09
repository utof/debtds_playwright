import re
from patchright.sync_api import Page

def find_company_data(page: Page) -> dict[str, str]:
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
    tbody_locator.wait_for(timeout=10000)

    # Now, find all `tr` elements *only within that specific tbody*.
    # This prevents the loop from iterating over rows from other tables.
    row_locators = tbody_locator.locator("tr")

    # The rest of the logic remains the same
    for row in row_locators.all():
        cells = row.locator("td")
        
        if cells.count() >= 2:
            key_cell = cells.nth(0)
            value_cell = cells.nth(1)

            # Extract and clean the key
            key_text = key_cell.text_content() or ""
            key = key_text.strip().removesuffix(':').strip()

            # Extract and clean the value
            value_text = value_cell.inner_text() or ""
            value = re.sub(r'\s+', ' ', value_text).strip()

            if key:
                company_data[key] = value
                
    return company_data


def extract_main_activity(page: Page) -> dict:
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
    if p_locator.count() > 0:
        # Within that paragraph, find the link containing the activity code.
        anchor_locator = p_locator.locator("a[href*='/list?okved']")

        if anchor_locator.count() > 0:
            # Extract the code (e.g., "49.41") from the link.
            activity_code = anchor_locator.inner_text()
            
            # Get the full text of the paragraph to extract the description.
            full_text = p_locator.text_content()
            
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

def parse_financial_data(page: Page, target_indicators: list[str] | None = None) -> dict:
    """
    Parses the financial data table from the company's report page.

    Args:
        page: The Playwright page object, on a company's main page.
        target_indicators: An optional list of financial indicators to parse.
                           If provided, the function will only search for and extract these indicators.
                           If None (default), it parses all available indicators.

    Returns:
        A dictionary with financial indicators and their values over the years.
        Example: {'Выручка': {'2023': '94208', '2022': '24755'}}
    """
    report_link_locator = page.locator('a[href*="/report"]')
    if report_link_locator.count() == 0:
        return {}
    report_url = f"{page.url.rstrip('/')}/report"
    page.goto(report_url, wait_until="domcontentloaded")

    table_locator = page.locator("table#rep_table")
    table_locator.wait_for(timeout=10000)

    # Extract years from the header row
    header_row = table_locator.locator('tr:has-text("Показатель")').first
    header_cells = header_row.locator("td.tth").all_text_contents()
    
    try:
        pokazatel_index = header_cells.index('Показатель')
        years = [year.strip() for year in header_cells[pokazatel_index + 1:] if year.strip().isdigit()]
    except (ValueError, IndexError):
        return {}  # Return empty if header structure is not as expected

    financial_data = {}

    if target_indicators:
        # Optimized path: Search only for the specified indicators
        for indicator_name in target_indicators:
            # Locate the row by finding the link with the exact indicator name
            row_locator = table_locator.locator(f'tr:has(a:text-is("{indicator_name}"))')
            
            if row_locator.count() > 0:
                cells = row_locator.first.locator("td").all()
                if len(cells) == len(years) + 3:
                    financial_data[indicator_name] = {}
                    data_cells = cells[3:]
                    for i, year in enumerate(years):
                        value = (data_cells[i].text_content() or "").strip()
                        financial_data[indicator_name][year] = value
    else:
        # Original path: Iterate through all rows
        rows = table_locator.locator("tbody > tr").all()
        for row in rows:
            if "Другие показатели:" in row.inner_text():
                break

            cells = row.locator("td").all()
            if len(cells) == len(years) + 3:
                indicator_name = (cells[1].inner_text() or "").strip()
                if indicator_name:
                    financial_data[indicator_name] = {}
                    data_cells = cells[3:]
                    for i, year in enumerate(years):
                        value = (data_cells[i].text_content() or "").strip()
                        financial_data[indicator_name][year] = value
    
    return financial_data