# from playwright.sync_api import Page, Locator
from patchright.sync_api import Page, Locator

# Centralized locator helpers to keep selectors consistent and easy to adjust.

def searchbox(page: Page) -> Locator:
    # Prefer role-based searchbox, fallback to common inputs
    loc = page.get_by_role("searchbox")
    return loc.first

def submit_button(page: Page) -> Locator:
    # Prefer button[type=submit]; fallback to any role button
    loc = page.locator('form button[type="submit"], button[type="submit"], [role="button"][type="submit"]')
    return loc.first

def first_company_result_link(page: Page) -> Locator:
    # Result link by URL pattern only, as requested
    return page.locator('a[href*="/company/ul/"]').first

def overview_heading(page: Page) -> Locator:
    # Heading with exact visible name (ru)
    return page.get_by_role("heading", name="Общая информация об организации")

def zero_results_banner(page: Page) -> Locator:
    # Detect banner/text indicating zero results (substring match)
    # Use a broad text locator to catch variants on the page
    return page.get_by_text("найдено 0 организаций", exact=False)