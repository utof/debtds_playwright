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



def find_company_data(page) -> dict:
    """
    Extracts company data from the details page using the existing page instance.

    Assumes the page is already navigated to the company's detail page.

    Args:
        page: The Playwright page object.

    Returns:
        A dictionary containing the extracted key-value pairs.
    """
    company_data = {}

    try:
        # Locate the main table body containing the data
        # This selector targets the tbody within the main content div
        tbody_locator = page.locator("tbody").first
        
        # Wait for the table body to be visible (adjust timeout if needed)
        tbody_locator.wait_for(timeout=10000) # Wait up to 10 seconds

        # Find all rows within the tbody
        row_locators = tbody_locator.locator("tr").all()

        for row_locator in row_locators:
            # Find the two td elements within the current row
            td_locators = row_locator.locator("td").all()
            
            # Ensure there are exactly two cells (key and value)
            if len(td_locators) >= 2:
                key_cell = td_locators[0]
                value_cell = td_locators[1]

                # --- Extract and Clean Key ---
                # Get the inner text of the key cell
                # inner_text() often handles whitespace better than text_content() for visible text
                raw_key_text = key_cell.inner_text(timeout=5000).strip() 
                
                # Use regex to extract the main label part, removing potential icon prefixes or trailing colons
                # This pattern looks for text after the last ')' or ':' which often precedes the label.
                # It also tries to remove common icon indicators if they appear at the start.
                key_parts = re.split(r'[:)]\s*', raw_key_text)
                if key_parts:
                    cleaned_key = key_parts[-1].strip() # Get the last part after split
                    # Further cleanup: remove common icon text prefixes (basic example)
                    # You might need to expand this list based on icons seen
                    cleaned_key = re.sub(r'^(fa-[\w\-]+\s*)+', '', cleaned_key, flags=re.IGNORECASE).strip(': \t\n\r')
                    key = cleaned_key
                else:
                    key = raw_key_text # Fallback if regex fails

                # --- Extract Value ---
                value = ""
                # Check for links within the value cell first
                link_locators = value_cell.get_by_role("link").all() # Find all links
                if link_locators:
                    # Prioritize the text of the first link
                    value = link_locators[0].inner_text(timeout=5000).strip()
                    # If you also need the href attribute later:
                    # link_href = link_locators[0].get_attribute('href')
                    # value = {"text": value, "link": link_href} # Example structure if needed
                else:
                    # Get the text directly from the cell if no links
                    value = value_cell.inner_text(timeout=5000).strip()

                # Store the key-value pair
                # Handle potential duplicate keys if they occur in the table structure
                if key in company_data:
                    # Example: Convert to list or append (simple overwrite shown here)
                    # For robustness, check type and append to list if already a list
                    if not isinstance(company_data[key], list):
                        company_data[key] = [company_data[key]]
                    company_data[key].append(value)
                else:
                     company_data[key] = value

        return company_data

    except Exception as e:
        print(f"An error occurred while extracting company data: {e}")
        # Optionally re-raise or return an empty dict/error indicator
        # raise 
        return {} # Return empty dict on error


if __name__ == "__main__":
    inn = "0263012310"
    with sync_playwright() as playwright:
        run(playwright, inn)