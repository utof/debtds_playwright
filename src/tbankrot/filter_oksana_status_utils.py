from typing import Optional
from datetime import datetime
import re

_RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12
}

def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _lower(s: str) -> str:
    # Lowercase with trimmed spaces
    return _norm_spaces((s or "").lower())

def _extract_date_ddmmyyyy(s: str) -> Optional[str]:
    """
    Finds the first explicit dd.mm.yyyy-like date and returns it normalized.
    """
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b", s)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, d).strftime("%d.%m.%Y")
    except ValueError:
        return None

def _extract_date_russian_text(s: str) -> Optional[str]:
    """
    Finds the first russian textual date like '19 ноября 2024 года' or 'с 8 сентября 2022 г.'
    Returns dd.mm.yyyy or None.
    """
    # Tolerate 'с ' prefix and optional 'г.' / 'года'
    m = re.search(r"(?:\bс\s+)?(\d{1,2})\s+([а-яё]+)\s+(\d{4})\s*(?:г\.?|года)?", _lower(s), flags=re.IGNORECASE)
    if not m:
        return None
    d = int(m.group(1))
    mon_name = m.group(2)
    y = int(m.group(3))
    mo = _RU_MONTHS.get(mon_name)
    if not mo:
        return None
    try:
        return datetime(y, mo, d).strftime("%d.%m.%Y")
    except ValueError:
        return None

def _extract_any_date(s: str) -> Optional[str]:
    return _extract_date_ddmmyyyy(s) or _extract_date_russian_text(s)

def _normalize_company_status(raw_text: str) -> str:
    """
    Maps raw status text to normalized company_status per the spec.
    If a date is expected but not found, append 'дата не найдена'.
    """
    raw = _norm_spaces(raw_text or "")
    txt = _lower(raw)

    # Feature flags / keywords
    has_excluded_kw = any(k in txt for k in [
        "исключен из егрюл", "исключение из егрюл", "юридическое лицо ликвидировано", "ликвидировано", "ликвидирован"
    ])
    has_reorg_kw = "реорганизац" in txt or "преобразован" in txt
    has_bankrupt_kw = ("банкрот" in txt) or ("несостоятельн" in txt)
    has_konkurs_kw = "конкурсное производ" in txt
    has_nablyud_kw = "наблюдени" in txt
    has_unreliable_kw = "сведения недостоверны" in txt
    has_acting_kw = ("действующая компания" in txt) or ("действующая организация" in txt)
    has_pre_excl_kw = "предстоящее исключение из егрюл" in txt
    has_in_reorg_phrase = any(k in txt for k in [
        "в состоянии реорганизац", "в процессе реорганизац", "путем преобразован"
    ])

    # Helper for date suffix policy
    def with_date_suffix(base: str, needs_date: bool = True) -> str:
        if not needs_date:
            return base
        date = _extract_any_date(raw)
        if date:
            return f"{base} {date}"
        else:
            return f"{base} дата не найдена"

    # 1) Исключен из ЕГРЮЛ: конкурсное производство
    if has_excluded_kw and has_konkurs_kw:
        return with_date_suffix("исключен из ЕГРЮЛ: конкурсное производство")

    # 2) Исключен из ЕГРЮЛ: недостоверность сведений
    if has_excluded_kw and "недостоверн" in txt:
        return with_date_suffix("исключен из ЕГРЮЛ: недостоверность сведений")

    # 3) Исключен из ЕГРЮЛ: реорганизация
    if has_excluded_kw and has_reorg_kw:
        return with_date_suffix("исключен из ЕГРЮЛ: реорганизация")

    # 4) Исключен из ЕГРЮЛ: иное
    if has_excluded_kw:
        return with_date_suffix("исключен из ЕГРЮЛ: иное")

    # 5) Признан банкротом: конкурсное производство
    if has_bankrupt_kw and has_konkurs_kw:
        return with_date_suffix("признан банкротом: конкурсное производство.", needs_date=True)

    # 6) Признан банкротом: наблюдение
    if has_bankrupt_kw and has_nablyud_kw:
        # exact wording requirement: both "банкрот" and "наблюдение" must be present (already satisfied)
        return with_date_suffix("признан банкротом: наблюдение.", needs_date=True)

    # 7) Действующий, предстоящее исключение / реорганизация (possibly both; join with '/')
    if has_pre_excl_kw or has_in_reorg_phrase:
        parts = []
        if has_pre_excl_kw:
            parts.append("предстоящее исключение из ЕГРЮЛ")
        if has_in_reorg_phrase:
            # Preserve the “путем преобразования” tail if present
            if "путем преобразован" in txt:
                parts.append("в процессе реорганизации путем преобразования")
            else:
                parts.append("в процессе реорганизации")
        joined = " / ".join(parts)
        return with_date_suffix(f"действующий, {joined}", needs_date=True)

    # 8) Сведения недостоверны
    if has_unreliable_kw:
        return with_date_suffix("сведения недостоверны.", needs_date=True)

    # 9) Действующий (plain)
    if has_acting_kw:
        return "действующий"

    # 10) Fallback → empty normalized, caller will still store raw
    return ""
