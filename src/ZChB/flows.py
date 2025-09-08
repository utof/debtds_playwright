import re
from patchright.async_api import Page
from loguru import logger

async def click_beneficiaries(page: Page) -> bool:
    try:
        # 0) Desktop layout and remove cookie overlay
        await page.set_viewport_size({"width": 1400, "height": 900})
        try:
            await page.locator('#cookie-accept-button').click(timeout=1000)
        except Exception:
            pass  # banner might not be there

        # 1) Scroll the section into view and produce real scroll events
        header = page.locator("text=Бенефициары (Выгодоприобретатели)")
        # If header not yet attached, wheel-scroll down until it appears
        for _ in range(20):
            if await header.count() > 0:
                break
            await page.mouse.wheel(0, 800)
            await page.wait_for_timeout(100)

        if await header.count() == 0:
            # As a fallback, go near bottom to force more lazy loads
            for _ in range(10):
                await page.mouse.wheel(0, 1200)
                await page.wait_for_timeout(100)

        # Ensure it’s within viewport
        if await header.count():
            await header.first.scroll_into_view_if_needed(timeout=3000)

        # 2) Wait a beat for their scroll-handler to issue Ajax
        await page.wait_for_timeout(300)

        # 3) Try to find the link; allow wording variations
        section = page.locator('#benefic_tree, .ajax-content[data-content*="/ajax/benefic-tree"]')
        link = section.locator("a:has-text('Показать всех')")
        if await link.count() == 0:
            link = section.locator("a").filter(has_text=re.compile(r"Показать\s+все(х)?", re.I))

        # Give the lazy loader a few more scroll nudges if needed
        for _ in range(6):
            if await link.count() > 0:
                break
            await page.mouse.wheel(0, 600)
            await page.evaluate("window.dispatchEvent(new Event('scroll'))")
            await page.wait_for_timeout(150)

        # 4) If still not there, force-inject via fetch (awaited)
        if await link.count() == 0:
            await page.evaluate("""
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
            await page.wait_for_selector("#benefic_tree a:has-text('Показать всех'), .ajax-content[data-content*='/ajax/benefic-tree'] a:has-text('Показать всех')", timeout=8000)

            # Refresh link locator after injection
            link = section.locator("a:has-text('Показать всех')")

        if await link.count() == 0:
            return False  # not loaded

        # 5) Click link (JS click fallback in case something overlays)
        try:
            await link.first.click(timeout=5000)
        except TimeoutError:
            await link.first.evaluate("el => el.click()")

        # 6) Wait for modal (either normal or premium)
        await page.wait_for_selector("#modal-template .modal-title", timeout=5000)

        if await page.locator("#modal-template .modal-title:has-text('Бенефициары')").count() > 0:
            return True
        if await page.locator("#modal-template .modal-title:has-text('доступны в тарифах')").count() > 0:
            return False  # premium-locked

        return True

    except TimeoutError:
        return False
    except Exception:
        return False
    
    
async def click_ceos(page: Page) -> bool:
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
    
    if await link_locator.count() == 0:
        logger.warning("The 'CEO History' link was not found on the page.")
        return False

    try:
        logger.info("Clicking the 'CEO History' link...")
        await link_locator.click()

        # Wait for the modal, identified by its title, to become visible.
        modal_title_locator = page.locator("div.modal-title:has-text('История изменений руководителей')")
        await modal_title_locator.wait_for(state="visible", timeout=5000)

        logger.success("Successfully clicked the link and the CEO history modal is visible.")
        return True
    except TimeoutError:
        logger.error("Timed out waiting for the CEO history modal to appear after clicking the link.")
        return False
    except Exception as e:
        logger.error(f"An error occurred while trying to open the CEO history modal: {e}")
        return False

async def extract_beneficiaries(page: Page) -> dict:
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

    if await modal_locator.count() == 0:
        logger.info("Beneficiaries modal not found on the page.")
        return {}
        
    # Find all data rows (tr) in the table, skipping the header row (th)
    rows = await modal_locator.locator("table.founders-table tbody tr:has(td)").all()

    if not rows:
        logger.warning("Beneficiaries table found, but it contains no data rows.")
        return {}

    for row in rows:
        cells = await row.locator("td").all()
        if len(cells) >= 5:
            try:
                row_num = (await cells[0].text_content() or "").strip()
                fio = (await cells[1].locator("a").first.text_content() or "").strip()
                svyaz = (await cells[2].text_content() or "").strip()
                inn = (await cells[3].text_content() or "").strip()
                dolya = (await cells[4].text_content() or "").strip()

                if row_num:
                    beneficiaries[row_num] = {
                        "фио": fio,
                        "связь": svyaz,
                        "инн": inn,
                        "доля": dolya
                    }
            except Exception as e:
                logger.error(f"Could not parse a beneficiary row. HTML: {await row.inner_html()}. Error: {e}")

    logger.info(f"Extracted {len(beneficiaries)} beneficiaries.")
    return beneficiaries

async def extract_ceos(page: Page) -> dict:
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
        await modal_locator.wait_for(state="visible", timeout=5000)
    except Exception:
        logger.info("CEO history modal not found on the page.")
        return {}

    # Each date chunk is its own <tbody id="history-founder-chunk-...">
    date_chunks = modal_locator.locator("tbody[id^='history-founder-chunk-']")
    if await date_chunks.count() == 0:
        logger.warning("CEO history modal found, but no date chunks were located.")
        return {}

    # Iterate chunks
    for i in range(await date_chunks.count()):
        chunk = date_chunks.nth(i)

        # The date is inside a <td class="attr-date"> ... <a href="/ordering?date=DD.MM.YYYY">DD.MM.2014</a>
        date_cell = chunk.locator("td.attr-date")
        if await date_cell.count() == 0:
            # No date row in this chunk; skip
            continue

        date_anchor_locator = date_cell.locator("a[href*='/ordering?date=']")
        if await date_anchor_locator.count() == 0:
            continue

        # Take the first anchor text as the date string
        date_str = (await date_anchor_locator.first.text_content() or "").strip()
        if not date_str:
            continue

        if date_str not in ceos_by_date:
            ceos_by_date[date_str] = []

        # Data rows: have <td data-th="..."> cells; the date row does not.
        data_rows = chunk.locator("tr:has(td[data-th])")
        for j in range(await data_rows.count()):
            row = data_rows.nth(j)

            # We expect at least 4 <td>s: index, position, name, inn
            tds = row.locator("td")
            if await tds.count() < 4:
                continue

            try:
                position = (await tds.nth(1).text_content() or "").strip()
                name = (await tds.nth(2).text_content() or "").strip()
                inn = (await tds.nth(3).text_content() or "").strip()

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
                    html_snippet = await row.inner_html()
                except Exception:
                    html_snippet = "<unavailable>"
                logger.error(f"Could not parse a CEO row. HTML: {html_snippet}. Error: {e}")

    logger.info(f"Extracted CEO history for {len(ceos_by_date)} dates.")
    return ceos_by_date

async def click_founders(page: Page) -> bool:
    """
    Finds and clicks the link to open the 'История изменений учредителей' modal.

    It waits for the modal to become visible after the click.

    Args:
        page: The Playwright page object.

    Returns:
        True if the link was clicked and the modal appeared, False otherwise.
    """
    # Be flexible about the company name and quotes; just match the invariant part.
    link_locator = page.locator('a[data-title*="История изменений учредителей"]')

    if await link_locator.count() == 0:
        logger.warning("The 'Founders History' link was not found on the page.")
        return False

    try:
        logger.info("Clicking the 'Founders History' link...")
        await link_locator.first.click()

        # Wait for the modal title that contains the invariant text.
        modal_title_locator = page.locator(
            "div.modal-title:has-text('История изменений учредителей')"
        )
        await modal_title_locator.wait_for(state="visible", timeout=5000)

        logger.success("Successfully clicked the link and the Founders history modal is visible.")
        return True
    except TimeoutError:
        logger.error("Timed out waiting for the Founders history modal to appear after clicking the link.")
        return False
    except Exception as e:
        logger.error(f"An error occurred while trying to open the Founders history modal: {e}")
        return False


async def extract_founders(page: Page) -> dict:
    """
    Extracts the 'История изменений учредителей' table grouped by date.

    Returns:
        {
          "12.05.2014": [
            {"учредитель": "...", "инн": "...", "доля": "...", "доля_руб": "..."},
            ...
          ],
          ...
        }
    """
    founders_by_date: dict[str, list[dict]] = {}

    # Scope to the specific modal by its title to avoid mixing with other modals.
    modal_locator = page.locator(
        "div.modal-content:has(div.modal-title:has-text('История изменений учредителей'))"
    )
    try:
        await modal_locator.wait_for(state="visible", timeout=5000)
    except Exception:
        logger.info("Founders history modal not found on the page.")
        return {}

    # Chunks are grouped per date; ids look like history-founder-chunk-DD-MM-YYYY
    date_chunks = modal_locator.locator("tbody[id^='history-founder-chunk-']")
    if await date_chunks.count() == 0:
        logger.warning("Founders history modal found, but no date chunks were located.")
        return {}

    for i in range(await date_chunks.count()):
        chunk = date_chunks.nth(i)

        # The date lives in the row with class 'attr-date' and contains an <a href="/.../ordering?date=DD.MM.YYYY">DD.MM.YYYY</a>
        date_cell = chunk.locator("td.attr-date")
        if await date_cell.count() == 0:
            continue

        date_anchor = date_cell.locator("a[href*='/ordering?date=']")
        if await date_anchor.count() == 0:
            continue

        date_str = (await date_anchor.first.text_content() or "").strip()
        if not date_str:
            continue

        founders_by_date.setdefault(date_str, [])

        # Data rows have td[data-th]; the date row does not.
        data_rows = chunk.locator("tr:has(td[data-th])")
        for j in range(await data_rows.count()):
            row = data_rows.nth(j)

            # Expected columns: # | Учредитель | ИНН | Доля | Доля (руб.)
            tds = row.locator("td")
            if await tds.count() < 5:
                # Some variants might omit a column; try to be defensive.
                try:
                    html_snippet = await row.inner_html()
                except Exception:
                    html_snippet = "<unavailable>"
                logger.warning(f"Unexpected founders row shape, skipping. HTML: {html_snippet}")
                continue

            try:
                founder = (await tds.nth(1).text_content() or "").strip()
                inn = (await tds.nth(2).text_content() or "").strip()
                share = (await tds.nth(3).text_content() or "").strip()
                share_rub = (await tds.nth(4).text_content() or "").strip()

                # Normalize whitespace/newlines
                def norm(s: str) -> str:
                    return " ".join(s.split())

                entry = {
                    "учредитель": norm(founder),
                    "инн": norm(inn),
                    "доля": norm(share),
                    "доля_руб": norm(share_rub),
                }
                founders_by_date[date_str].append(entry)
            except Exception as e:
                try:
                    html_snippet = await row.inner_html()
                except Exception:
                    html_snippet = "<unavailable>"
                logger.error(f"Could not parse a founders row. HTML: {html_snippet}. Error: {e}")

    logger.info(f"Extracted founders history for {len(founders_by_date)} dates.")
    return founders_by_date


async def extract_employees_by_year(page) -> dict:
    """
    Extracts employee counts year by year from the div#sshr-collapse.

    Returns:
        dict like: {"2018": 14, "2019": 13, "2020": 11, "2021": 9, "2022": 8}
    """
    employees_by_year = {}

    try:
        collapse = page.locator("div#sshr-collapse")
        await collapse.wait_for(state="attached", timeout=5000)
    except Exception:
        logger.warning("Employee collapse div (#sshr-collapse) not found.")
        return {}

    year_rows = await collapse.locator("div").all()
    if not year_rows:
        logger.warning("No year rows found under #sshr-collapse.")
        return {}

    for row in year_rows:
        try:
            year_span = row.locator("span.text-gray").first
            year_text = (await year_span.text_content() or "").strip()
            year = year_text if year_text.isdigit() else None
            if not year:
                continue

            # Extract all text and filter out year & +/- info
            row_text = " ".join((await row.text_content() or "").split())
            # Example row_text: "2022 8 -1 чел."
            parts = row_text.split()
            # first part = year, second part = employee count
            count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None

            if count is not None:
                employees_by_year[year] = count
        except Exception as e:
            logger.error(f"Failed to parse employee row: {await row.inner_html()}. Error: {e}")

    # Sort dict by year (ascending = oldest first)
    employees_by_year = {
        k: employees_by_year[k]
        for k in sorted(employees_by_year.keys(), key=int)
    }

    logger.info(f"Extracted employees by year: {employees_by_year}")
    return employees_by_year