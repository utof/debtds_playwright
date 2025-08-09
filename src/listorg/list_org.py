import re
from patchright.sync_api import Playwright, sync_playwright, expect
from flows import extract_main_activity,  find_company_data, parse_financial_data
from utils import process_inn

def run(playwright: Playwright, inn: str) -> None:
    inn = process_inn(inn)
    print(f"preprocessed INN: {inn}")
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = browser.new_page()


    page.goto(f"https://www.list-org.com/search?val={inn}", wait_until='domcontentloaded')
    no_results_locator = page.locator("p:has-text('Найдено 0 организаций')")
    if no_results_locator.count() > 0:
        message = "Найдено 0 организаций с таким ИНН"
        print(message)
        page.close()
        context.close()
        browser.close()
        return message
    # page.get_by_role("link", name="ООО \"ТРАНССПЕЦСЕРВИС\"").click() #1
    link = page.locator("a[href*='/company/']").first
    link.wait_for()  # Waits until the element is attached and visible
    link.click()
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
    with sync_playwright() as playwright:
        run(playwright, inn)