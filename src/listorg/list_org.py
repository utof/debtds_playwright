import re
from patchright.sync_api import Playwright, sync_playwright, expect
from flows import extract_main_activity,  find_company_data, parse_financial_data, handle_captcha
from utils import process_inn
from loguru import logger
import os
import datetime

def run(playwright: Playwright, inn: str) -> None:
    inn = process_inn(inn)
    logger.info(f"preprocessed INN: {inn}")
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = browser.new_page()


    page.goto(f"https://www.list-org.com/search?val={inn}", wait_until='domcontentloaded')
    handle_captcha(page)
    no_results_locator = page.locator("p:has-text('Найдено 0 организаций')")
    if no_results_locator.count() > 0:
        message = "Найдено 0 организаций с таким ИНН"
        logger.info(message)
        page.close()
        context.close()
        browser.close()
        return message
    link = page.locator("a[href*='/company/']").first
    link.wait_for()  # Waits until the element is attached and visible
    link.click()
    page.wait_for_load_state("domcontentloaded")
    handle_captcha(page)
    # print(find_company_data(page))
    # print(extract_main_activity(page))
    # financial_data = parse_financial_data(page, target_indicators=["Выручка", "Основные средства"])
    financial_data = parse_financial_data(page)
    print(financial_data)
    # make a json file and save financial_data to it
    with open(f"{inn}_financial_data.json", "w", encoding="utf-8") as f:
        import json
        json.dump(financial_data, f, ensure_ascii=False, indent=4)
    page.close()
    print("page closed")
    # ---------------------
    context.close()
    print("context closed")

    browser.close()
    print("browser closed")





if __name__ == "__main__":
    inn = "1400013278"
    logger.add("data/logs/runs.log", rotation="1 day", level="INFO")
    try:
        with sync_playwright() as playwright:
            run(playwright, inn)
    except Exception as e:
        logger.exception(f"Unhandled exception in main execution: {e}")
        # Save error details to timestamped file
        os.makedirs("data/error_logs", exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        error_file = f"data/error_logs/error_{timestamp}.log"
        logger.add(error_file, level="ERROR")
        logger.error(f"Error details: {e}")
        raise