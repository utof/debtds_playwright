import re
from loguru import logger
from patchright.async_api import Page
import json


# The utility functions below are currently not used by the main function,
# but are kept for future steps as requested.

UNIT_TO_MILLIONS = {
    "тыс": 0.001,
    "млн": 1.0,
    "млрд": 1000.0
}

def _parse_number(s: str) -> float:
    """
    Parse a Russian-formatted number string like '123,4' or '123.4' or '123 456'
    into a float. Non-breaking spaces and regular spaces are stripped.
    """
    if s is None:
        return 0.0
    s = s.replace("\xa0", " ").strip()
    # Remove spaces used as thousand separators
    s = re.sub(r"\s+", "", s)
    # Convert comma decimal to dot
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0

def _extract_count_and_amount(text: str) -> dict:
    """
    From a line like:
      'Рассматривается 17 дел, на сумму 123.7 млн ₽'
    extract count=17 and amount_mln=123.7 (already normalized to millions).
    """
    # Count: ... Рассматривается <num> дел ...
    m_count = re.search(r"Рассматривается\s+(\d+)\s+дел", text, flags=re.IGNORECASE)
    count = int(m_count.group(1)) if m_count else 0

    # Amount: ... на сумму <num> <unit> ₽
    m_amt = re.search(
        r"на\s+сумму\s+([0-9][0-9\s.,]*)\s*(тыс|млн|млрд)?\s*₽",
        text,
        flags=re.IGNORECASE
    )
    amount_mln = 0.0
    if m_amt:
        num = _parse_number(m_amt.group(1))
        unit = (m_amt.group(2) or "").lower()
        factor = UNIT_TO_MILLIONS.get(unit, None)
        if factor is not None:
            amount_mln = num * factor
        else:
            amount_mln = num / 1_000_000.0

    return {
        "количество судебных дел": count,
        "судебных дел на сумму(млн руб)": round(amount_mln, 6)
    }
async def get_defendant_in_progress_text(page: Page) -> str | None:
    """
    Finds the 'Ответчик' (Defendant) block and returns the raw text 
    of the line containing 'Рассматривается' (In progress).
    """
    try:
        # 1) Locate the row for 'Ответчик'
        row = page.locator("div.row.m-b-5:has-text('Ответчик')").first
        await row.wait_for(state="visible", timeout=5000)
    except Exception:
        logger.warning("Could not find the 'Ответчик' row on the page.")
        return None

    # 2) From that row, find the paragraph with 'Рассматривается'
    line = row.locator("p:has-text('Рассматривается')").first
    try:
        await line.wait_for(state="visible", timeout=5000)
    except Exception:
        logger.warning("No 'Рассматривается' line found under 'Ответчик'.")
        return None

    # 3) Get the full text content and normalize whitespace
    text = await line.text_content()
    if not text:
        logger.warning("The 'Рассматривается' line was found, but it contains no text.")
        return None
        
    normalized_text = " ".join(text.split())
    logger.debug(f"Found raw text: '{normalized_text}'")
    return normalized_text

async def extract_defendant_in_progress(page: Page) -> dict:
    """
    Finds the 'Ответчик' block and extracts the current 'Рассматривается' stats.
    
    This function now only extracts the raw text and returns it.
    No parsing or conversion is performed.
    """
    logger.info("Attempting to extract defendant in-progress stats...")
    
    # 1. Get the raw text from the page
    text = await get_defendant_in_progress_text(page)

    if text is None:
        logger.error("Failed to extract the defendant's 'in progress' text.")
        return {"extracted_text": "Error: Text not found"}

    # 2. Return the extracted text directly
    result = {"extracted_text": text}
    logger.info(f"Extraction successful. Returning: {json.dumps(result, ensure_ascii=False)}")
    
    return result
