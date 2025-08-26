from loguru import logger
def process_inn(inn: str) -> str:
    # if inn is None then throw ValueError,
    # if not a string then convert to string
    # if 9 digits then add leading zero
    if inn is None:
        raise ValueError("INN cannot be None")
    if not isinstance(inn, str):
        inn = str(inn)
    if not inn.isdigit():
        raise ValueError("INN must contain only digits")
    if len(inn) == 9:
        inn = '0' + inn
    if len(inn) < 9 or len(inn) > 10:
        raise ValueError("INN must be 9 or 10 digits long")
    return inn

def calculate_financial_coefficients(financial_data: dict) -> dict:
    """
    Calculates key financial coefficients based on parsed financial data from list-org.com.
    Returns per-year values or short 'undefined, ...' reasons when impossible to compute.
    """
    calculations = {}

    required_codes = [
        'Ф1.1200', 'Ф1.1240', 'Ф1.1250', 'Ф1.1400',
        'Ф1.1500', 'Ф1.1520', 'Ф1.1530', 'Ф1.1600', 'Ф2.2000'
    ]

    # if 'financials' not in financial_data:
    #     logger.warning("Input data does not contain 'financials' key.")
    #     return {}

    # data = financial_data['financials']
    data = financial_data

    if not financial_data:
        logger.warning("input data is empty")
        return {}
    
    # Gather all years present across any required code
    years = set()
    for code in required_codes:
        vals = data.get(code, {}).get('values', {})
        if isinstance(vals, dict):
            years.update(vals.keys())

    if not years:
        logger.warning("No financial data for any years found.")
        return {}

    # --- helpers -------------------------------------------------------------

    def _parse_int_or_reason(val, code) -> tuple[int | None, str | None]:
        """Try to parse int, return (value, None) or (None, reason)."""
        if val is None or val == "" or (isinstance(val, str) and val.strip().lower() in {"nan", "null", "none"}):
            return None, f"нет значения {code}"
        try:
            # accept strings like "1 234", "1,234" (we expect integers in input)
            s = str(val).replace("\xa0", " ").strip()
            s = s.replace(" ", "")
            s = s.replace(",", "")  # incoming are usually integers; strip commas
            return int(s), None
        except Exception:
            return None, f"не число {code}"

    def getv(code: str, year: str) -> tuple[int | None, str | None]:
        """
        Return (value, None) if ok; otherwise (None, short_reason).
        Short reasons are Russian & minimal for AI context.
        """
        if code not in data:
            return None, f"нет {code}"
        values = data[code].get('values')
        if not isinstance(values, dict):
            return None, f"нет {code}"
        if year not in values:
            return None, f"нет значения {code}"
        return _parse_int_or_reason(values[year], code)

    def combine_or_number(val_err_list, op):
        """
        val_err_list: list of (value, reason) for required inputs.
        If any reason present -> return (None, combined_reason)
        Else return (computed_value, None) via op(values).
        """
        reasons = [r for _, r in val_err_list if r]
        if reasons:
            # de-duplicate while preserving order; keep it tight
            seen = set()
            uniq = []
            for r in reasons:
                if r not in seen:
                    uniq.append(r)
                    seen.add(r)
            return None, "; ".join(uniq)
        try:
            return op([v for v, _ in val_err_list]), None
        except ZeroDivisionError:
            return None, "деление на 0"
        except Exception as e:
            logger.error(f"Unexpected error in combine_or_number: {e}")
            return None, "ошибка вычисления"

    # --- per-year calculations ----------------------------------------------

    for year in sorted(years, reverse=True):
        logger.debug(f"Calculating coefficients for year: {year}")

        # Fetch inputs
        v1600 = getv('Ф1.1600', year)  # Активы
        v1400 = getv('Ф1.1400', year)  # Долгосрочные обязательства
        v1500 = getv('Ф1.1500', year)  # Краткосрочные обязательства
        v1530 = getv('Ф1.1530', year)  # Целевое финансирование
        v1250 = getv('Ф1.1250', year)  # Денежные средства
        v1240 = getv('Ф1.1240', year)  # Финансовые вложения
        v1200 = getv('Ф1.1200', year)  # Оборотные активы
        v1520 = getv('Ф1.1520', year)  # Кредиторская задолженность
        v2400 = getv('Ф2.2400', year)  # Убытки (или прибыль со знаком)

        year_out = {}

        # 1) Net assets: v1600 - v1400 - v1500 + v1530
        net_assets, na_reason = combine_or_number(
            [v1600, v1400, v1500, v1530],
            lambda vs: vs[0] - vs[1] - vs[2] + vs[3]
        )
        year_out["net_assets"] = net_assets if na_reason is None else f"undefined, {na_reason}"

        # 2) Absolute liquidity: (v1250 + v1240) / v1520
        def _abs_liq(values):
            num = values[0] + values[1]
            den = values[2]
            if den == 0:
                raise ZeroDivisionError
            return num / den

        abs_liq, al_reason = combine_or_number([v1250, v1240, v1520], _abs_liq)
        year_out["absolute_liquidity_ratio"] = abs_liq if al_reason is None else f"undefined, {al_reason}"

        # 3) Current liquidity: v1200 / v1500
        def _cur_liq(values):
            num, den = values
            if den == 0:
                raise ZeroDivisionError
            return num / den

        cur_liq, cl_reason = combine_or_number([v1200, v1500], _cur_liq)
        year_out["current_liquidity_ratio"] = cur_liq if cl_reason is None else f"undefined, {cl_reason}"

        # 4) Asset-liability ratio: v1600 / (v1400 + v1500)
        def _al_ratio(values):
            a, d1, d2 = values
            den = d1 + d2
            if den == 0:
                raise ZeroDivisionError
            return a / den

        asset_lia, alr_reason = combine_or_number([v1600, v1400, v1500], _al_ratio)
        year_out["asset_liability_ratio"] = asset_lia if alr_reason is None else f"undefined, {alr_reason}"

        # 5) Solvency ratio: v1200 / v1520
        def _solv(values):
            num, den = values
            if den == 0:
                raise ZeroDivisionError
            return num / den

        solv, solv_reason = combine_or_number([v1200, v1520], _solv)
        year_out["solvency_ratio"] = solv if solv_reason is None else f"undefined, {solv_reason}"

        # 6) Losses: just pass through, but explain if undefined
        losses_val, losses_reason = v2400
        year_out["losses"] = losses_val if losses_reason is None else f"undefined, {losses_reason}"

        calculations[year] = year_out
        logger.info(f"Calculated for {year}: {year_out}")

    return calculations
