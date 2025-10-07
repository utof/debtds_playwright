
def evaluate_claim_terms(case_date: float, company_status: str, time_to_claim: float) -> dict:
    """
    Оценивает сроки подачи иска.
    Возвращает {"points": int, "comment": str}.
    
    Параметры:
      case_date — сколько лет прошло с момента события (float)
      company_status — строка, статус компании
      time_to_claim — сколько лет прошло с момента возможного иска (float)
    """

    company_status = (company_status or "").strip().lower()

    # --- 1. case_date < 3 лет ---
    if case_date < 3:
        return {"points": 2, "comment": ""}

    # --- 2. >3 лет, действующая, и time_to_claim < 3 лет ---
    if case_date > 3 and "действ" in company_status and time_to_claim < 3:
        return {"points": 1, "comment": ""}

    # --- 3. >3 лет, действующая, и time_to_claim > 3.33 лет ---
    if case_date > 3 and "действ" in company_status and time_to_claim > 3.33:
        return {"points": -100, "comment": "Долг не верифицирован, сроки подачи иска пропущены"}

    # --- 4. >3 лет, действующая, time_to_claim в [3; 3.33] лет ---
    if case_date > 3 and "действ" in company_status and 3 <= time_to_claim <= 3.33:
        return {
            "points": -5,
            "comment": (
                "Сроки подачи иска пропущены, однако если ИП прекращено по ст. 46 ч.1 п.3, "
                "и пристав не смог установить местонахождение или имущество должника — "
                "долг можно условно верифицировать."
            )
        }

    # --- 5. исключен из ЕГРЮЛ (реорганизация, недостоверность сведений, иное) ---
    if "исключен" in company_status and any(
        kw in company_status
        for kw in ["реорган", "недостовер", "иное"]
    ):
        return {
            "points": 1,
            "comment": (
                "Взыскание возможно только при привлечении к субсидиарной ответственности "
                "при наличии активов у КДЛ."
            )
        }

    # --- 6. исключен из ЕГРЮЛ: конкурсное производство ---
    if "исключен" in company_status and "конкурс" in company_status:
        return {
            "points": -100,
            "comment": "Компания ликвидирована (конкурсное производство), долг не верифицирован."
        }

    # fallback
    return {"points": 0, "comment": "нет подходящего условия"}



def evaluate_debt_confirmation(case_sum, sum_difference) -> dict:
    """
    Оценивает подтверждение суммы долга.
    Принимает case_sum (число или пустая строка) и sum_difference (число).
    Возвращает словарь {"points": int, "comment": str}.
    """

    # --- Check case_sum conditions ---
    if isinstance(case_sum, (int, float)) and case_sum > 0:
        return {
            "points": 2,
            "comment": "сумма долга подтверждена судебным решением"
        }

    if case_sum == "" or case_sum is None:
        return {
            "points": -50,
            "comment": "сумма долга не подтверждена судебным решением, долг не верифицирован"
        }

    # --- Check sum_difference conditions ---
    if sum_difference >= 0.7 and sum_difference <= 1.3:
        return {
            "points": 2,
            "comment": "сумма долга близка к сумме в судебном решении"
        }

    if sum_difference > 1.3:
        return {
            "points": -1,
            "comment": "сумма долга отличается от судебного решения и на 30% выше заявленной суммы"
        }

    if sum_difference < 0.7:
        return {
            "points": -1,
            "comment": "сумма долга отличается от судебного решения и на 30% ниже заявленной суммы"
        }

    return {"points": 0, "comment": "нет данных для оценки"}


def evaluate_case_status(case_status: str) -> dict:
    """
    Определяет баллы и комментарий по статусу судебного дела.
    Возвращает словарь {"points": int, "comment": str}.
    """

    mapping = {
        "Судебное решение в силе": {
            "points": 5,
            "comment": ""
        },
        "Дело оставлено без рассмотрения": {
            "points": 2,
            "comment": "повторно подать иск"
        },
        "Отказ от иска со стороны кредитора": {
            "points": -100,
            "comment": "невозможно подать повторный иск, юридически долг не верифицирован"
        },
    }

    # normalize input a bit
    key = case_status.strip().lower()

    for k, v in mapping.items():
        if k.lower() in key:
            return v

    return {"points": 0, "comment": "неизвестный статус"}


def evaluate_legal_verification(points: float, comments: list[str]) -> dict:
    """
    Evaluates the legal-stage debt verification based on points.

    Args:
        points (float | int): Total score (e.g. -250 .. 12)
        comments (list[str]): Collected reasons (optional)

    Returns:
        dict: {
            "verified": bool,
            "status": str,
            "reason": str
        }
    """
    if 5 <= points <= 12:
        status = "долг верифицирован с 80% уверенностью"
        verified = True
        reason = "Переход к следующему этапу юридической верификации."
    elif -42 <= points <= 4:
        status = "долг условно верифицирован, необходимы дополнительные данные для верификации"
        verified = True
        reason = (
            "Переход к следующему этапу юридической верификации. "
            "Необходим сбор дополнительных данных."
        )
    elif -89 <= points <= -43:
        status = "долг условно верифицирован, сумма долга не подтверждена судебным решением"
        verified = True
        reason = (
            "Переход к следующему этапу юридической верификации. "
            "Требуется подтверждение суммы долга судебным решением."
        )
    elif -250 <= points <= -90:
        status = (
            "долг не верифицирован юридически. имеются критические пороки, "
            "рекомендуем списание"
        )
        verified = False
        reason = (
            "Долг не верифицирован юридически, переход к следующему этапу невозможен.\n"
            "Причины:\n" + "\n".join(comments)
        )
    else:
        status = "неопределённый результат юридической оценки"
        verified = False
        reason = (
            f"Баллы ({points}) вне ожидаемых диапазонов. Проверьте данные.\n"
            "Причины:\n" + "\n".join(comments)
        )

    return {
        "verified": verified,
        "status": status,
        "reason": reason.strip()
    }

