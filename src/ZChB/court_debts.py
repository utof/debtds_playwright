import re
from loguru import logger

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
            # If unit missing/unknown, assume raw RUB and convert to millions
            amount_mln = num / 1_000_000.0

    return {
        "количество судебных дел": count,
        "судебных дел на сумму(млн руб)": round(amount_mln, 6)  # keep sane precision
    }

def extract_defendant_in_progress(page) -> dict:
    """
    Find the 'Ответчик' block and extract the current 'Рассматривается' stats.
    Returns JSON like:
      {"количество судебных дел": <int>, "судебных дел на сумму(млн руб)": <float>}
    """
    try:
        row = page.locator("div.row.m-b-5:has(div.col-md-4:has-text('Ответчик'))").first
        row.wait_for(state="attached", timeout=5000)
    except Exception:
        logger.warning("Ответчик row not found on the page.")
        return {}

    # 2) From the sibling right column, pick the paragraph that contains 'Рассматривается'
    right_col = row.locator("div.col-md-8").first
    line = right_col.locator("p:has-text('Рассматривается')").first

    try:
        line.wait_for(state="visible", timeout=5000)
    except Exception:
        logger.warning("No 'Рассматривается' line found under Ответчик.")
        return {}

    # 3) Get the full text content (anchor + spans)
    text = (line.text_content() or "").strip()
    # Normalize whitespace/newlines
    text = " ".join(text.split())
    logger.debug(f"Extracting defendant in progress from text: {text}")

    # 4) Parse out count and amount, normalize to millions
    result = _extract_count_and_amount(text)
    logger.info(f"Extracted defendant in progress: {result}")
    return result
