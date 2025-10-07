LATEST_YEAR = 2024  # global, easy to adjust

def all_missing_or_empty(data: list) -> bool:
    """
    Returns True if ALL 'Ф...' entries either:
      1. don't contain keys for 2024, 2023, 2022, OR
      2. have all of them as empty strings ("").

    Args:
        data (list): Array of dicts in the expected format.

    Returns:
        bool: True if all items are missing or empty for the 3 years.
    """
    target_years = [str(LATEST_YEAR - i) for i in range(3)]

    for item in data:
        for block in item.values():
            values = block.get("values", {})

            # Case 1: doesn't contain any of the target years
            has_any_year = any(y in values for y in target_years)
            if not has_any_year:
                continue  # skip, this one counts as "missing"

            # Case 2: has them, but all empty strings
            all_empty = all(
                (values.get(y, "") or "").strip() == "" for y in target_years
            )
            if not all_empty:
                # Found at least one block that breaks the rule
                return False

    # All blocks are either missing or have empty values
    return True

def is_monodecreasing_last_3_years(values: dict) -> bool:
    """
    Checks if the given year's values are monotonically decreasing
    (each next year <= previous) over the last 3 years:
    LATEST_YEAR, LATEST_YEAR-1, LATEST_YEAR-2.

    Args:
        values (dict): {year: value, ...}

    Returns:
        bool: True if decreasing or equal, False otherwise.
    """
    target_years = [str(LATEST_YEAR - i) for i in range(3)]
    seq = []

    for year in target_years:
        val = values.get(year)
        if val is None or str(val).strip() == "":
            # missing data breaks the check
            return False
        try:
            seq.append(float(val))
        except ValueError:
            return False

    # Check monotone decreasing: 2024 >= 2023 >= 2022
    return all(seq[i] >= seq[i + 1] for i in range(len(seq) - 1))

def too_many_missing_revenue_assets(vyruchka: dict, osnovnye: dict) -> bool:
    """
    Checks whether more than 3 of the last 3 years' combined values
    (выручка + основные средства) are missing or empty.

    Missing keys are treated as empty.

    Args:
        vyruchka (dict): e.g. {'2024': '...', '2023': '...', '2022': '...'}
        osnovnye (dict): same format

    Returns:
        bool: True if >3 of 6 possible cells are missing/empty.
    """
    target_years = [str(LATEST_YEAR - i) for i in range(3)]
    empty_count = 0

    for year in target_years:
        # выручка
        val1 = vyruchka.get(year)
        if val1 is None or str(val1).strip() == "":
            empty_count += 1

        # основные средства
        val2 = osnovnye.get(year)
        if val2 is None or str(val2).strip() == "":
            empty_count += 1

    return empty_count > 3

def evaluate_debt_verification(points: float, comments: list[str]) -> dict:
    """
    Evaluates debt verification status based on total points.

    Args:
        points (float | int): Total score (from -137 to 13 typically).
        comments (list[str]): Collected textual reasons (may be empty).

    Returns:
        dict: {
            "verified": bool,
            "status": str,
            "reason": str
        }
    """
    # Define ranges
    if 11 <= points <= 13:
        status = "долг верифицирован с 80% уверенностью"
        verified = True
        reason = "Переход к юридической стадии верификации."
    elif -37 <= points <= 10:
        status = "долг условно верифицирован"
        verified = True
        reason = "Переход к юридической стадии верификации."
    elif -109 <= points <= -93:
        status = "долг не верифицирован"
        verified = False
        reason = "Долг не верифицирован.\nПричины:\n" + "\n".join(comments)
    elif -148 <= points <= -110:
        status = "долг не верифицирован с 80% уверенностью, рекомендуем списание"
        verified = False
        reason = (
            "Долг не верифицирован с 80% уверенностью, рекомендуем списание.\n"
            "Причины:\n" + "\n".join(comments)
        )
    else:
        status = "неопределённый результат"
        verified = False
        reason = (
            f"Баллы ({points}) вне ожидаемых диапазонов. Проверьте входные данные.\n"
            "Причины:\n" + "\n".join(comments)
        )

    return {
        "verified": verified,
        "status": status,
        "reason": reason.strip()
    }

