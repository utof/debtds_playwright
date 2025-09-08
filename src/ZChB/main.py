from patchright.async_api import Browser as PlaywrightBrowser
from loguru import logger
import json
import os
import datetime
import asyncio

from .flows import (
    click_ceos, 
    extract_ceos, 
    click_beneficiaries, 
    extract_beneficiaries,
    extract_employees_by_year,
    click_founders,
    extract_founders
)
from .login import login
from .court_debts import extract_defendant_in_progress
from ..utils import process_inn
from ..browser import Browser

async def run_test(browser: PlaywrightBrowser, inn: str) -> dict:
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

    page = await browser.new_page()
    logger.debug("New page created.")

    results = {
        "ceos": {},
        "beneficiaries": {},
        "defendant_in_progress": {}  # + new field
    }

    try:
        if not await login(page):
            return {}
        
        logger.info(f"Navigating to search page for INN: {inn}")
        await page.goto(f"https://zachestnyibiznes.ru/search?query={inn}", wait_until='domcontentloaded')

        # Locate all potential company links first, without selecting .first
        company_links_locator = page.locator(f'a[href*="/company/ul/"]:visible')
        
        # Check the count. If zero, no link was found.
        if await company_links_locator.count() == 0:
            logger.warning("No visible company link found on the search results page.")
            return {"message": "Не найдено данных на ЗЧБ. Нет такой компании."}

        # If we are here, at least one link exists. Now we can safely get the first and click it.
        logger.info("Company link found, navigating to company page.")
        await company_links_locator.first.click()
        await page.wait_for_load_state("domcontentloaded")
        logger.success("Successfully navigated to the company page.")

        if await click_ceos(page):
            results["ceos"] = await extract_ceos(page)
            await page.keyboard.press("Escape")
            logger.info("CEO modal processed and closed.")
        else:
            logger.warning("Could not open or find the CEO modal.")
        
        if await click_founders(page):
            results["founders"] = await extract_founders(page)
            await page.keyboard.press("Escape")
            logger.info("founders modal processed and closed.")
        else:
            logger.warning("Could not open or find the founders modal.")

        if await click_beneficiaries(page):
            results["beneficiaries"] = await extract_beneficiaries(page)
            await page.keyboard.press("Escape")
            logger.info("Beneficiaries modal processed and closed.")
        else:
            logger.warning("Could not open or find the beneficiaries modal.")

        results["employees_by_year"] = await extract_employees_by_year(page)
        
        # + new extraction (no modal)
        results["defendant_in_progress"] = await extract_defendant_in_progress(page)

        return results

    except Exception as e:
        logger.exception(f"An error occurred during the test run for INN {inn}: {e}")
        os.makedirs("data/screenshots", exist_ok=True)
        await page.screenshot(path=f"data/screenshots/error_{inn}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        return {"error": str(e)}
    
    finally:
        await page.close()
        logger.debug("Page closed.")


async def main():
    test_inn = "3123109532"
    
    log_file = f"data/logs/test_runs_{datetime.datetime.now().strftime('%Y-%m-%d')}.log"
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger.add(log_file, rotation="1 day", level="INFO")

    logger.info(f"--- Starting new test session for INN: {test_inn} ---")
    
    try:
        async with Browser() as browser:
            final_data = await run_test(browser, test_inn)
            output_filename = f"data/output/{test_inn}_test_data.json"
            os.makedirs(os.path.dirname(output_filename), exist_ok=True)
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(final_data, f, ensure_ascii=False, indent=4)
            logger.success(f"Test run complete. Data saved to {output_filename}")
            print(json.dumps(final_data, ensure_ascii=False, indent=4))

    except Exception as e:
        logger.exception(f"A critical error occurred in the main execution block: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())