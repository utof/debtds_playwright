from patchright.sync_api import Browser as PlaywrightBrowser
from loguru import logger
import json
import os
import datetime

from .flows import (
    click_ceos, 
    extract_ceos, 
    click_beneficiaries, 
    extract_beneficiaries,
)
from .login import login
from .court_debts import extract_defendant_in_progress
from ..utils import process_inn
from ..browser import Browser

def run_test(browser: PlaywrightBrowser, inn: str) -> dict:
    """
    Tests the CEO and Beneficiary extraction flow on zachestnyibiznes.ru.

    Args:
        browser: The Playwright browser instance from the Browser wrapper.
        inn: The company's INN.

    Returns:
        A dictionary containing the extracted CEO and beneficiary data.
    """
    inn = process_inn(inn)
    logger.info(f"Starting test run for INN: {inn}")

    page = browser.new_page()
    logger.debug("New page created.")

    results = {
        "ceos": {},
        "beneficiaries": {},
        "defendant_in_progress": {}  # + new field
    }

    try:
        if not login(page):
            return {}
        
        logger.info(f"Navigating to search page for INN: {inn}")
        page.goto(f"https://zachestnyibiznes.ru/search?query={inn}", wait_until='domcontentloaded')

        company_link_locator = page.locator(f'a[href*="/company/ul/"]:visible').first
        if company_link_locator.count() == 0:
            logger.warning("No visible company link found on the search results page.")
            return {}

        logger.info("Company link found, navigating to company page.")
        company_link_locator.click()
        page.wait_for_load_state("domcontentloaded")
        logger.success("Successfully navigated to the company page.")

        if click_ceos(page):
            results["ceos"] = extract_ceos(page)
            page.keyboard.press("Escape")
            logger.info("CEO modal processed and closed.")
        else:
            logger.warning("Could not open or find the CEO modal.")

        if click_beneficiaries(page):
            results["beneficiaries"] = extract_beneficiaries(page)
            page.keyboard.press("Escape")
            logger.info("Beneficiaries modal processed and closed.")
        else:
            logger.warning("Could not open or find the beneficiaries modal.")

        # + new extraction (no modal)
        results["defendant_in_progress"] = extract_defendant_in_progress(page)

        return results

    except Exception as e:
        logger.exception(f"An error occurred during the test run for INN {inn}: {e}")
        os.makedirs("data/screenshots", exist_ok=True)
        page.screenshot(path=f"data/screenshots/error_{inn}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        return {"error": str(e)}
    
    finally:
        page.close()
        logger.debug("Page closed.")


if __name__ == "__main__":
    test_inn = "3123109532"
    
    log_file = f"data/logs/test_runs_{datetime.datetime.now().strftime('%Y-%m-%d')}.log"
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger.add(log_file, rotation="1 day", level="INFO")

    logger.info(f"--- Starting new test session for INN: {test_inn} ---")
    
    try:
        with Browser() as browser:
            final_data = run_test(browser, test_inn)
            output_filename = f"data/output/{test_inn}_test_data.json"
            os.makedirs(os.path.dirname(output_filename), exist_ok=True)
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(final_data, f, ensure_ascii=False, indent=4)
            logger.success(f"Test run complete. Data saved to {output_filename}")
            print(json.dumps(final_data, ensure_ascii=False, indent=4))

    except Exception as e:
        logger.exception(f"A critical error occurred in the main execution block: {e}")
        raise
