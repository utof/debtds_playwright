import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.list-org.com/")
    page.get_by_role("textbox", name="Поиск").click()
    page.get_by_role("textbox", name="Поиск").fill("1025004909665")
    page.get_by_role("button", name="Поиск").click()
    page.get_by_text("инн/кпп").click()
    page.close()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
