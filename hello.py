import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://zachestnyibiznes.ru/")
    # if inside html u cant find anything that says exactly "darybon@bk.ru" then go to login page 
    page.goto("https://zachestnyibiznes.ru/login")
    page.get_by_role("textbox", name="Email или номер телефона").fill("darybon@bk.ru ")
    page.get_by_role("textbox", name="Пароль").click()
    page.get_by_role("textbox", name="Пароль").fill("Dashu13145#")
    page.get_by_role("button", name="Войти").click()
    page.locator(".wrap").click()
    # if it says that kinda thing (dont click it its just what it says)
    page.get_by_text("В Ваш аккаунт выполнен вход с другого устройства Вы сможете воспользоваться Плат").click()
    # then look at the <span id="t">5:07</span> here's the timeout we have to wait for (same here, dont click it)
    page.get_by_text(":18").click()
    # after waiting (wait for redirect) check - does darybon@bk.ru exist anywhere? if no then go to login again
    page.goto("https://zachestnyibiznes.ru/login")
    page.get_by_text("Email или номер телефона").click()
    page.get_by_role("textbox", name="Email или номер телефона").click()
    page.get_by_role("textbox", name="Email или номер телефона").fill("darybon@bk.ru ")
    page.get_by_role("textbox", name="Email или номер телефона").press("Tab")
    page.get_by_role("textbox", name="Пароль").fill("Dashu13145#")
    page.get_by_role("button", name="Войти").click()
    # after full page load, see if you have this text. otherwise continue onto the normal routine
    page.get_by_text("Вы вошли в Платный доступ.Другие открытые сессии в Вашем аккаунте завершены").click()
    page.get_by_role("button", name="Понятно").click()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
