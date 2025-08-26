import re
from patchright.sync_api import Page
from loguru import logger

def click_beneficiaries(page: Page) -> bool:
    try:
        # 0) Desktop layout and remove cookie overlay
        page.set_viewport_size({"width": 1400, "height": 900})
        try:
            page.locator('#cookie-accept-button').click(timeout=1000)
        except Exception:
            pass  # banner might not be there

        # 1) Scroll the section into view and produce real scroll events
        header = page.locator("text=Бенефициары (Выгодоприобретатели)")
        # If header not yet attached, wheel-scroll down until it appears
        for _ in range(20):
            if header.count() > 0:
                break
            page.mouse.wheel(0, 800)
            page.wait_for_timeout(100)

        if header.count() == 0:
            # As a fallback, go near bottom to force more lazy loads
            for _ in range(10):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(100)

        # Ensure it’s within viewport
        if header.count():
            header.first.scroll_into_view_if_needed(timeout=3000)

        # 2) Wait a beat for their scroll-handler to issue Ajax
        page.wait_for_timeout(300)

        # 3) Try to find the link; allow wording variations
        section = page.locator('#benefic_tree, .ajax-content[data-content*="/ajax/benefic-tree"]')
        link = section.locator("a:has-text('Показать всех')")
        if link.count() == 0:
            link = section.locator("a").filter(has_text=re.compile(r"Показать\s+все(х)?", re.I))

        # Give the lazy loader a few more scroll nudges if needed
        for _ in range(6):
            if link.count() > 0:
                break
            page.mouse.wheel(0, 600)
            page.evaluate("window.dispatchEvent(new Event('scroll'))")
            page.wait_for_timeout(150)

        # 4) If still not there, force-inject via fetch (awaited)
        if link.count() == 0:
            page.evaluate("""
                (async () => {
                  const el = document.querySelector('#benefic_tree, .ajax-content[data-content*="/ajax/benefic-tree"]');
                  if (!el) return;
                  const url = el.getAttribute('data-content');
                  if (!url) return;
                  const resp = await fetch(url, { credentials: 'include' });
                  const html = await resp.text();
                  el.innerHTML = html;
                })();
            """)
            page.wait_for_selector("#benefic_tree a:has-text('Показать всех'), .ajax-content[data-content*='/ajax/benefic-tree'] a:has-text('Показать всех')", timeout=8000)

            # Refresh link locator after injection
            link = section.locator("a:has-text('Показать всех')")

        if link.count() == 0:
            return False  # not loaded

        # 5) Click link (JS click fallback in case something overlays)
        try:
            link.first.click(timeout=5000)
        except TimeoutError:
            link.first.evaluate("el => el.click()")

        # 6) Wait for modal (either normal or premium)
        page.wait_for_selector("#modal-template .modal-title", timeout=5000)

        if page.locator("#modal-template .modal-title:has-text('Бенефициары')").count() > 0:
            return True
        if page.locator("#modal-template .modal-title:has-text('доступны в тарифах')").count() > 0:
            return False  # premium-locked

        return True

    except TimeoutError:
        return False
    except Exception:
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
    Finds the modal for 'История изменений руководителей' and extracts the data by date.
    Returns: {"12.05.2014": [{"должность": "...", "руководитель": "...", "инн": "..."}], ...}
    """
    ceos_by_date = {}

    # Wait for the modal to be present & visible
    modal_locator = page.locator(
        "div.modal-content:has(div.modal-title:has-text('История изменений руководителей'))"
    )
    try:
        modal_locator.wait_for(state="visible", timeout=5000)
    except Exception:
        logger.info("CEO history modal not found on the page.")
        return {}

    # Each date chunk is its own <tbody id="history-founder-chunk-...">
    date_chunks = modal_locator.locator("tbody[id^='history-founder-chunk-']")
    if date_chunks.count() == 0:
        logger.warning("CEO history modal found, but no date chunks were located.")
        return {}

    # Iterate chunks
    for i in range(date_chunks.count()):
        chunk = date_chunks.nth(i)

        # The date is inside a <td class="attr-date"> ... <a href="/ordering?date=DD.MM.YYYY">DD.MM.2014</a>
        date_cell = chunk.locator("td.attr-date")
        if date_cell.count() == 0:
            # No date row in this chunk; skip
            continue

        date_anchor_locator = date_cell.locator("a[href*='/ordering?date=']")
        if date_anchor_locator.count() == 0:
            continue

        # Take the first anchor text as the date string
        date_str = (date_anchor_locator.first.text_content() or "").strip()
        if not date_str:
            continue

        if date_str not in ceos_by_date:
            ceos_by_date[date_str] = []

        # Data rows: have <td data-th="..."> cells; the date row does not.
        data_rows = chunk.locator("tr:has(td[data-th])")
        for j in range(data_rows.count()):
            row = data_rows.nth(j)

            # We expect at least 4 <td>s: index, position, name, inn
            tds = row.locator("td")
            if tds.count() < 4:
                continue

            try:
                position = (tds.nth(1).text_content() or "").strip()
                name = (tds.nth(2).text_content() or "").strip()
                inn = (tds.nth(3).text_content() or "").strip()

                # Normalize whitespace/newlines
                position = " ".join(position.split())
                name = " ".join(name.split())
                inn = " ".join(inn.split())

                ceos_by_date[date_str].append({
                    "должность": position,
                    "руководитель": name,
                    "инн": inn
                })
            except Exception as e:
                try:
                    html_snippet = row.inner_html()
                except Exception:
                    html_snippet = "<unavailable>"
                logger.error(f"Could not parse a CEO row. HTML: {html_snippet}. Error: {e}")

    logger.info(f"Extracted CEO history for {len(ceos_by_date)} dates.")
    return ceos_by_date


def extract_employees_by_year(page) -> dict:
    """
    Extracts employee counts year by year from the div#sshr-collapse.

    Returns:
        dict like: {"2018": 14, "2019": 13, "2020": 11, "2021": 9, "2022": 8}
    """
    employees_by_year = {}

    try:
        collapse = page.locator("div#sshr-collapse")
        collapse.wait_for(state="attached", timeout=5000)
    except Exception:
        logger.warning("Employee collapse div (#sshr-collapse) not found.")
        return {}

    year_rows = collapse.locator("div").all()
    if not year_rows:
        logger.warning("No year rows found under #sshr-collapse.")
        return {}

    for row in year_rows:
        try:
            year_span = row.locator("span.text-gray").first
            year_text = (year_span.text_content() or "").strip()
            year = year_text if year_text.isdigit() else None
            if not year:
                continue

            # Extract all text and filter out year & +/- info
            row_text = " ".join((row.text_content() or "").split())
            # Example row_text: "2022 8 -1 чел."
            parts = row_text.split()
            # first part = year, second part = employee count
            count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None

            if count is not None:
                employees_by_year[year] = count
        except Exception as e:
            logger.error(f"Failed to parse employee row: {row.inner_html()}. Error: {e}")

    # Sort dict by year (ascending = oldest first)
    employees_by_year = {
        k: employees_by_year[k]
        for k in sorted(employees_by_year.keys(), key=int)
    }

    logger.info(f"Extracted employees by year: {employees_by_year}")
    return employees_by_year