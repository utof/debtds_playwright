from loguru import logger

def calculate_financial_coefficients(financial_data: dict) -> dict:
    """
    Calculates key financial coefficients based on parsed financial data from list-org.com.

    Args:
        financial_data: A dictionary containing financial data, structured by financial statement codes.
                        Example: {"Ф1.1600": {"values": {"2023": "1000", "2022": "950"}}, ...}

    Returns:
        A dictionary with calculated coefficients for each year.
        Example: {"2023": {"net_assets": 500, "absolute_liquidity_ratio": 1.5}, ...}
    """
    calculations = {}
    
    # Define the required financial codes for calculation
    required_codes = [
        'Ф1.1200', 'Ф1.1240', 'Ф1.1250', 'Ф1.1400', 
        'Ф1.1500', 'Ф1.1520', 'Ф1.1530', 'Ф1.1600'
    ]

    # Check if the main 'financials' key exists
    if 'financials' not in financial_data:
        logger.warning("Input data does not contain 'financials' key.")
        return {}

    data = financial_data['financials']

    # Find all unique years available in the data
    years = set()
    for code in required_codes:
        if code in data and 'values' in data[code]:
            years.update(data[code]['values'].keys())

    if not years:
        logger.warning("No financial data for any years found.")
        return {}

    # Helper to safely get and convert a numeric value
    def get_value(code, year):
        try:
            # Get value for code and year, default to '0' if not found
            value_str = data.get(code, {}).get('values', {}).get(year, '0')
            return int(value_str)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert value for code {code}, year {year} to int. Using 0.")
            return 0

    # Perform calculations for each year
    for year in sorted(list(years), reverse=True):
        logger.debug(f"Calculating coefficients for year: {year}")
        
        # Extract values for the current year
        v1600 = get_value('Ф1.1600', year)  # Активы
        v1400 = get_value('Ф1.1400', year)  # Долгосрочные обязательства
        v1500 = get_value('Ф1.1500', year)  # Краткосрочные обязательства
        v1530 = get_value('Ф1.1530', year)  # Целевое финансирование
        v1250 = get_value('Ф1.1250', year)  # Денежные средства
        v1240 = get_value('Ф1.1240', year)  # Финансовые вложения
        v1200 = get_value('Ф1.1200', year)  # Оборотные активы
        v1520 = get_value('Ф1.1520', year)  # Кредиторская задолженность

        # Perform calculations
        try:
            # 1. Чистые активы (Net Assets)
            net_assets = v1600 - v1400 - v1500 + v1530

            # 2. Коэффициент абсолютной ликвидности (Absolute Liquidity Ratio)
            abs_liq_ratio = (v1250 + v1240) / v1520 if v1520 != 0 else None

            # 3. Коэффициент текущей ликвидности (Current Liquidity Ratio)
            cur_liq_ratio = v1200 / v1500 if v1500 != 0 else None

            # 4. Коэффициент обеспеченности обязательств активами (Asset-Liability Ratio)
            asset_lia_ratio = v1600 / (v1400 + v1500) if (v1400 + v1500) != 0 else None

            # 5. Степень платёжеспособности по текущим обязательствам (Solvency Ratio)
            solvency_ratio = v1200 / v1520 if v1520 != 0 else None

            calculations[year] = {
                "net_assets": net_assets,
                "absolute_liquidity_ratio": abs_liq_ratio,
                "current_liquidity_ratio": cur_liq_ratio,
                "asset_liability_ratio": asset_lia_ratio,
                "solvency_ratio": solvency_ratio,
            }
            logger.info(f"Successfully calculated coefficients for {year}.")

        except Exception as e:
            logger.error(f"An error occurred during calculation for year {year}: {e}")
            calculations[year] = {"error": str(e)}

    return calculations