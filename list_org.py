import re
from patchright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright, inn: str) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = browser.new_page()
    page.goto(f"https://www.list-org.com/search?val={inn}")
    # page.wait_for_load_state("domcontentloaded", timeout=40000)
    # page.get_by_role("link", name="ООО \"ТРАНССПЕЦСЕРВИС\"").click() #1
    link = page.locator("a[href*='/company/']").first
    link.wait_for()  # Waits until the element is attached and visible
    link.click()
    # page.wait_for_load_state("domcontentloaded", timeout=40000)
    company_card = find_company_data(page)
    print(company_card)
    page.get_by_text("Полное юридическое наименование:").click() #2
    page.get_by_text("Основной (по коду ОКВЭД ред.2): 49.41").click() #3

    # ---------------------
    context.close()
    browser.close()



def find_company_data(page) -> dict[str, str]:
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
if __name__ == "__main__":
    inn = "0263012310"
    with sync_playwright() as playwright:
        run(playwright, inn)