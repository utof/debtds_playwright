import re
from patchright.sync_api import Page
from loguru import logger

def click_beneficiaries(page: Page) -> bool:
    """
    Finds and clicks the link to open the beneficiaries modal using a robust selector.
    It waits for the modal to become visible after the click.

    Args:
        page: The Playwright page object.

    Returns:
        True if the link was clicked and the modal appeared, False otherwise.
    """
    # UPDATED: Use the 'contains' attribute selector (*=) to find the link
    # even if the data-title attribute contains complex HTML.
    link_locator = page.locator('a[data-title*="Бенефициары"]')
    
    if link_locator.count() == 0:
        logger.warning("The 'Beneficiaries' link was not found on the page.")
        return False

    try:
        logger.info("Clicking the 'Beneficiaries' link...")
        link_locator.first.click()
        
        # Wait for the modal to appear. We identify it by its title.
        modal_title_locator = page.locator("div.modal-title:has-text('Бенефициары')")
        modal_title_locator.wait_for(state="visible", timeout=5000)
        
        logger.success("Successfully clicked the link and the beneficiaries modal is visible.")
        return True
    except TimeoutError:
        # This can happen if the modal is a "premium feature" pop-up.
        # We check for that specific case.
        premium_modal = page.locator("div.modal-title:has-text('доступны в тарифах')")
        if premium_modal.count() > 0:
            logger.warning("Beneficiaries are a premium feature for this company. Cannot extract data.")
            return False
        logger.error("Timed out waiting for the beneficiaries modal to appear after clicking.")
        return False
    except Exception as e:
        logger.error(f"An error occurred while trying to open the beneficiaries modal: {e}")
        return False
    
    
def click_ceos(page: Page) -> bool:
    """
    Finds and clicks the link to open the CEO history modal.

    It waits for the modal to become visible after the click.

    Args:
        page: The Playwright page object.

    Returns:
        True if the link was clicked and the modal appeared, False otherwise.
    """
    # Use a 'starts-with' selector for the data-title to make it more robust,
    # as the company name might change.
    link_locator = page.locator('a[data-title*="История изменений руководителей"]')
    
    if link_locator.count() == 0:
        logger.warning("The 'CEO History' link was not found on the page.")
        return False

    try:
        logger.info("Clicking the 'CEO History' link...")
        link_locator.click()

        # Wait for the modal, identified by its title, to become visible.
        modal_title_locator = page.locator("div.modal-title:has-text('История изменений руководителей')")
        modal_title_locator.wait_for(state="visible", timeout=5000)

        logger.success("Successfully clicked the link and the CEO history modal is visible.")
        return True
    except TimeoutError:
        logger.error("Timed out waiting for the CEO history modal to appear after clicking the link.")
        return False
    except Exception as e:
        logger.error(f"An error occurred while trying to open the CEO history modal: {e}")
        return False

def extract_beneficiaries(page: Page) -> dict:
    """
    Finds the 'Бенефициары' (Beneficiaries) modal on the page and extracts data from its table.

    This function specifically targets the modal by its title, making the selector robust.
    If the modal or table is not found, it returns an empty dictionary.

    Args:
        page: The Playwright page object.

    Returns:
        A dictionary of beneficiaries, keyed by their row number.
        Example: {"1": {"фио": "Иванов Иван", "связь": "Прямая", "инн": "123...", "доля": "100%"}}
    """
    beneficiaries = {}
    
    # Locate the modal by finding the header that contains the exact text "Бенефициары"
    # and then navigate up to the main modal content container.
    modal_locator = page.locator("div.modal-content:has(div.modal-title:text-is('Бенефициары'))")

    if modal_locator.count() == 0:
        logger.info("Beneficiaries modal not found on the page.")
        return {}
        
    # Find all data rows (tr) in the table, skipping the header row (th)
    rows = modal_locator.locator("table.founders-table tbody tr:has(td)").all()

    if not rows:
        logger.warning("Beneficiaries table found, but it contains no data rows.")
        return {}

    for row in rows:
        cells = row.locator("td").all()
        if len(cells) >= 5:
            try:
                row_num = (cells[0].text_content() or "").strip()
                fio = (cells[1].locator("a").first.text_content() or "").strip()
                svyaz = (cells[2].text_content() or "").strip()
                inn = (cells[3].text_content() or "").strip()
                dolya = (cells[4].text_content() or "").strip()

                if row_num:
                    beneficiaries[row_num] = {
                        "фио": fio,
                        "связь": svyaz,
                        "инн": inn,
                        "доля": dolya
                    }
            except Exception as e:
                logger.error(f"Could not parse a beneficiary row. HTML: {row.inner_html()}. Error: {e}")

    logger.info(f"Extracted {len(beneficiaries)} beneficiaries.")
    return beneficiaries

def extract_ceos(page: Page) -> dict:
    """
    Finds the modal for 'История изменений руководителей' (History of CEO changes)
    and extracts the data, organizing it by date.

    Args:
        page: The Playwright page object.

    Returns:
        A dictionary where keys are dates and values are lists of CEOs for that date.
        Example: {"21.03.2025": [{"должность": "КОНКУРСНЫЙ УПРАВЛЯЮЩИЙ", ...}]}
    """
    ceos_by_date = {}
    
    # Locate the modal by its unique title text
    modal_locator = page.locator("div.modal-content:has(div.modal-title:has-text('История изменений руководителей'))")
    # modal_locator = page.locator("История изменений руководителей")
    
    if modal_locator.count() == 0:
        logger.info("CEO history modal not found on the page.")
        return {}
        
    # The data is structured in separate tbody elements, one for each date.
    date_chunks = modal_locator.locator("tbody[id*='history-founder-chunk-']").all()

    if not date_chunks:
        logger.warning("CEO history modal found, but no date chunks were located.")
        return {}

    for chunk in date_chunks:
        # Extract the date from the first row of the chunk
        date_row = chunk.locator("tr.attr-date").first
        date_anchor = date_row.locator("a[href*='/ordering?date=']").first
        
        if date_anchor.count() == 0:
            continue
            
        date_str = (date_anchor.text_content() or "").strip()
        
        # Find all actual data rows within this chunk
        data_rows = chunk.locator("tr:not(.attr-date)").all()
        
        if date_str not in ceos_by_date:
            ceos_by_date[date_str] = []

        for row in data_rows:
            cells = row.locator("td").all()
            if len(cells) >= 4:
                try:
                    # Extract data using the 'data-th' attribute as a fallback guide
                    position = (cells[1].text_content() or "").strip()
                    name = (cells[2].text_content() or "").strip()
                    inn = (cells[3].text_content() or "").strip()

                    ceos_by_date[date_str].append({
                        "должность": position,
                        "руководитель": name,
                        "инн": inn
                    })
                except Exception as e:
                    logger.error(f"Could not parse a CEO row. HTML: {row.inner_html()}. Error: {e}")

    logger.info(f"Extracted CEO history for {len(ceos_by_date)} dates.")
    return ceos_by_date