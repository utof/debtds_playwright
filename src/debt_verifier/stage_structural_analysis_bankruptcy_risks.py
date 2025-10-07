from __future__ import annotations
from datetime import datetime, date
import re
# src/tbankrot/status_fetch.py
from typing import Optional, Dict
from patchright.async_api import Page  # or playwright.async_api.Page if that's what you use
from tbankrot.companium_company_status import get_company_status
from tbankrot.filter_oksana_status_utils import _extract_date_ddmmyyyy, _normalize_company_status

async def fetch_and_normalize_company_status(page: Page, inn: str) -> Dict[str, Optional[str]]:
    """
    Fetches the company's status from companium.ru and returns normalized info.

    Returns a dict:
      {
        'inn': str,
        'raw': Optional[str],           # what companium showed (e.g. 'Действующая', etc.)
        'normalized': str,              # your normalized, spec-compliant string
        'date': Optional[str],          # dd.mm.yyyy if found anywhere in `normalized`
        'has_date': bool,               # convenience flag
        'normalized_for_eval': str      # same as `normalized` if date present; otherwise
                                        # strip the ' дата не найдена' tail to avoid parse failures
      }
    """
    raw = await get_company_status(page, inn)
    if raw is None:
        return {
            "inn": inn,
            "raw": None,
            "normalized": "",
            "date": None,
            "has_date": False,
            "normalized_for_eval": "",
        }

    normalized = _normalize_company_status(raw)
    date = _extract_date_ddmmyyyy(normalized)
    has_date = bool(date)

    # If the normalizer produced "... дата не найдена", the pure evaluator's date parser
    # will choke. Provide a cleaned variant for later use.
    normalized_for_eval = normalized
    if not has_date and normalized.endswith(" дата не найдена"):
        normalized_for_eval = normalized[: -len(" дата не найдена")]

    return {
        "inn": inn,
        "raw": raw,
        "normalized": normalized,
        "date": date,
        "has_date": has_date,
        "normalized_for_eval": normalized_for_eval,
    }

def evaluate_company_status(status_text: str) -> dict:
    """
    Input: left-column text exactly as in the table.
    Output: {'points': int, 'comment': str}
    Notes:
      - Date is always present when shown in the table; parsed from the end (dd.mm.yyyy).
      - All cases are split explicitly, so each can have its own comment string.
      - If the table cell had no comment, return an empty string.
    """
    text = status_text.strip().lower()

    def parse_date(t: str) -> date:
        m = re.search(r"(\d{2}\.\d{2}\.\d{4})$", t)
        return datetime.strptime(m.group(1), "%d.%m.%Y").date()

    def years_since(d: date) -> float:
        return (date.today() - d).days / 365.25

    # Shared comment used by the three "исключен из ЕГРЮЛ: ..." (реорганизация/недостоверность/иное)
    comment_subsidiary = (
        "Взыскание возможно только при привлечении к субсидиарной ответственности "
        "при наличии активов у КДЛ."
    )

    # === 1) Действующий ===
    if text == "действующий":
        return {"points": 6, "comment": ""}

    # === 2) Сведения недостоверны. дд.мм.гг ===
    if text.startswith("сведения недостоверны"):
        _ = parse_date(text)
        return {"points": 3, "comment": ""}

    # === 3) Действующий, предстоящее исключение / в процессе реорганизации путем преобразования. дд.мм.гг ===
    if text.startswith("действующий, предстоящее исключение") \
       or "в процессе реорганизации путем преобразования" in text:
        _ = parse_date(text)
        return {"points": 2, "comment": ""}

    # === 4) Исключен из ЕГРЮЛ: реорганизация. дд.мм.гг (порог 3 года) ===
    if text.startswith("исключен из егрюл: реорганизация"):
        d = parse_date(text)
        pts = -100 if years_since(d) >= 3.0 else 2
        return {"points": pts, "comment": comment_subsidiary}

    # === 5) Исключен из ЕГРЮЛ: недостоверность сведений. дд.мм.гг (порог 3 года) ===
    if text.startswith("исключен из егрюл: недостоверност"):
        d = parse_date(text)
        pts = -100 if years_since(d) >= 3.0 else 2
        return {"points": pts, "comment": comment_subsidiary}

    # === 6) Исключен из ЕГРЮЛ: иное. дд.мм.гг (порог 3 года) ===
    if text.startswith("исключен из егрюл: иное"):
        d = parse_date(text)
        pts = -100 if years_since(d) >= 3.0 else 2
        return {"points": pts, "comment": comment_subsidiary}

    # === 7) Исключен из ЕГРЮЛ: конкурсное производство. дд.мм.гг ===
    if text.startswith("исключен из егрюл: конкурсное производство"):
        _ = parse_date(text)
        return {"points": -100, "comment": ""}

    # === 8) Признан банкротом: конкурсное производство. дд.мм.гг ===
    if text.startswith("признан банкротом: конкурсное производство"):
        _ = parse_date(text)
        return {"points": -20, "comment": ""}

    # === 9) Признан банкротом: наблюдение. дд.мм.гг ===
    if text.startswith("признан банкротом: наблюдение"):
        _ = parse_date(text)
        return {"points": -10, "comment": ""}

    # Fallback (shouldn't occur with normalized inputs)
    return {"points": 0, "comment": ""}


def evaluate_register_date(register_date_str: str, today: date | None = None) -> dict:

    """
    Score company age by registration date.

    Args:
        register_date_str: 'dd.mm.yyyy'
        today: optional override for testing; defaults to date.today()

    Returns:
        {"points": int, "comment": str}
            <1 year  -> -4, "Компания зарегистрирована менее 1 года, что может быть риском компании-однодневки"
            1–3 years -> -2, ""
            >3 years  ->  2, ""
    """
    if today is None:
        today = date.today()

    reg_date = datetime.strptime(register_date_str.strip(), "%d.%m.%Y").date()

    # full years between reg_date and today
    years = today.year - reg_date.year
    if (today.month, today.day) < (reg_date.month, reg_date.day):
        years -= 1

    if years < 1:
        return {
            "points": -4,
            "comment": "Компания зарегистрирована менее 1 года, что может быть риском компании-однодневки",
        }
    elif years < 3:
        return {"points": -2, "comment": ""}
    else:
        return {"points": 2, "comment": ""}
    
def evaluate_last_finances_date(last_finances_date_str: str, today: date | None = None) -> dict:
    """
    Оценка актуальности последней отчетности компании (Этап 2).

    Логика:
      - Дата подачи последней отчетности = 1 апреля текущего года.
      - last_ideal_date:
          если current_date >= 1.04.current_year → сравниваем с current_year - 1
          если current_date <  1.04.current_year → сравниваем с current_year - 2
      - Разница по годам между last_finances_date и last_ideal_date:
          0 лет → +5 баллов
          1 год → +2 балла
          >1 лет → -3 балла
    """
    if today is None:
        today = date.today()

    # Parse company’s last reporting date
    last_finances_date = datetime.strptime(last_finances_date_str.strip(), "%d.%m.%Y").date()

    # Determine cutoff for April 1 of current year
    april_first = date(today.year, 4, 1)

    # Determine last ideal year per rules
    ideal_year = today.year - 1 if today >= april_first else today.year - 2
    last_ideal_date = date(ideal_year, 4, 1)

    # Compute year difference
    diff_years = last_ideal_date.year - last_finances_date.year

    if diff_years == 0:
        points = 5
    elif diff_years == 1:
        points = 2
    else:
        points = -3

    return {"points": points, "comment": ""}

def score_markers_3y(
    *,
    no_finance_3y: bool,
    no_data_3y: bool,
    staff_reduction: bool,
    fixed_assets_reduction: bool,
    bankruptintent: bool,
) -> dict:
    """
    Boolean -> points mapping (True == 'да'):
      no_finance_3y          True -> -10, False -> 0
      no_data_3y             True -> -5,  False -> 0
      staff_reduction        True -> -4,  False -> 0
      fixed_assets_reduction True -> -7,  False -> 0
      bankruptintent         True -> -5,  False -> 0
    """
    pts = {
        "no_finance_3y": -10 if no_finance_3y else 0,
        "no_data_3y": -5 if no_data_3y else 0,
        "staff_reduction": -4 if staff_reduction else 0,
        "fixed_assets_reduction": -7 if fixed_assets_reduction else 0,
        "bankruptintent": -5 if bankruptintent else 0,
    }
    pts["total"] = sum(pts.values())
    return pts