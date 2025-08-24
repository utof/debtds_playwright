from patchright.sync_api import sync_playwright, Browser as PlaywrightBrowser


# Assuming these helper functions are in sibling files (e.g., src/listorg/flows.py)
from .flows import extract_main_activity, find_company_data, parse_financial_data, handle_captcha
from .utils import process_inn
from loguru import logger
import os
import datetime

from ..browser import Browser

def run(browser: PlaywrightBrowser, inn: str, method: str) -> dict:
    """
    Scrapes company data from list-org.com based on the INN.

    Args:
        browser: The Playwright browser instance.
        inn: The company's INN.
        method: The type of data to retrieve ('card' or 'finances').

    Returns:
        A dictionary containing the requested company data.
    """
    inn = process_inn(inn)
    logger.info(f"Processing INN: {inn} for method: {method}")

    page = browser.new_page()
    logger.debug("New page created.")

    try:
        page.goto(f"https://www.list-org.com/search?val={inn}", wait_until='domcontentloaded')
        handle_captcha(page)

        if page.locator("p:has-text('Найдено 0 организаций')").count() > 0:
            message = "Company with the specified INN not found."
            logger.warning(message)
            return {"error": message}

        # Navigate to the company page
        page.locator("a[href*='/company/']").first.click()
        page.wait_for_load_state("domcontentloaded")
        handle_captcha(page)
        required_codes = [
        'Ф1.1200', 'Ф1.1240', 'Ф1.1250', 'Ф1.1400', 
        'Ф1.1500', 'Ф1.1520', 'Ф1.1530', 'Ф1.1600', 'Ф2.2000']

        # Execute logic based on the requested method
        if method == 'card':
            company_data = find_company_data(page)
            main_activity = extract_main_activity(page)
            # Combine the results into a single dictionary
            result = {**company_data, "main_activity": main_activity}
            logger.info(f"Successfully retrieved card data for INN: {inn}")
            return result
        
        elif method == 'finances':
            financial_data = parse_financial_data(page, required_codes)
            logger.info(f"Successfully retrieved financial data for INN: {inn}")
            return {"financials": financial_data}
        
        else:
            # Handle invalid method
            logger.error(f"Invalid method specified: {method}")
            return {"error": "Invalid method specified. Use 'card' or 'finances'."}

    except Exception as e:
        logger.exception(f"An error occurred during scraping for INN {inn}: {e}")
        page.screenshot(path=f"error_{inn}.png")
        return {"error": str(e)}
    
    finally:
        page.close()
        logger.debug("Page closed.")


if __name__ == "__main__":
    inn = "1400013278"
    logger.add("data/logs/runs.log", rotation="1 day", level="INFO")
    try:
        with Browser() as browser:
            jsonn = run(browser, inn, "finances")
            with open(f"{inn}_financial_data.json", "w", encoding="utf-8") as f:
                import json
                json.dump(jsonn, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.exception(f"Unhandled exception in main execution: {e}")
        # Save error details to timestamped file
        os.makedirs("data/error_logs", exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        error_file = f"data/error_logs/error_{timestamp}.log"
        logger.add(error_file, level="ERROR")
        logger.error(f"Error details: {e}")
        raise