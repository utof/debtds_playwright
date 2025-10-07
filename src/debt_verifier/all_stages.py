def verify_stage0(
    contract_existence=None,
    legality_debt_transfer=None,
    debt_sum=None,
    debtor_inn=None,
    debtor_name=None,
) -> dict:
    """
    Этап 0 — Проверка наличия данных (не строгая).

    Возвращает словарь с полями:
      {
        "contract_existence": bool,
        "legality_debt_transfer": bool,
        "debt_sum": bool,
        "debtor_inn": bool,
        "debtor_name": bool
      }
    """
    return {
        "contract_existence": isinstance(contract_existence, bool),
        "legality_debt_transfer": isinstance(legality_debt_transfer, bool),
        "debt_sum": isinstance(debt_sum, (int, float)) and debt_sum > 0,
        "debtor_inn": isinstance(debtor_inn, (str, int)) and str(debtor_inn).strip() != "",
        "debtor_name": isinstance(debtor_name, str) and debtor_name.strip() != "",
    }


