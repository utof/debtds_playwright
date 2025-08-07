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