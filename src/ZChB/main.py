from patchright.sync_api import Browser as PlaywrightBrowser
from loguru import logger
import json
import os
import datetime

# Assuming flows.py and utils.py are in the same directory or a reachable path
# Using relative imports to match the second file's style
from .flows import (
    handle_captcha, 
    click_ceos, 
    extract_ceos, 
    click_beneficiaries, 
    extract_beneficiaries
)
from .utils import process_inn
# Assuming a Browser wrapper class exists in a parent directory, similar to the second file
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
        "beneficiaries": {}
    }

    try:
        # 1. Navigate to the search page and handle captcha
        logger.info(f"Navigating to search page for INN: {inn}")
        page.goto(f"https://zachestnyibiznes.ru/search?query={inn}", wait_until='domcontentloaded')
        handle_captcha(page)

        # 2. Find the correct, visible link to the company page
        company_link_locator = page.locator(f'a[href*="/company/ul/"]:visible').first
        
        if company_link_locator.count() == 0:
            logger.warning("No visible company link found on the search results page.")
            return {}

        # 3. Click the link and go to the company page
        logger.info("Company link found, navigating to company page.")
        company_link_locator.click()
        page.wait_for_load_state("domcontentloaded")
        handle_captcha(page)
        logger.success("Successfully navigated to the company page.")

        # 4. Process CEOs
        if click_ceos(page):
            results["ceos"] = extract_ceos(page)
            # Close the modal by pressing the Escape key to avoid interference
            page.keyboard.press("Escape")
            logger.info("CEO modal processed and closed.")
        else:
            logger.warning("Could not open or find the CEO modal.")

        # 5. Process Beneficiaries
        if click_beneficiaries(page):
            results["beneficiaries"] = extract_beneficiaries(page)
            # Close the modal
            page.keyboard.press("Escape")
            logger.info("Beneficiaries modal processed and closed.")
        else:
            logger.warning("Could not open or find the beneficiaries modal.")

        return results

    except Exception as e:
        logger.exception(f"An error occurred during the test run for INN {inn}: {e}")
        # Save a screenshot for debugging
        os.makedirs("data/screenshots", exist_ok=True)
        page.screenshot(path=f"data/screenshots/error_{inn}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        return {"error": str(e)}
    
    finally:
        page.close()
        logger.debug("Page closed.")


if __name__ == "__main__":
    # Use an INN that is known to have the data you want to test
    test_inn = "3123109532" # Example INN for Sberbank Technologies
    
    # Configure logger
    log_file = f"data/logs/test_runs_{datetime.datetime.now().strftime('%Y-%m-%d')}.log"
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger.add(log_file, rotation="1 day", level="INFO")

    logger.info(f"--- Starting new test session for INN: {test_inn} ---")
    
    try:
        with Browser() as browser:
            final_data = run_test(browser, test_inn)
            
            # Save the results to a JSON file
            output_filename = f"data/output/{test_inn}_test_data.json"
            os.makedirs(os.path.dirname(output_filename), exist_ok=True)
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(final_data, f, ensure_ascii=False, indent=4)
            
            logger.success(f"Test run complete. Data saved to {output_filename}")
            print(json.dumps(final_data, ensure_ascii=False, indent=4))

    except Exception as e:
        logger.exception(f"A critical error occurred in the main execution block: {e}")
        raise