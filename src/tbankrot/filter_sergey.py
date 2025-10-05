#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deterministic rules engine for RAS (РСБУ) markers 1–5.

Input format (example):
{
  "Ф1.1250": {
    "name": "Денежные средства и денежные эквиваленты",
    "values": {"2021": "2102", "2022": "12914", "2023": "502"}
  },
  "Ф1.1500": {...},
  ...
}

Notes / assumptions:
- CURRENT_YEAR is fixed to 2024 (as requested). We pick the freshest available
  year <= CURRENT_YEAR for single-year markers.
- We NEVER substitute zeros for missing data. A marker becomes "not_applicable"
  with an explicit reason if inputs are missing or invalid.
- Marker 2 ("низкая текущая ликвидность"): the text distinguishes
  <0.7 (critical) vs 0.7–1.0 (elevated). I treat ANY <1.0 as "triggered"
  (2 points) and expose a 'severity' field. If you prefer "trigger only if <0.7",
  adjust SHOULD_TRIGGER_CURR_RATIO(...) below – one line change.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, List, Tuple
import math

CURRENT_YEAR = 2024  # per your instruction

# --------------------------- Helpers ---------------------------

def _to_float(x: Any) -> Optional[float]:
    """Parse numbers safely: allow strings with spaces/thin spaces/commas."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        # normalize -0.0 to 0.0
        return float(x) if not (isinstance(x, float) and math.isnan(x)) else None
    if isinstance(x, str):
        s = x.strip().replace('\u00a0', '').replace(' ', '').replace(',', '.')
        if s == '':
            return None
        try:
            val = float(s)
        except ValueError:
            return None
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    return None


def get_value(data: Dict[str, Any], form: int, code: int, year: int) -> Optional[float]:
    """Get value for given form+code and year. Example: form=1, code=1250 -> 'Ф1.1250'."""
    key = f"Ф{form}.{code}"
    entry = data.get(key)
    if not entry:
        return None
    values = entry.get("values") or {}
    raw = values.get(str(year))
    return _to_float(raw)


def available_years(data: Dict[str, Any]) -> List[int]:
    """All years present across any line, as sorted ints (unique)."""
    years = set()
    for v in data.values():
        vals = v.get("values") or {}
        for ys in vals.keys():
            try:
                years.add(int(ys))
            except Exception:
                continue
    return sorted(years)


def latest_year_leq(years: List[int], cap: int) -> Optional[int]:
    """Latest year <= cap."""
    cand = [y for y in years if y <= cap]
    return max(cand) if cand else None


def last_n_years(years: List[int], cap: int, n: int) -> List[int]:
    """Up to n latest years <= cap, descending."""
    cand = [y for y in years if y <= cap]
    return sorted(cand, reverse=True)[:n]


def safe_ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Return num/den if both present and den != 0, else None."""
    if num is None or den is None:
        return None
    if den == 0:
        return None
    return num / den


def pct_drop(old: float, new: float) -> Optional[float]:
    """Percent drop from old to new: (old - new)/old. None if old <= 0."""
    if old is None or new is None:
        return None
    if old <= 0:
        return None
    return (old - new) / old


def epsilon_lt(x: float, threshold: float, eps: float = 1e-9) -> bool:
    """Compare with tiny epsilon to avoid float edge quirks."""
    return x < threshold - eps


# ----------------------- Marker calculators -----------------------

def marker_1_negative_equity(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M1. Отрицательный собственный капитал (Ф1.1300):
      - Trigger if 1300 < 0 in the freshest available year <= CURRENT_YEAR.
      - If also <0 второй год подряд (в текущем и прошлом) — усиление (3 балла).
    """
    years_all = available_years(data)
    y0 = latest_year_leq(years_all, CURRENT_YEAR)
    if y0 is None:
        return _not_applicable("Нет доступных годов для оценки 1300.")

    eq0 = get_value(data, 1, 1300, y0)
    values = {str(y0): eq0}

    if eq0 is None:
        return _not_applicable("Нет значения Ф1.1300 за текущий доступный год.", values)

    triggered = eq0 < 0
    points = 0
    why = f"Ф1.1300={eq0} за {y0}."

    if triggered:
        # check previous year as well
        prev_years = last_n_years(years_all, y0 - 1, 1)
        if prev_years:
            y1 = prev_years[0]
            eq1 = get_value(data, 1, 1300, y1)
            values[str(y1)] = eq1
            if eq1 is not None and eq1 < 0:
                points = 3
                why += f" Второй год подряд отрицательное значение (и в {y1}: {eq1})."
            else:
                points = 2
                why += " Отрицательное значение в последнем году."
        else:
            points = 2
            why += " Отрицательное значение в последнем году; предыдущего года нет."
    else:
        points = 0
        why += " Не ниже нуля."

    return {
        "code": "M1",
        "name": "Отрицательный собственный капитал",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
    }


# Safe, easy-to-change trigger policy for Marker 2:
# If you want "trigger ONLY when <0.7" — set return ratio < 0.7 below.
def _should_trigger_current_ratio(ratio: float) -> bool:
    # Assumption: <1.0 is already "низкая ликвидность"; <0.7 is "critical".
    return ratio < 1.0


def marker_2_low_current_liquidity(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M2. Низкая текущая ликвидность:
      current_ratio = Ф1.1200 / Ф1.1500
      - severity:
          < 0.7 -> critical
          [0.7, 1.0) -> elevated
      - Trigger (assumption): ratio < 1.0 (2 points).
        (One-liner to change to <0.7 if you prefer.)
    """
    years_all = available_years(data)
    y0 = latest_year_leq(years_all, CURRENT_YEAR)
    if y0 is None:
        return _not_applicable("Нет доступных годов для оценки 1200/1500.")
    ca = get_value(data, 1, 1200, y0)
    cl = get_value(data, 1, 1500, y0)
    ratio = safe_ratio(ca, cl)
    values = {str(y0): {"1200": ca, "1500": cl, "ratio": ratio}}

    if ratio is None:
        reason = "Недостаточно данных или деление на ноль (1200/1500)."
        return _not_applicable(reason, values)

    severity = None
    if epsilon_lt(ratio, 0.7):
        severity = "critical"
    elif epsilon_lt(ratio, 1.0):
        severity = "elevated"
    else:
        severity = "normal"

    triggered = _should_trigger_current_ratio(ratio)
    points = 2 if triggered else 0
    why = f"Коэфф. текущей ликвидности {ratio:.4f} за {y0} → {severity}."

    return {
        "code": "M2",
        "name": "Низкая текущая ликвидность",
        "triggered": bool(triggered),
        "points": points,
        "severity": severity,
        "why": why,
        "values": values,
    }


def marker_3_low_quick_liquidity(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M3. Низкая быстрая ликвидность:
      quick_ratio = (Ф1.1200 - Ф1.1210) / Ф1.1500
      Trigger if quick_ratio < 0.6 (2 points).
    """
    years_all = available_years(data)
    y0 = latest_year_leq(years_all, CURRENT_YEAR)
    if y0 is None:
        return _not_applicable("Нет доступных годов для оценки быстрой ликвидности.")
    ca = get_value(data, 1, 1200, y0)
    inv = get_value(data, 1, 1210, y0)
    cl = get_value(data, 1, 1500, y0)
    if ca is None or inv is None or cl is None:
        return _not_applicable("Отсутствуют 1200/1210/1500 для расчёта.", {str(y0): {"1200": ca, "1210": inv, "1500": cl}})

    num = ca - inv
    ratio = safe_ratio(num, cl)
    values = {str(y0): {"1200": ca, "1210": inv, "1500": cl, "ratio": ratio}}

    if ratio is None:
        return _not_applicable("Деление на ноль или некорректные значения.", values)

    triggered = epsilon_lt(ratio, 0.6)
    points = 2 if triggered else 0
    why = f"Быстрая ликвидность {ratio:.4f} за {y0}."
    if triggered:
        why += " Ниже 0,6 — маркер сработал."
    else:
        why += " Не ниже 0,6."

    return {
        "code": "M3",
        "name": "Низкая быстрая ликвидность",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
    }


def marker_4_low_absolute_liquidity(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M4. Низкая абсолютная ликвидность:
      abs_ratio = Ф1.1250 / Ф1.1500
      Trigger if abs_ratio < 0.1 (2 points).
    """
    years_all = available_years(data)
    y0 = latest_year_leq(years_all, CURRENT_YEAR)
    if y0 is None:
        return _not_applicable("Нет доступных годов для оценки абсолютной ликвидности.")
    cash = get_value(data, 1, 1250, y0)
    cl = get_value(data, 1, 1500, y0)
    ratio = safe_ratio(cash, cl)
    values = {str(y0): {"1250": cash, "1500": cl, "ratio": ratio}}

    if ratio is None:
        return _not_applicable("Недостаточно данных или деление на ноль (1250/1500).", values)

    triggered = epsilon_lt(ratio, 0.1)
    points = 2 if triggered else 0
    why = f"Абсолютная ликвидность {ratio:.4f} за {y0}."
    if triggered:
        why += " Ниже 0,1 — маркер сработал."
    else:
        why += " Не ниже 0,1."

    return {
        "code": "M4",
        "name": "Низкая абсолютная ликвидность",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
    }


def marker_5_drop_in_fixed_assets(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M5. Существенное сокращение основных средств:
      Compare Ф1.1150 for the last 2 available years (Y2 vs Y1, both <= CURRENT_YEAR).
      Trigger if drop >= 25%: (1150[Y1] - 1150[Y2]) / 1150[Y1] >= 0.25
      (i.e., Y2 <= 0.75 * Y1).
    """
    years_all = available_years(data)
    pair = last_n_years(years_all, CURRENT_YEAR, 2)
    if len(pair) < 2:
        return _not_applicable("Недостаточно годов для сравнения (нужно >=2).")

    y2, y1 = pair[0], pair[1]  # pair is descending [latest, prev]
    fa_y2 = get_value(data, 1, 1150, y2)
    fa_y1 = get_value(data, 1, 1150, y1)
    values = {str(y1): fa_y1, str(y2): fa_y2}

    if fa_y2 is None or fa_y1 is None:
        return _not_applicable("Нет значений Ф1.1150 по обоим годам.", values)

    drop = pct_drop(fa_y1, fa_y2)  # (old - new)/old
    if drop is None:
        return _not_applicable("Невозможно корректно оценить % снижения (искажённая база).", {**values, "drop": drop})

    triggered = drop >= 0.25
    points = 2 if triggered else 0
    why = f"Изменение Ф1.1150: {fa_y1} → {fa_y2} (снижение {drop*100:.2f}%)."
    if triggered:
        why += " Падение ≥ 25% — маркер сработал."
    else:
        why += " Падение < 25%."

    return {
        "code": "M5",
        "name": "Существенное сокращение основных средств",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
    }

# ----------------------- Markers 6–10 -----------------------

def marker_6_shift_to_long_term_investments(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M6. Перевод активов в долгосрочные финансовые вложения:
      БАЗОВО (реализовано сейчас): сработал, если
        share_curr = 1170/1600 >= 0.20 И (share_curr - share_prev) >= 0.10 за год.
      TODO (по согласованию): 'рост заметный по сумме' — добавить явный порог Δ1170.
    """
    years = last_n_years(available_years(data), CURRENT_YEAR, 2)
    if len(years) < 2:
        return _not_applicable("Нужно минимум 2 года для сравнения долей (1170/1600).")
    y2, y1 = years[0], years[1]

    inv2 = get_value(data, 1, 1170, y2)
    inv1 = get_value(data, 1, 1170, y1)
    tot2 = get_value(data, 1, 1600, y2)
    tot1 = get_value(data, 1, 1600, y1)

    share2 = safe_ratio(inv2, tot2)
    share1 = safe_ratio(inv1, tot1)

    values = {
        str(y1): {"1170": inv1, "1600": tot1, "share": share1},
        str(y2): {"1170": inv2, "1600": tot2, "share": share2},
    }

    if share1 is None or share2 is None:
        return _not_applicable("Недостаточно данных для долей 1170/1600.", values)

    delta_pp = share2 - share1  # в долях (0..1)
    cond_share_level = share2 >= 0.20 - 1e-9
    cond_share_jump = delta_pp >= 0.10 - 1e-9

    triggered = cond_share_level and cond_share_jump
    points = 2 if triggered else 0

    why = (
        f"Доля 1170/1600: {y1}: {share1:.4f} → {y2}: {share2:.4f} "
        f"(изменение {delta_pp*100:.2f} п.п.)."
    )
    if triggered:
        why += " Доля ≥ 20% и рост ≥ 10 п.п. — маркер сработал."
    else:
        why += " Комбинированное условие не выполнено."

    return {
        "code": "M6",
        "name": "Перевод в долгосрочные фин. вложения",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
    }


def marker_7_frozen_receivables(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M7. «Застывшая» дебиторская задолженность:
      Основное условие: (1230/2110) > 1 в текущем году И второй год подряд растёт.
      Усилитель (не меняет баллы, но логируем): DSO = 365*1230/2110 > 240 И растёт.
      Если 2110 <= 0 или =0 → считаем маркер неприменим (и логируем).
    """
    years = last_n_years(available_years(data), CURRENT_YEAR, 3)
    if len(years) < 2:
        return _not_applicable("Нужно минимум 2 года для тренда 1230/2110.")

    ratios = {}
    dsos = {}
    missing = False
    for y in years:
        ar = get_value(data, 1, 1230, y)
        rev = get_value(data, 2, 2110, y)  # Выручка — форма 2
        r = None
        dso = None
        if rev is None or rev <= 0 or ar is None:
            # как обсуждалось ранее — не считаем, чтобы не искажать
            missing = True if (rev is None or rev <= 0) else missing
        else:
            r = ar / rev
            dso = 365.0 * ar / rev
        ratios[y] = r
        dsos[y] = dso

    y2, y1 = years[0], years[1]
    r2, r1 = ratios[y2], ratios[y1]
    values = {
        str(y1): {"1230/2110": r1, "DSO": dsos[y1]},
        str(y2): {"1230/2110": r2, "DSO": dsos[y2]},
    }
    if len(years) >= 3:
        y0 = years[2]
        values[str(y0)] = {"1230/2110": ratios[y0], "DSO": dsos[y0]}

    if r2 is None or r1 is None:
        return _not_applicable("Недостаточно корректных данных по выручке/дебиторке.", values)

    grows_second_year = r2 > r1 + 1e-9
    main_cond = (r2 is not None and r2 > 1.0 + 1e-9) and grows_second_year

    # Усилитель: DSO>240 и растёт (если есть Y0 для сравнения)
    dso_flag = False
    if dsos[y2] is not None and dsos[y2] > 240.0 + 1e-9:
        if dsos[y1] is not None and dsos[y2] > dsos[y1] + 1e-9:
            dso_flag = True
        # если есть третий год, проверим и общий тренд
        if len(years) >= 3 and dsos[y1] is not None and dsos[y0] is not None:
            dso_flag = dso_flag or (dsos[y1] > dsos[y0] + 1e-9)

    triggered = main_cond
    points = 2 if triggered else 0

    why = (
        f"Коэфф. 1230/2110: {y1}={r1:.4f if r1 is not None else 'None'}; "
        f"{y2}={r2:.4f if r2 is not None else 'None'}. "
    )
    if triggered:
        why += " >1 и растёт второй год — маркер сработал."
    else:
        why += " Условие (>1 и рост) не выполнено."

    if dso_flag:
        why += " DSO>240 и растёт — усиливает маркер."

    return {
        "code": "M7",
        "name": "«Застывшая» дебиторская задолженность",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
        "dso_strengthen": dso_flag,
    }


def marker_8_creditors_up_revenue_down(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M8. Рост кредиторки (1520) на ≥50% и падение выручки (2110) на ≥30% — за тот же период.
      Сравниваем последний год (Y2) с предыдущим (Y1).
      Требуем положительную базу для процентов: 1520[Y1]>0 и 2110[Y1]>0.
    """
    years = last_n_years(available_years(data), CURRENT_YEAR, 2)
    if len(years) < 2:
        return _not_applicable("Нужно минимум 2 года для сравнения (1520 и 2110).")

    y2, y1 = years[0], years[1]
    cred2 = get_value(data, 1, 1520, y2)
    cred1 = get_value(data, 1, 1520, y1)
    rev2 = get_value(data, 2, 2110, y2)
    rev1 = get_value(data, 2, 2110, y1)

    values = {
        str(y1): {"1520": cred1, "2110": rev1},
        str(y2): {"1520": cred2, "2110": rev2},
    }

    if (cred1 is None or cred1 <= 0) or (rev1 is None or rev1 <= 0) or cred2 is None or rev2 is None:
        return _not_applicable("Недостаточно корректной базы: нужен Y1>0 по 1520 и 2110.", values)

    cred_growth = (cred2 - cred1) / cred1
    rev_drop = (rev1 - rev2) / rev1

    cond_cred = cred_growth >= 0.50 - 1e-9
    cond_rev = rev_drop >= 0.30 - 1e-9

    triggered = cond_cred and cond_rev
    points = 2 if triggered else 0

    why = (
        f"1520: {cred1} → {cred2} (рост {cred_growth*100:.2f}%); "
        f"2110: {rev1} → {rev2} (падение {rev_drop*100:.2f}%). "
    )
    if triggered:
        why += "Обе границы выполнены — маркер сработал."
    else:
        why += "Комбинация 50%/−30% не выполнена."

    return {
        "code": "M8",
        "name": "Рост кредиторки при падении выручки",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
    }


def marker_9_cash_vs_creditors(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M9. Денег крайне мало относительно кредиторской задолженности:
      ratio = 1250 / 1520 < 0.1 → сработал.
    """
    years_all = available_years(data)
    y0 = latest_year_leq(years_all, CURRENT_YEAR)
    if y0 is None:
        return _not_applicable("Нет доступных годов для расчёта 1250/1520.")

    cash = get_value(data, 1, 1250, y0)
    cred = get_value(data, 1, 1520, y0)
    ratio = safe_ratio(cash, cred)
    values = {str(y0): {"1250": cash, "1520": cred, "ratio": ratio}}

    if ratio is None:
        return _not_applicable("Недостаточно данных или деление на ноль (1250/1520).", values)

    triggered = epsilon_lt(ratio, 0.1)
    points = 2 if triggered else 0

    why = f"1250/1520 = {ratio:.4f} за {y0}. "
    why += "Ниже 0,1 — маркер сработал." if triggered else "Не ниже 0,1."

    return {
        "code": "M9",
        "name": "Денег мало относительно кредиторки",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
    }


def marker_10_debt_load_and_interest_cover(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M10. Чрезмерная долговая нагрузка и слабое покрытие процентов:
      debt_to_revenue = (1410 + 1510) / 2110  > 2  → тревожно
      cover = 2200 / 2330 < 1, при этом 2330 > 0 → тревожно
      Маркер срабатывает, если выполнено ХОТЯ БЫ одно из условий.
      (В тексте второе — «дополнительно», поэтому считаем его альтернативным триггером.)
    """
    years_all = available_years(data)
    y0 = latest_year_leq(years_all, CURRENT_YEAR)
    if y0 is None:
        return _not_applicable("Нет доступных годов для расчёта долговой нагрузки/покрытия процентов.")

    long_debt = get_value(data, 1, 1410, y0)
    short_debt = get_value(data, 1, 1510, y0)
    revenue = get_value(data, 2, 2110, y0)
    profit_sales = get_value(data, 2, 2200, y0)
    interest_pay = get_value(data, 2, 2330, y0)

    debt_sum = None if (long_debt is None and short_debt is None) else ( (long_debt or 0.0) + (short_debt or 0.0) )
    dtr = safe_ratio(debt_sum, revenue)

    cover = None
    cover_applicable = interest_pay is not None and interest_pay > 0
    if cover_applicable and profit_sales is not None:
        cover = profit_sales / interest_pay

    values = {
        str(y0): {
            "1410": long_debt, "1510": short_debt, "2110": revenue,
            "debt_sum": debt_sum, "debt_to_revenue": dtr,
            "2200": profit_sales, "2330": interest_pay, "cover": cover,
        }
    }

    cond_dtr = (dtr is not None) and (dtr > 2.0 + 1e-9)
    cond_cover = cover_applicable and (cover is not None) and (cover < 1.0 - 1e-9)

    if (dtr is None) and (not cover_applicable):
        return _not_applicable("Недостаточно данных: нет валидной выручки/долга и 2330<=0/None.", values)

    triggered = cond_dtr or cond_cover
    points = 2 if triggered else 0

    why = []
    if dtr is not None:
        why.append(f"(1410+1510)/2110 = {dtr:.4f}{' > 2' if cond_dtr else ''}")
    else:
        why.append("(1410+1510)/2110 — не рассчитан")

    if cover_applicable:
        if cover is not None:
            why.append(f"2200/2330 = {cover:.4f}{' < 1' if cond_cover else ''}")
        else:
            why.append("2200/2330 — не рассчитан (нет 2200)")
    else:
        why.append("Покрытие процентов не применимо (2330<=0 или нет значения)")

    why_str = "; ".join(why) + (". Маркер сработал." if triggered else ". Условия не выполнены.")

    return {
        "code": "M10",
        "name": "Долговая нагрузка и покрытие процентов",
        "triggered": bool(triggered),
        "points": points,
        "why": why_str,
        "values": values,
        "dtr_trigger": cond_dtr,
        "cover_trigger": cond_cover,
    }


# -------- Aggregation / scoring for 6–10 (standalone, как и раньше) --------

def compute_markers_6_to_10(data: Dict[str, Any]) -> Dict[str, Any]:
    m6 = marker_6_shift_to_long_term_investments(data)
    m7 = marker_7_frozen_receivables(data)
    m8 = marker_8_creditors_up_revenue_down(data)
    m9 = marker_9_cash_vs_creditors(data)
    m10 = marker_10_debt_load_and_interest_cover(data)

    def ensure_code(obj: Dict[str, Any], code: str, name: str) -> Dict[str, Any]:
        obj.setdefault("code", code)
        obj.setdefault("name", name)
        return obj

    m6 = ensure_code(m6, "M6", "Перевод в долгосрочные фин. вложения")
    m7 = ensure_code(m7, "M7", "«Застывшая» дебиторская задолженность")
    m8 = ensure_code(m8, "M8", "Рост кредиторки при падении выручки")
    m9 = ensure_code(m9, "M9", "Денег мало относительно кредиторки")
    m10 = ensure_code(m10, "M10", "Долговая нагрузка и покрытие процентов")

    markers = {x["code"]: x for x in [m6, m7, m8, m9, m10]}

    total = sum(int(m.get("points", 0)) for m in markers.values())
    strong = sum(1 for m in markers.values() if int(m.get("points", 0)) >= 3)
    medium = sum(1 for m in markers.values() if int(m.get("points", 0)) == 2)

    autopass = False
    autopass_reason = None
    if strong >= 2:
        autopass, autopass_reason = True, "две сильные характеристики (>=3 баллов)"
    elif strong >= 1 and medium >= 2:
        autopass, autopass_reason = True, "1 сильная + 2 средние"
    elif total >= 10:
        autopass, autopass_reason = True, "сумма баллов ≥ 10"

    return {
        "years_available": available_years(data),
        "current_year_cap": CURRENT_YEAR,
        "markers": markers,
        "score_total": total,
        "autopass": autopass,
        "autopass_reason": autopass_reason,
    }


def run_rules_engine_markers_6_10(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Pure function wrapper for the 6–10 block."""
    return compute_markers_6_to_10(input_data)

# ----------------------- Markers 11–15 -----------------------

def marker_11_inventories_up_revenue_down(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M11. Запасы растут (>=30%), а выручка падает (>=20%) — за тот же период (Y2 vs Y1).
    Доп.: 1210/2110 > 0.5 усиливает (лог-флаг, на баллы не влияет).
    """
    years = last_n_years(available_years(data), CURRENT_YEAR, 2)
    if len(years) < 2:
        return _not_applicable("Нужно минимум 2 года для сравнения 1210 и 2110.")
    y2, y1 = years[0], years[1]

    inv2 = get_value(data, 1, 1210, y2)
    inv1 = get_value(data, 1, 1210, y1)
    rev2 = get_value(data, 2, 2110, y2)
    rev1 = get_value(data, 2, 2110, y1)

    values = {
        str(y1): {"1210": inv1, "2110": rev1},
        str(y2): {"1210": inv2, "2110": rev2},
    }

    if inv1 is None or inv2 is None or rev1 is None or rev2 is None or rev1 <= 0:
        return _not_applicable("Недостаточно корректных данных для % роста/падения.", values)

    inv_growth = (inv2 - inv1) / inv1 if inv1 != 0 else None
    rev_drop = (rev1 - rev2) / rev1

    if inv_growth is None:
        return _not_applicable("База для 1210 равна 0 — невозможно оценить рост.", {**values, "inv_growth": inv_growth})

    cond_inv = inv_growth >= 0.30 - 1e-9
    cond_rev = rev_drop >= 0.20 - 1e-9
    triggered = cond_inv and cond_rev
    points = 2 if triggered else 0

    # Усилитель: отношение 1210/2110 > 0.5 в Y2
    strengthen = False
    ratio = safe_ratio(inv2, rev2)
    if ratio is not None and ratio > 0.5 + 1e-9:
        strengthen = True

    why = (
        f"1210: {inv1} → {inv2} (рост {inv_growth*100:.2f}%); "
        f"2110: {rev1} → {rev2} (падение {rev_drop*100:.2f}%). "
    )
    why += "Комбинация выполнена — маркер сработал." if triggered else "Условия не выполнены."
    if strengthen:
        why += " 1210/2110>0.5 — усиливает (лог-флаг)."

    values[str(y2)]["1210/2110"] = ratio

    return {
        "code": "M11",
        "name": "Запасы растут, выручка падает",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
        "ratio_strengthen": strengthen,
    }


def marker_12_large_asset_shifts(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M12. Крупные сдвиги: |Δ1150| или |Δ1170| или |Δ1240| >= 25% от 1600 прошлого года.
    Сравнение Y2 vs Y1 (оба <= CURRENT_YEAR).
    Усиление до 3 баллов, если 'налог на имущество' резко упал (−70% и более) за тот же год.
    Источник налога (опционально): data['__external__']['tax_property'][str(year)].
    """
    years = last_n_years(available_years(data), CURRENT_YEAR, 2)
    if len(years) < 2:
        return _not_applicable("Нужно минимум 2 года для сравнения сдвигов активов.")
    y2, y1 = years[0], years[1]

    a2 = {1150: get_value(data, 1, 1150, y2),
          1170: get_value(data, 1, 1170, y2),
          1240: get_value(data, 1, 1240, y2),
          1600: get_value(data, 1, 1600, y2)}
    a1 = {1150: get_value(data, 1, 1150, y1),
          1170: get_value(data, 1, 1170, y1),
          1240: get_value(data, 1, 1240, y1),
          1600: get_value(data, 1, 1600, y1)}

    values = {str(y1): a1, str(y2): a2}

    base = a1[1600]
    if base is None or base <= 0:
        return _not_applicable("Нет корректной базы 1600 за прошлый год.", values)

    deltas = {}
    flags = {}
    triggered = False
    for code in (1150, 1170, 1240):
        v1, v2 = a1[code], a2[code]
        if v1 is None or v2 is None:
            deltas[str(code)] = None
            flags[str(code)] = False
            continue
        delta_abs = abs(v2 - v1)
        deltas[str(code)] = delta_abs
        flags[str(code)] = (delta_abs >= 0.25 * base - 1e-9)
        triggered = triggered or flags[str(code)]

    values["deltas_abs"] = deltas
    values["flags"] = flags

    points = 2 if triggered else 0
    why = "Сдвиги по (1150/1170/1240) относительно 25% от 1600 прошлого года. "
    why += "Есть хотя бы один крупный сдвиг — маркер сработал. " if triggered else "Крупных сдвигов не выявлено. "

    # Усиление по налогу на имущество (если есть внешний блок)
    tax_block = (data.get("__external__") or {}).get("tax_property") or {}
    tax_y1 = _to_float(tax_block.get(str(y1))) if isinstance(tax_block, dict) else None
    tax_y2 = _to_float(tax_block.get(str(y2))) if isinstance(tax_block, dict) else None
    strengthen = False
    if tax_y1 is not None and tax_y1 > 0 and tax_y2 is not None:
        drop = (tax_y1 - tax_y2) / tax_y1
        values["tax_property"] = {str(y1): tax_y1, str(y2): tax_y2, "drop": drop}
        # Assumption: "резкое падение" = −70% и более за год (легко поменять):
        if drop >= 0.70 - 1e-9 and triggered:
            strengthen = True
            points = 3
            why += "Налог на имущество упал ≥70% — усиление до 3 баллов."
    else:
        if triggered:
            why += "Данные по налогу на имущество отсутствуют — усиление не применено."

    return {
        "code": "M12",
        "name": "Крупные сдвиги в структуре активов",
        "triggered": bool(triggered),
        "points": points,
        "why": why.strip(),
        "values": values,
        "strengthen_tax_property": strengthen,
    }


def marker_13_reporting_issues(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M13. Проблемы с отчётностью — 3 балла при любом из:
      a) Нет отчётности за последний год (берём набор ключевых строк и проверяем отсутствие всех).
      b) 1600 != 1700 (если 1700 доступна).
      c) ДВА года подряд отсутствуют ключевые строки (2110, 1200, 1500).
    """
    years_all = available_years(data)
    y0 = latest_year_leq(years_all, CURRENT_YEAR)
    if y0 is None:
        return _not_applicable("Нет ни одного года — оценка невозможна.")

    # a) отсутствие отчётности за последний год: считаем, что если отсутствуют ВСЕ ключевые строки
    keys_last = {
        "1600": get_value(data, 1, 1600, y0),
        "1700": get_value(data, 1, 1700, y0),
        "2110": get_value(data, 2, 2110, y0),
        "1200": get_value(data, 1, 1200, y0),
        "1500": get_value(data, 1, 1500, y0),
    }
    a_no_last = all(v is None for v in keys_last.values())

    # b) несоответствие валюты баланса актив/пассив (если 1700 есть)
    b_mismatch = False
    if keys_last["1600"] is not None and keys_last["1700"] is not None:
        # сравнение с толерансом
        b_mismatch = abs(keys_last["1600"] - keys_last["1700"]) > 1e-6

    # c) отсутствие ключевых строк 2110, 1200, 1500 два года подряд
    yrs2 = last_n_years(years_all, CURRENT_YEAR, 2)
    c_two_years_absent = False
    c_details = {}
    if len(yrs2) == 2:
        y2, y1 = yrs2[0], yrs2[1]
        set2 = {
            "2110": get_value(data, 2, 2110, y2),
            "1200": get_value(data, 1, 1200, y2),
            "1500": get_value(data, 1, 1500, y2),
        }
        set1 = {
            "2110": get_value(data, 2, 2110, y1),
            "1200": get_value(data, 1, 1200, y1),
            "1500": get_value(data, 1, 1500, y1),
        }
        c_details = {str(y1): set1, str(y2): set2}
        c_two_years_absent = all(v is None for v in set1.values()) and all(v is None for v in set2.values())

    triggered = a_no_last or b_mismatch or c_two_years_absent
    points = 3 if triggered else 0

    why_parts = []
    if a_no_last:
        why_parts.append(f"Нет отчётности за {y0}: ключевые строки отсутствуют.")
    if b_mismatch:
        why_parts.append(f"Несовпадение валюты баланса: 1600 ({keys_last['1600']}) != 1700 ({keys_last['1700']}).")
    if c_two_years_absent:
        why_parts.append("Два года подряд отсутствуют 2110/1200/1500.")
    if not why_parts:
        why_parts.append("Нарушений не выявлено.")

    values = {"last_year": {str(y0): keys_last}}
    if c_details:
        values["two_years_check"] = c_details

    return {
        "code": "M13",
        "name": "Проблемы с отчётностью",
        "triggered": bool(triggered),
        "points": points,
        "why": " ".join(why_parts),
        "values": values,
    }


def marker_14_composite_duty_to_file(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M14. Сводный признак обязанности подать заявление о банкротстве — 3 балла, если ЛЮБОЙ сценарий:
      S1: 1300<0 и 1200/1500 < 0.7
      S2: (1200-1210)/1500 < 0.6 и (1410+1510)/2110 > 2
      S3: 1250/1500 < 0.1 и одновременно (рост 1520>=50% и падение 2110>=30%) как в M8
    """
    years = last_n_years(available_years(data), CURRENT_YEAR, 2)
    if len(years) < 2:
        return _not_applicable("Нужно минимум 2 года для сценария S3 (динамика 1520/2110).")
    y2, y1 = years[0], years[1]

    # Год Y2 (текущий доступный) — для односложных коэффициентов
    eq = get_value(data, 1, 1300, y2)
    ca = get_value(data, 1, 1200, y2)
    inv = get_value(data, 1, 1210, y2)
    cl = get_value(data, 1, 1500, y2)
    cash = get_value(data, 1, 1250, y2)
    ldebt = get_value(data, 1, 1410, y2)
    sdebt = get_value(data, 1, 1510, y2)
    rev = get_value(data, 2, 2110, y2)

    current_ratio = safe_ratio(ca, cl)
    quick_ratio = safe_ratio((ca - inv) if (ca is not None and inv is not None) else None, cl)
    debt_sum = None if (ldebt is None and sdebt is None) else ( (ldebt or 0.0) + (sdebt or 0.0) )
    debt_to_rev = safe_ratio(debt_sum, rev)
    abs_ratio = safe_ratio(cash, cl)

    # Для S3 нужны динамики 1520/2110 между Y1 и Y2
    cred2 = get_value(data, 1, 1520, y2)
    cred1 = get_value(data, 1, 1520, y1)
    rev2 = get_value(data, 2, 2110, y2)
    rev1 = get_value(data, 2, 2110, y1)
    cond_dyn = None
    if (cred1 is not None and cred1 > 0 and cred2 is not None) and (rev1 is not None and rev1 > 0 and rev2 is not None):
        cred_growth = (cred2 - cred1) / cred1
        rev_drop = (rev1 - rev2) / rev1
        cond_dyn = (cred_growth >= 0.50 - 1e-9) and (rev_drop >= 0.30 - 1e-9)

    s1 = (eq is not None and eq < 0) and (current_ratio is not None and current_ratio < 0.7 - 1e-9)
    s2 = (quick_ratio is not None and quick_ratio < 0.6 - 1e-9) and (debt_to_rev is not None and debt_to_rev > 2.0 + 1e-9)
    s3 = (abs_ratio is not None and abs_ratio < 0.1 - 1e-9) and (cond_dyn is True)

    triggered = s1 or s2 or s3
    points = 3 if triggered else 0

    values = {
        str(y2): {
            "1300": eq, "1200": ca, "1210": inv, "1500": cl, "1250": cash,
            "1410": ldebt, "1510": sdebt, "2110": rev,
            "current_ratio": current_ratio, "quick_ratio": quick_ratio,
            "debt_to_revenue": debt_to_rev, "abs_ratio": abs_ratio
        },
        "dynamics": {
            str(y1): {"1520": cred1, "2110": rev1},
            str(y2): {"1520": cred2, "2110": rev2},
        },
        "scenarios": {"S1": s1, "S2": s2, "S3": s3}
    }

    why = []
    why.append(f"S1: 1300<0 и 1200/1500<0.7 → {'да' if s1 else 'нет'}")
    why.append(f"S2: (1200-1210)/1500<0.6 и (1410+1510)/2110>2 → {'да' if s2 else 'нет'}")
    one_line = "да" if (cond_dyn is True) else ("нет" if (cond_dyn is False) else "н/д")
    why.append(f"S3: 1250/1500<0.1 И [рост 1520≥50% & падение 2110≥30%] → {one_line}")
    why_str = "; ".join(why) + (". Маркер сработал." if triggered else ". Условия не выполнены.")

    return {
        "code": "M14",
        "name": "Сводный признак обязанности подать",
        "triggered": bool(triggered),
        "points": points,
        "why": why_str,
        "values": values,
    }


def marker_15_drop_share_fixed_assets(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M15. Падение доли основных средств:
      - Δ(1150/1600) <= −15 п.п. за год (Y2 vs Y1)
      - И выручка (2110) падает или не растёт второй год подряд → требуется 3 года (Y2<=Y1<=Y0).
      Консервативно: если есть только 2 года, НЕ триггерим (легко ослабить в одной строке).
    """
    years = last_n_years(available_years(data), CURRENT_YEAR, 3)
    if len(years) < 3:
        return _not_applicable("Нужно минимум 3 года для проверки тренда выручки.")

    y2, y1, y0 = years[0], years[1], years[2]
    fa2, fa1 = get_value(data, 1, 1150, y2), get_value(data, 1, 1150, y1)
    tot2, tot1 = get_value(data, 1, 1600, y2), get_value(data, 1, 1600, y1)

    if fa2 is None or fa1 is None or tot2 is None or tot1 is None or tot1 <= 0 or tot2 <= 0:
        return _not_applicable("Недостаточно данных для долей 1150/1600.", {
            str(y1): {"1150": fa1, "1600": tot1},
            str(y2): {"1150": fa2, "1600": tot2},
        })

    share2 = fa2 / tot2
    share1 = fa1 / tot1
    delta_pp = (share2 - share1) * 100.0  # в п.п.

    # Выручка тренд: Y2 <= Y1 и Y1 <= Y0 (падает или не растёт второй год)
    rev2 = get_value(data, 2, 2110, y2)
    rev1 = get_value(data, 2, 2110, y1)
    rev0 = get_value(data, 2, 2110, y0)

    if rev2 is None or rev1 is None or rev0 is None:
        return _not_applicable("Недостаточно данных по 2110 для тренда (3 года).", {
            str(y0): {"2110": rev0}, str(y1): {"2110": rev1}, str(y2): {"2110": rev2},
            "shares": {str(y1): share1, str(y2): share2, "Δpp": delta_pp},
        })

    rev_trend_ok = (rev2 <= rev1 + 1e-9) and (rev1 <= rev0 + 1e-9)
    share_drop_ok = delta_pp <= -15.0 - 1e-9

    triggered = share_drop_ok and rev_trend_ok
    points = 2 if triggered else 0

    why = (
        f"Доля 1150/1600: {y1}={share1:.4f} → {y2}={share2:.4f} (Δ {delta_pp:.2f} п.п.). "
        f"Тренд выручки: {y0}={rev0}, {y1}={rev1}, {y2}={rev2} → "
        f"{'падает/не растёт' if rev_trend_ok else 'не подтверждено'}."
    )
    if triggered:
        why += " Падение ≥15 п.п. при падающей/стационарной выручке — маркер сработал."
    else:
        why += " Условия не выполнены."

    return {
        "code": "M15",
        "name": "Падение доли основных средств в активах",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": {
            "shares": {str(y1): share1, str(y2): share2, "Δpp": delta_pp},  # noqa
            "revenue": {str(y0): rev0, str(y1): rev1, str(y2): rev2},
        },
    }


# -------- Aggregation / scoring for 11–15 --------

def compute_markers_11_to_15(data: Dict[str, Any]) -> Dict[str, Any]:
    m11 = marker_11_inventories_up_revenue_down(data)
    m12 = marker_12_large_asset_shifts(data)
    m13 = marker_13_reporting_issues(data)
    m14 = marker_14_composite_duty_to_file(data)
    m15 = marker_15_drop_share_fixed_assets(data)

    def ensure_code(obj: Dict[str, Any], code: str, name: str) -> Dict[str, Any]:
        obj.setdefault("code", code)
        obj.setdefault("name", name)
        return obj

    m11 = ensure_code(m11, "M11", "Запасы растут, выручка падает")
    m12 = ensure_code(m12, "M12", "Крупные сдвиги в структуре активов")
    m13 = ensure_code(m13, "M13", "Проблемы с отчётностью")
    m14 = ensure_code(m14, "M14", "Сводный признак обязанности подать")
    m15 = ensure_code(m15, "M15", "Падение доли основных средств в активах")

    markers = {x["code"]: x for x in [m11, m12, m13, m14, m15]}

    total = sum(int(m.get("points", 0)) for m in markers.values())
    strong = sum(1 for m in markers.values() if int(m.get("points", 0)) >= 3)
    medium = sum(1 for m in markers.values() if int(m.get("points", 0)) == 2)

    autopass = False
    autopass_reason = None
    if strong >= 2:
        autopass, autopass_reason = True, "две сильные характеристики (>=3 баллов)"
    elif strong >= 1 and medium >= 2:
        autopass, autopass_reason = True, "1 сильная + 2 средние"
    elif total >= 10:
        autopass, autopass_reason = True, "сумма баллов ≥ 10"

    return {
        "years_available": available_years(data),
        "current_year_cap": CURRENT_YEAR,
        "markers": markers,
        "score_total": total,
        "autopass": autopass,
        "autopass_reason": autopass_reason,
    }


def run_rules_engine_markers_11_15(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Pure function wrapper for the 11–15 block."""
    return compute_markers_11_to_15(input_data)

# ----------------------- Markers 16–19 -----------------------

def marker_16_growth_in_short_term_investments(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M16. Рост краткосрочных финансовых вложений:
      Условие (любой из двух, за год Y2 vs Y1):
        A) 1240 выросли на ≥50% (при базе Y1>0)
        B) доля 1240/1600 в Y2 ≥ 15% И прирост доли ≥ 8 п.п.
      Срабатывает при выполнении хотя бы одного условия → 2 балла.
    """
    years = last_n_years(available_years(data), CURRENT_YEAR, 2)
    if len(years) < 2:
        return _not_applicable("Нужно минимум 2 года для сравнения 1240.")
    y2, y1 = years[0], years[1]

    st_inv2 = get_value(data, 1, 1240, y2)
    st_inv1 = get_value(data, 1, 1240, y1)
    tot2 = get_value(data, 1, 1600, y2)
    tot1 = get_value(data, 1, 1600, y1)

    share2 = safe_ratio(st_inv2, tot2)
    share1 = safe_ratio(st_inv1, tot1)

    values = {
        str(y1): {"1240": st_inv1, "1600": tot1, "share": share1},
        str(y2): {"1240": st_inv2, "1600": tot2, "share": share2},
    }

    cond_A = None
    if st_inv1 is not None and st_inv1 > 0 and st_inv2 is not None:
        cond_A = (st_inv2 - st_inv1) / st_inv1 >= 0.50 - 1e-9

    cond_B = None
    if (share1 is not None) and (share2 is not None):
        cond_B = (share2 >= 0.15 - 1e-9) and ((share2 - share1) >= 0.08 - 1e-9)

    # Trigger if either condition is True
    triggered = (cond_A is True) or (cond_B is True)
    if cond_A is None and cond_B is None:
        return _not_applicable("Недостаточно данных для 1240/1600 и/или базового роста.", values)

    points = 2 if triggered else 0
    why = []
    why.append(f"A: рост 1240 ≥50% → {'да' if cond_A else 'нет' if cond_A is not None else 'н/д'}")
    why.append(f"B: доля 1240/1600 ≥15% и +≥8 п.п. → {'да' if cond_B else 'нет' if cond_B is not None else 'н/д'}")
    why_str = "; ".join(why) + (". Маркер сработал." if triggered else ". Условия не выполнены.")

    return {
        "code": "M16",
        "name": "Рост краткосрочных финансовых вложений",
        "triggered": bool(triggered),
        "points": points,
        "why": why_str,
        "values": values,
        "cond_A_growth50": cond_A,
        "cond_B_share15_plus8pp": cond_B,
    }


def marker_17_working_capital_vs_creditors(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M17. Оборотные активы не растут/уменьшаются, а кредиторка растёт:
      - 1200[Y2] <= 1200[Y1] (не растёт)
      - 1520 выросла на ≥30% (при базе Y1>0)
      Сравнение Y2 vs Y1.
    """
    years = last_n_years(available_years(data), CURRENT_YEAR, 2)
    if len(years) < 2:
        return _not_applicable("Нужно минимум 2 года для сравнения 1200 и 1520.")
    y2, y1 = years[0], years[1]

    ca2 = get_value(data, 1, 1200, y2)
    ca1 = get_value(data, 1, 1200, y1)
    cr2 = get_value(data, 1, 1520, y2)
    cr1 = get_value(data, 1, 1520, y1)

    values = {str(y1): {"1200": ca1, "1520": cr1}, str(y2): {"1200": ca2, "1520": cr2}}

    if (ca1 is None or ca2 is None) or (cr1 is None or cr2 is None or cr1 <= 0):
        return _not_applicable("Недостаточно данных (нужны 1200 и 1520, база 1520[Y1]>0).", values)

    cond_ca = ca2 <= ca1 + 1e-9
    cred_growth = (cr2 - cr1) / cr1
    cond_cr = cred_growth >= 0.30 - 1e-9

    triggered = cond_ca and cond_cr
    points = 2 if triggered else 0

    why = (
        f"1200: {ca1} → {ca2} ({'не растёт/падает' if cond_ca else 'растёт'}); "
        f"1520: {cr1} → {cr2} (рост {cred_growth*100:.2f}%). "
        + ("Комбинация выполнена — маркер сработал." if triggered else "Условия не выполнены.")
    )

    return {
        "code": "M17",
        "name": "Оборотка не растёт, кредиторка растёт",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
    }


def marker_18_structural_anomalies(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M18. Структурные несоответствия — 1 балл при ЛЮБОМ из:
      A) 1200 < 1210 (аномалия) — проверяем за последний доступный год Y0.
      B) 1500 < 1520 (инфо-флаг) — тоже за Y0.
      C) 2110 = 0 два года подряд при наличии оборотных активов (1200>0) — смотрим Y2,Y1.
    """
    years_all = available_years(data)
    y0 = latest_year_leq(years_all, CURRENT_YEAR)
    if y0 is None:
        return _not_applicable("Нет доступных лет для проверки аномалий.")

    # A & B on latest year
    ca0 = get_value(data, 1, 1200, y0)
    inv0 = get_value(data, 1, 1210, y0)
    cl0 = get_value(data, 1, 1500, y0)
    cred0 = get_value(data, 1, 1520, y0)

    cond_A = (ca0 is not None and inv0 is not None and ca0 < inv0 - 1e-9)
    cond_B = (cl0 is not None and cred0 is not None and cl0 < cred0 - 1e-9)

    # C: two consecutive years revenue==0 with CA>0
    yrs2 = last_n_years(years_all, CURRENT_YEAR, 2)
    cond_C = False
    c_values = {}
    if len(yrs2) == 2:
        y2, y1 = yrs2[0], yrs2[1]
        rev2 = get_value(data, 2, 2110, y2)
        rev1 = get_value(data, 2, 2110, y1)
        ca2 = get_value(data, 1, 1200, y2)
        ca1 = get_value(data, 1, 1200, y1)
        c_values = {str(y1): {"2110": rev1, "1200": ca1}, str(y2): {"2110": rev2, "1200": ca2}}
        cond_C = (
            (rev2 is not None and abs(rev2) < 1e-9) and
            (rev1 is not None and abs(rev1) < 1e-9) and
            ( (ca2 is not None and ca2 > 0) or (ca1 is not None and ca1 > 0) )
        )

    triggered = cond_A or cond_B or cond_C
    points = 1 if triggered else 0

    why_parts = []
    why_parts.append(f"A: 1200<1210 → {'да' if cond_A else 'нет'}")
    why_parts.append(f"B: 1500<1520 → {'да' if cond_B else 'нет'}")
    why_parts.append(f"C: 2110=0 два года при 1200>0 → {'да' if cond_C else 'нет'}")
    why = "; ".join(why_parts) + (". Маркер сработал." if triggered else ". Аномалии не выявлены.")

    values = {
        "latest": {str(y0): {"1200": ca0, "1210": inv0, "1500": cl0, "1520": cred0}},
    }
    if c_values:
        values["two_years_revenue_zero"] = c_values

    return {
        "code": "M18",
        "name": "Структурные аномалии отчётности",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
        "flags": {"A": cond_A, "B": cond_B, "C": cond_C},
    }


def marker_19_off_balance_indicators(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    M19. Внебалансовые индикаторы из смежных реестров — 2 балла при подтверждении набора сигналов.

    Как в описании: «налог на имущество почти до нуля», «транспортный налог исчез»,
    «в ЕГРЮЛ/Росстате деятельность не подтверждается», при этом в балансе крупные
    дебиторки/вложения.

    Реализация (консервативно; все пороги легко менять одной строкой):
      - Используем OPTIONAL внешний блок data['__external__'] с под-ключами:
            'tax_property':  {year: number}
            'tax_transport': {year: number}
            'activity_confirmed': {year: bool}  # True=деятельность подтверждается
        Если блока нет — маркер скорее всего 'not_applicable', чтобы не выдумывать.
      - Сигналы по последним двум годам (Y2 vs Y1):
            S1: property_tax_drop_big — налог на имущество упал на ≥90% (почти ноль) при базе >0.
                # ASSUMPTION: 90% порог «почти ноль».
            S2: transport_tax_vanish — налог на транспорт был >0 и стал ==0/None.
            S3: not_active — activity_confirmed[Y2] is False.
            S4 (балансовый): paper_assets_heavy — (1230/1600 ≥ 0.40) или ((1170+1240)/1600 ≥ 0.30).
                # ASSUMPTION: разумные консервативные пороги, легко поправить.
        Триггер: (как минимум два из S1..S3 истинны) И S4.
    """
    years = last_n_years(available_years(data), CURRENT_YEAR, 2)
    if len(years) < 2:
        return _not_applicable("Нужно минимум 2 года для оценки внебалансовых индикаторов.")
    y2, y1 = years[0], years[1]

    ext = (data.get("__external__") or {})
    tax_prop = ext.get("tax_property") if isinstance(ext.get("tax_property"), dict) else {}
    tax_trans = ext.get("tax_transport") if isinstance(ext.get("tax_transport"), dict) else {}
    activity = ext.get("activity_confirmed") if isinstance(ext.get("activity_confirmed"), dict) else {}

    tp1 = _to_float(tax_prop.get(str(y1))) if tax_prop else None
    tp2 = _to_float(tax_prop.get(str(y2))) if tax_prop else None
    tt1 = _to_float(tax_trans.get(str(y1))) if tax_trans else None
    tt2 = _to_float(tax_trans.get(str(y2))) if tax_trans else None
    act2 = activity.get(str(y2)) if activity else None
    act2_bool = bool(act2) if act2 is not None else None

    # Балансовая часть (S4)
    tot2 = get_value(data, 1, 1600, y2)
    recv2 = get_value(data, 1, 1230, y2)
    invL2 = get_value(data, 1, 1170, y2)
    invS2 = get_value(data, 1, 1240, y2)

    ratio_recv = safe_ratio(recv2, tot2)
    ratio_invest = safe_ratio(( (invL2 or 0.0) + (invS2 or 0.0) ), tot2) if tot2 not in (None, 0) else None

    # --- Assumptions (easy to change) ---
    prop_near_zero_drop_threshold = 0.90  # 90%+
    paper_recv_threshold = 0.40          # 40%+ дебиторка к активам
    paper_invest_threshold = 0.30        # 30%+ суммарные финвложения к активам
    # ------------------------------------

    S1 = None
    if tp1 is not None and tp1 > 0 and tp2 is not None:
        S1 = (tp2 <= (1.0 - prop_near_zero_drop_threshold) * tp1 + 1e-9)  # tp2 <= 10% tp1

    S2 = None
    if tt1 is not None:
        S2 = (tt1 > 0) and (tt2 is None or abs(tt2) < 1e-9)

    S3 = None
    if act2_bool is not None:
        S3 = (act2_bool is False)

    S4 = None
    if (ratio_recv is not None) or (ratio_invest is not None):
        S4 = ( (ratio_recv is not None and ratio_recv >= paper_recv_threshold - 1e-9) or
               (ratio_invest is not None and ratio_invest >= paper_invest_threshold - 1e-9) )

    values = {
        "years": [y1, y2],
        "external": {
            "tax_property": {str(y1): tp1, str(y2): tp2},
            "tax_transport": {str(y1): tt1, str(y2): tt2},
            "activity_confirmed": {str(y2): act2_bool}
        },
        "balance": {
            str(y2): {
                "1600": tot2, "1230": recv2, "1170": invL2, "1240": invS2,
                "recv_share": ratio_recv, "invests_share": ratio_invest
            }
        },
        "signals": {"S1_prop_drop": S1, "S2_trans_vanish": S2, "S3_not_active": S3, "S4_paper_assets": S4}
    }

    # Require at least some external availability; otherwise mark N/A (to avoid guessing).
    if S1 is None and S2 is None and S3 is None:
        return _not_applicable("Нет внешних данных (__external__) для M19.", values)

    # Count external positives S1..S3
    ext_flags = [s for s in (S1, S2, S3) if s is True]
    ext_ok = len(ext_flags) >= 2
    balance_ok = (S4 is True)

    triggered = ext_ok and balance_ok
    points = 2 if triggered else 0

    why_parts = []
    why_parts.append(f"S1 (налог на имущество ~0): {'да' if S1 else 'нет' if S1 is not None else 'н/д'}")
    why_parts.append(f"S2 (транспортный налог исчез): {'да' if S2 else 'нет' if S2 is not None else 'н/д'}")
    why_parts.append(f"S3 (не подтверждена деятельность): {'да' if S3 else 'нет' if S3 is not None else 'н/д'}")
    why_parts.append(f"S4 (бумажные активы в балансе): {'да' if S4 else 'нет' if S4 is not None else 'н/д'}")
    why = "; ".join(why_parts) + (". Маркер сработал." if triggered else ". Условия не выполнены.")

    return {
        "code": "M19",
        "name": "Внебалансовые индикаторы (реестры)",
        "triggered": bool(triggered),
        "points": points,
        "why": why,
        "values": values,
    }


# -------- Aggregation / scoring for 16–19 --------

def compute_markers_16_to_19(data: Dict[str, Any]) -> Dict[str, Any]:
    m16 = marker_16_growth_in_short_term_investments(data)
    m17 = marker_17_working_capital_vs_creditors(data)
    m18 = marker_18_structural_anomalies(data)
    m19 = marker_19_off_balance_indicators(data)

    def ensure_code(obj: Dict[str, Any], code: str, name: str) -> Dict[str, Any]:
        obj.setdefault("code", code)
        obj.setdefault("name", name)
        return obj

    m16 = ensure_code(m16, "M16", "Рост краткосрочных финансовых вложений")
    m17 = ensure_code(m17, "M17", "Оборотка не растёт, кредиторка растёт")
    m18 = ensure_code(m18, "M18", "Структурные аномалии отчётности")
    m19 = ensure_code(m19, "M19", "Внебалансовые индикаторы (реестры)")

    markers = {x["code"]: x for x in [m16, m17, m18, m19]}

    total = sum(int(m.get("points", 0)) for m in markers.values())
    strong = sum(1 for m in markers.values() if int(m.get("points", 0)) >= 3)
    medium = sum(1 for m in markers.values() if int(m.get("points", 0)) == 2)

    autopass = False
    autopass_reason = None
    if strong >= 2:
        autopass, autopass_reason = True, "две сильные характеристики (>=3 баллов)"
    elif strong >= 1 and medium >= 2:
        autopass, autopass_reason = True, "1 сильная + 2 средние"
    elif total >= 10:
        autopass, autopass_reason = True, "сумма баллов ≥ 10"

    return {
        "years_available": available_years(data),
        "current_year_cap": CURRENT_YEAR,
        "markers": markers,
        "score_total": total,
        "autopass": autopass,
        "autopass_reason": autopass_reason,
    }


def run_rules_engine_markers_16_19(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Pure function wrapper for the 16–19 block."""
    return compute_markers_16_to_19(input_data)

# ----------------------- Global stitch (M1–M19) -----------------------

def _score_and_autopass(markers: Dict[str, Any]) -> Tuple[int, bool, Optional[str]]:
    total = sum(int(m.get("points", 0)) for m in markers.values())
    strong = sum(1 for m in markers.values() if int(m.get("points", 0)) >= 3)
    medium = sum(1 for m in markers.values() if int(m.get("points", 0)) == 2)

    autopass = False
    reason = None
    if strong >= 2:
        autopass, reason = True, "две сильные характеристики (>=3 баллов)"
    elif strong >= 1 and medium >= 2:
        autopass, reason = True, "1 сильная + 2 средние"
    elif total >= 10:
        autopass, reason = True, "сумма баллов ≥ 10"
    return total, autopass, reason


def compute_markers_all_1_to_19(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merges 1–5, 6–10, 11–15, 16–19 into a single result and applies global scoring.
    Assumes all marker functions & block compute_* funcs are already imported/defined.
    """
    block1 = compute_markers_1_to_5(data)
    block2 = compute_markers_6_to_10(data)
    block3 = compute_markers_11_to_15(data)
    block4 = compute_markers_16_to_19(data)

    markers = {}
    for blk in (block1, block2, block3, block4):
        markers.update(blk.get("markers", {}))

    total, autopass, reason = _score_and_autopass(markers)

    return {
        "years_available": available_years(data),
        "current_year_cap": CURRENT_YEAR,
        "markers": markers,                 # dict: {"M1": {...}, ..., "M19": {...}}
        "score_total": total,               # final score across 1–19
        "autopass": autopass,               # final decision by global thresholds
        "autopass_reason": reason,
        "by_sections": {
            "1_5":  block1.get("score_total", 0),
            "6_10": block2.get("score_total", 0),
            "11_15": block3.get("score_total", 0),
            "16_19": block4.get("score_total", 0),
        },
    }


def run_rules_engine_all(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Pure function wrapper for the full 1–19 set."""
    return compute_markers_all_1_to_19(input_data)


# ----------------------- Aggregation / scoring -----------------------

def _not_applicable(reason: str, values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "triggered": False,
        "points": 0,
        "why": f"Неприменимо: {reason}",
        "values": values or {},
        "not_applicable": True,
    }


def compute_markers_1_to_5(data: Dict[str, Any]) -> Dict[str, Any]:
    m1 = marker_1_negative_equity(data)
    m2 = marker_2_low_current_liquidity(data)
    m3 = marker_3_low_quick_liquidity(data)
    m4 = marker_4_low_absolute_liquidity(data)
    m5 = marker_5_drop_in_fixed_assets(data)

    # Attach codes/names if _not_applicable returned bare objects
    def ensure_code(obj: Dict[str, Any], code: str, name: str) -> Dict[str, Any]:
        obj.setdefault("code", code)
        obj.setdefault("name", name)
        return obj

    m1 = ensure_code(m1, "M1", "Отрицательный собственный капитал")
    m2 = ensure_code(m2, "M2", "Низкая текущая ликвидность")
    m3 = ensure_code(m3, "M3", "Низкая быстрая ликвидность")
    m4 = ensure_code(m4, "M4", "Низкая абсолютная ликвидность")
    m5 = ensure_code(m5, "M5", "Существенное сокращение основных средств")

    markers = {x["code"]: x for x in [m1, m2, m3, m4, m5]}

    # Score and simple autopass check (partial, based on implemented set).
    total = sum(int(m.get("points", 0)) for m in markers.values())
    strong = sum(1 for m in markers.values() if int(m.get("points", 0)) >= 3)
    medium = sum(1 for m in markers.values() if int(m.get("points", 0)) == 2)

    autopass = False
    autopass_reason = None
    if strong >= 2:
        autopass, autopass_reason = True, "две сильные характеристики (>=3 баллов)"
    elif strong >= 1 and medium >= 2:
        autopass, autopass_reason = True, "1 сильная + 2 средние"
    elif total >= 10:
        autopass, autopass_reason = True, "сумма баллов ≥ 10"

    return {
        "years_available": available_years(data),
        "current_year_cap": CURRENT_YEAR,
        "markers": markers,
        "score_total": total,
        "autopass": autopass,
        "autopass_reason": autopass_reason,
    }


# ------------------------------ Main ------------------------------

def run_rules_engine_markers_1_5(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pure function: no file I/O. Returns JSON-serializable dict.
    """
    return compute_markers_1_to_5(input_data)


# If you want to manual-test quickly:
if __name__ == "__main__":
    # Minimal smoke sample (feel free to remove):
    sample = {
        "Ф1.1250": {"name": "Денежные средства", "values": {"2022": "100", "2023": "50"}},
        "Ф1.1500": {"name": "Краткосрочные обязательства", "values": {"2022": "500", "2023": "800"}},
        "Ф1.1200": {"name": "Оборотные активы", "values": {"2022": "300", "2023": "700"}},
        "Ф1.1210": {"name": "Запасы", "values": {"2022": "100", "2023": "200"}},
        "Ф1.1300": {"name": "Капитал и резервы", "values": {"2022": "-10", "2023": "-5"}},
        "Ф1.1150": {"name": "Основные средства", "values": {"2022": "1000", "2023": "700"}},
    }
    import json
    out = run_rules_engine_markers_1_5(sample)
    print(json.dumps(out, ensure_ascii=False, indent=2))
