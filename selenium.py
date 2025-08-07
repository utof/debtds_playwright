import requests
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from seleniumwire import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
import json
from io import BytesIO
import openpyxl
import re
import random
from config import PROXYS, BASE_URL
from typing import Optional
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Конфигурация
INN = "7811151966"
SEARCH_URL = f"{BASE_URL}/search"


def get_random_proxy():
    """Возвращает случайный прокси из списка"""
    return random.choice(PROXYS)

def setup_selenium():
    # chrome_path = "/usr/bin/google-chrome"
    # driver_path = "/usr/local/bin/chromedriver"


    chrome_options = Options()
    # chrome_options.binary_location = chrome_path
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')

    # Настройка прокси через Selenium Wire
    proxy = get_random_proxy()
    seleniumwire_options = {
        'proxy': {
            'http': proxy['http'],
            'https': proxy['https'],
            'no_proxy': 'localhost,127.0.0.1'
        },
        'verify_ssl': False
    }

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(
        service=service,
        options=chrome_options,
        seleniumwire_options=seleniumwire_options)
    return driver


def get_excel_url_and_founders(driver, company_url):
    """Получает ссылку на Excel и данные об учредителях через Selenium"""
    result = {
        "excel_url": None,
        "Учредители": [],
        "Арбитраж": [],
        "Исполнительные производства по данным fssprus.ru": []
    }

    try:
        driver.get(company_url)

        # 1. Проверяем наличие и нажимаем кнопку "Показать еще" (может быть несколько нажатий)
        while True:
            try:
                show_more_button = WebDriverWait(driver, 1).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "a[id='id_all_arb']"))   
                )
                if "Показать еще" in show_more_button.text:
                    driver.execute_script("arguments[0].click();", show_more_button)      
                    # Ждем обновления таблицы
                    WebDriverWait(driver, 1).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "table.tt tr:last-child"))
                    )
                    # Небольшая пауза для стабилизации
                    time.sleep(1)
                else:
                    break
            except (TimeoutException, NoSuchElementException):
                break  # Кнопки нет или больше не появляется

        # . Собираем все данные из таблицы
        table = driver.find_element(By.CSS_SELECTOR, "table.tt.f08")
        rows = table.find_elements(By.CSS_SELECTOR, "tr")[1:]  # Пропускаем заголовок     

        for row in rows:
            try:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 4:  # Проверяем минимальное количество ячеек
                    # Обрабатываем номер дела (может быть ссылкой или текстом)
                    case_number = ""
                    case_link = ""
                    try:
                        link = cells[0].find_element(By.TAG_NAME, "a")
                        case_number = link.text.strip()
                        case_link = link.get_attribute("href")
                    except NoSuchElementException:
                        case_number = cells[0].text.strip()

                    # Формируем данные по делу
                    case_data = {
                        "Номер дела": case_number,
                        "Ссылка": case_link,
                        "Дата": cells[1].text.strip(),
                        "Сторона": cells[2].text.strip(),
                        "Описание": cells[3].text.strip() if len(cells) > 3 else ""       
                    }
                    result['Арбитраж'].append(case_data)
            except Exception as e:
                print(f"Ошибка при обработке строки таблицы: {e}")

        try:
            # Ждем появления заголовка таблицы
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(., 'Исполнительные производства по данным fssprus.ru')]"))
            )

            # Находим таблицу с исполнительными производствами
            table = driver.find_elements(By.CSS_SELECTOR, "table.tt")[-1]
            rows = table.find_elements(By.CSS_SELECTOR, "tr:not(:has(th))")  # Пропускаем строку с заголовками

            current_status = None  # Для хранения текущего статуса (Открыто/Окончено)     

            for row in rows:
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")

                    # Определяем статус (может быть объединен через rowspan)
                    if len(cells) >= 4:  # Полная строка со статусом
                        status_cell = cells[0]
                        if status_cell.text.strip():
                            current_status = status_cell.text.strip()
                        subject = cells[1].text.strip()
                        count_debt = cells[2].text.strip()
                        date = cells[3].text.strip()
                    elif len(cells) == 3:  # Строка продолжения с объединенным статусом   
                        subject = cells[0].text.strip()
                        count_debt = cells[1].text.strip()
                        date = cells[2].text.strip()
                    else:
                        continue  # Пропускаем некорректные строки

                    # Парсим количество и сумму долга
                    count = None
                    debt_amount = None
                    if "/" in count_debt:
                        parts = count_debt.split("/")
                        count = int(parts[0].strip())
                        debt_match = re.search(r"(\d[\d\s]*)", parts[1])
                        if debt_match:
                            debt_amount = int(debt_match.group(1).replace(" ", ""))       
                    else:
                        count = int(count_debt.strip()) if count_debt.strip().isdigit() else None

                    # Формируем запись
                    record = {
                        "Статус": current_status,
                        "Предмет исполнения": subject,
                        "Количество": count,
                        "Сумма долга (руб)": debt_amount,
                        "Дата последнего": date
                    }
                    result['Исполнительные производства по данным fssprus.ru'].append(record)

                except Exception as e:
                    # print(f"Ошибка при обработке строки: {str(e)}")
                    continue
        except Exception as e:
            result['Исполнительные производства по данным fssprus.ru'] = "Не найдены (по ИНН)"

        # 1. Ищем ссылку на Excel
        WebDriverWait(driver, 1).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.a_link_xls"))
        )
        excel_element = driver.find_element(By.CSS_SELECTOR, "a.a_link_xls")
        excel_href = excel_element.get_attribute("href")

        if excel_href.startswith("http"):
            result["excel_url"] = excel_href
        else:
            result["excel_url"] = BASE_URL + excel_href

    except TimeoutException:
        print("Таблица исполнительных производств не найдена")
    except Exception as e:
        print(f"Ошибка: {e}")

    # print(result['Исполнительные производства по данным fssprus.ru'])
    return result


def download_excel_to_memory(excel_url, cookies):
    """Скачивание файла в память через requests"""
    try:
        session = requests.Session()
        session.cookies.update(cookies)
        # Используем прокси из настроек Selenium
        session.proxies = get_random_proxy()

        response = session.get(
            excel_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': BASE_URL
            },
            stream=True,
            timeout=30
        )
        response.raise_for_status()

        in_memory_file = BytesIO()
        for chunk in response.iter_content(8192):
            in_memory_file.write(chunk)
        in_memory_file.seek(0)
        return in_memory_file
    except Exception as e:
        print(f"Ошибка при скачивании: {e}")
        return None


def parse_excel_with_multiple_tables(excel_file):
    """Парсинг Excel с учётом нескольких таблиц на одном листе"""
    result = {
        "company_info": {},
        "financial_statements": [],
        "tax_info": []
    }

    try:
        wb = openpyxl.load_workbook(excel_file, data_only=True)
        sheet = wb.active
        current_section = None
        years_finance = []
        years_tax = []
        parsing_financials = False
        parsing_tax = False

        for row in sheet.iter_rows(values_only=True):
            if not row or all(cell is None for cell in row):
                continue

            first_cell = str(row[0]).strip() if row[0] else ""

            # Определяем начало новых разделов
            if "Краткое наименование" in first_cell:
                current_section = "company_info"
                parsing_financials = parsing_tax = False
            elif "Финансовая (бухгалтерская) отчетность" in first_cell:
                current_section = "financial_statements"
                years_finance = []
                parsing_financials = True
                parsing_tax = False
                continue
            elif "НАЛОГОВЫЕ ДОХОДЫ" in first_cell:  # исправлено
                current_section = "tax_info"
                years_tax = []
                parsing_tax = True
                parsing_financials = False
                continue
            elif "Показатель" in first_cell:
                if parsing_financials:
                    years_finance = [cell for cell in row[3:] if isinstance(cell, int)]
                    continue
                elif parsing_tax:
                    current_section = "tax_info"
                    parsing_tax = True
                    parsing_financials = False
                    years_tax = [cell for cell in row[2:] if isinstance(cell, int)]       
                    continue
                else:
                    current_section = "tax_info"
                    years_tax = []
                    parsing_tax = True
                    parsing_financials = False
                    continue

            # company_info
            if current_section == "company_info":
                if len(row) >= 2 and row[0] and row[1]:
                    key = str(row[0]).strip().replace(":", "")
                    value = str(row[1]).strip()
                    result["company_info"][key] = value

            # financial_statements
            elif current_section == "financial_statements" and years_finance:
                if row[0] and row[1] and row[2]:
                    statement = {
                        "indicator": str(row[0]).strip(),
                        "code": str(row[1]).strip(),
                        "unit": str(row[2]).strip(),
                        "values": []
                    }
                    for idx, year in enumerate(years_finance):
                        cell_idx = 3 + idx
                        if cell_idx < len(row) and row[cell_idx] is not None:
                            statement["values"].append({
                                "year": year,
                                "value": row[cell_idx]
                            })
                    if statement["values"]:
                        result["financial_statements"].append(statement)

            # tax_info
            elif current_section == "tax_info" and years_tax:
                if row[0] and row[1]:
                    tax_data = {
                        "indicator": str(row[0]).strip(),
                        "unit": str(row[1]).strip(),
                        "values": []
                    }
                    for idx, year in enumerate(years_tax):
                        cell_idx = 2 + idx
                        if cell_idx < len(row) and row[cell_idx] is not None:
                            tax_data["values"].append({
                                "year": year,
                                "value": row[cell_idx]
                            })
                    if tax_data["values"]:
                        result["tax_info"].append(tax_data)

        return result

    except Exception as e:
        return {"error": str(e)}


# Пример использования:
# data = parse_excel_data_dynamic_years("your_file.xlsx")
# with open("output.json", "w", encoding="utf-8") as f:
#     json.dump(data, f, ensure_ascii=False, indent=2)

def parse_amount(text):
    """Конвертирует текстовое представление суммы в число"""
    if not text:
        return None

    match = re.search(r'(\d+\.?\d*)\s*тыс', text)
    if match:
        try:
            return int(float(match.group(1)) * 1000)
        except ValueError:
            return None

    match = re.search(r'(\d+)', text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None

    return None


def parse_founders_table(soup):
    """Парсит таблицу учредителей из BeautifulSoup объекта"""
    founders = []
    table = soup.find('table', {'class': 'tt f08m'})

    if not table:
        return founders

    rows = table.find_all('tr')[1:]  # Пропускаем заголовок

    for row in rows:
        # Пропускаем строки с кнопкой "показать все"
        if row.find('a', href=lambda x: x and 'founders_history' in x):
            continue

        cells = row.find_all('td')
        if len(cells) < 4:
            continue

        name_link = cells[0].find('a')
        name = name_link.get_text(strip=True) if name_link else cells[0].get_text(strip=True)
        name_url = name_link['href'] if name_link else None

        inn = cells[1].get_text(strip=True) if len(cells) > 1 else None
        share = cells[2].get_text(strip=True) if len(cells) > 2 else None
        amount_text = cells[3].get_text(strip=True) if len(cells) > 3 else None

        founders.append({
            "Наименование": name,
            "Ссылка": f"https://www.list-org.com{name_url}" if name_url else None,        
            "ИНН": inn,
            "Доля": share,
            "Сумма": parse_amount(amount_text)
        })

    return founders


def get_company_founders(company_id):
    """Получает данные об учредителях компании"""
    base_url = f"https://www.list-org.com/company/{company_id}"
    history_url = f"{base_url}/founders_history"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        # 1. Проверяем основную страницу
        response = requests.get(base_url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 2. Ищем ссылку на историю учредителей
        # Способ 1: Ищем по тексту ссылки
        history_link = soup.find('a', string=re.compile(r'показать все', re.IGNORECASE))  

        if history_link:
            # 3. Если есть история - парсим ее
            response = requests.get(history_url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            founders = parse_founders_table(soup)
            return {"source": "history_page", "founders": founders}
        else:
            # 4. Если истории нет - парсим основную страницу
            founders = parse_founders_table(soup)
            return {"source": "main_page", "founders": founders}

    except requests.exceptions.RequestException as e:
        return {"error": f"Ошибка при запросе: {str(e)}"}
    except Exception as e:
        return {"error": f"Общая ошибка: {str(e)}"}


# Константы (обратите внимание на русскую 'С' в начале)
СBASE_URL = "https://companium.ru/search/tips?query="
СDETAILS_URL = "https://companium.ru"
DELAY_RANGE = (1, 3)
СCOOKIES = {
    '_ym_uid': '1747066760757332821',
    '_ym_isad': '2',
    '_companium_ru_session': 'xc%2F4BDXj6uc62w%2FzDNZNeG%2B1JkJYcD4Mt15Napzw5xdZ9RS1ZRMqAm4G1UZgkAdjvp5Fy0cTtKtcCiqCqN19BZpoDgc0lHye4dFAzjJLd9DEr5lYEpCvI4tJElzX5DrQHb8vwWoffDZxkAflbHJuaxeJ%2BLeKW%2FJ%2B6Y%2Fxw9AEwlIyS7nWRVyAHo%2FCSRDyvBUYvyPZaK%2B3R5RHYvCJbyRowR%2FMXbO6YUh%2F8lZeKVZdPCfO37FhjYc1SeC7tb0N40s9DggseZ3cBFcyDS79kgnT5CeGXTn7k9i88ZSs6%2BM%3D--rDEsdVTSYE%2FkEQVa--N8LadXM8e7WFcRFXlln98g%3D%3D',
    '_ym_d': '1747591126'
}
СHEADERS = {
    'authority': 'companium.ru',
    'accept': '*/*',
    'accept-language': 'ru,en;q=0.9,en-GB;q=0.8,en-US;q=0.7',
    'referer': 'https://companium.ru/',
    'sec-ch-ua': '"Chromium";v="136", "Microsoft Edge";v="136", "Not.A/Brand";v="99"',    
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0'
}


def extract_link(content: str) -> Optional[str]:
    try:
        href_start = content.find('href="') + 6
        href_end = content.find('"', href_start)
        return content[href_start:href_end]
    except (IndexError, ValueError):
        return None


def random_delay():
    time.sleep(random.uniform(*DELAY_RANGE))

def parse_company_status(html: str) -> str:
    """Извлекает статус компании из HTML"""

    soup = BeautifulSoup(html, 'html.parser')

    # Ищем статус в трех возможных вариантах (как в оригинальном парсере)
    status_div = soup.find('div', class_="text-success fw-bold")  # Действующая
    if not status_div:
        status_div = soup.find('div', class_="text-danger fw-bold")  # Ликвидирована      
    if not status_div:
        status_div = soup.find('div', class_="fw-bold special-status")  # Другой статус   
    if not status_div:
        status_div = soup.find('div', class_="fw-bold text-danger")

    if status_div:
        # Убираем лишние пробелы и переносы строк
        return ' '.join(status_div.get_text(strip=True).split())
    return "Статус не определен"


def companium_parser(inn: str) -> str:
    """Возвращает статус компании по ИНН с использованием прокси"""
    result = {
        'status': "",
        'error': None
    }

    session = requests.Session()
    session.headers.update(СHEADERS)
    session.cookies.update(СCOOKIES)

    # Получаем случайный прокси из вашего списка
    proxy = get_random_proxy()
    session.proxies = {
        'http': proxy['http'],
        'https': proxy['https']
    }

    try:
        # 1. Поиск компании по ИНН
        random_delay()
        search_url = f"{СBASE_URL}{inn}"
        response = session.get(
            search_url,
            timeout=30,
            verify=False  # Отключаем проверку SSL для работы через прокси
        )

        if response.status_code != 200:
            result['error'] = f"Ошибка поиска: HTTP {response.status_code}"
            return result['error']

        # 2. Извлечение ссылки
        data = response.json()
        if not data or not isinstance(data, list):
            result['error'] = "Компания не найдена"
            return result['error']

        first_result = data[0]
        link = extract_link(first_result.get('content', ''))
        if not link:
            result['error'] = "Не удалось извлечь ссылку на компанию"
            return result['error']

        company_url = f"{СDETAILS_URL}{link}"

        # 3. Загрузка страницы компании
        random_delay()
        company_response = session.get(
            company_url,
            timeout=30,
            verify=False
        )
        if company_response.status_code != 200:
            result['error'] = f"Ошибка загрузки страницы: HTTP {company_response.status_code}"
            return result['error']

        html = company_response.text
        result['status'] = parse_company_status(html)

    except requests.exceptions.ProxyError as e:
        result['error'] = f"Ошибка прокси: {str(e)}"
    except requests.exceptions.SSLError as e:
        result['error'] = f"SSL ошибка: {str(e)}"
    except requests.exceptions.RequestException as e:
        result['error'] = f"Ошибка сети: {str(e)}"
    except Exception as e:
        result['error'] = f"Неожиданная ошибка: {str(e)}"

    if result['error']:
        return result['error']

    return result['status']


def main(inn):
    driver = None
    result = {
        "success": False,
        "company_url": "",
        "excel_url": "",
        "data": None,
        "error": None,
        "user_proxy": None
    }

    try:
        driver = setup_selenium()
        result["used_proxy"] = driver.proxy  # Записываем используемый прокси

        time.sleep(1)
        # Поиск компании
        session = requests.Session()
        search_response = session.get(
            SEARCH_URL,
            params={"val": inn, "type": "inn", "sort": ""},
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        search_response.raise_for_status()

        # Парсим ID компании
        soup = BeautifulSoup(search_response.text, 'html.parser')
        company_link = soup.find('a', href=lambda x: x and '/company/' in x)
        if not company_link:
            result["error"] = "Компания не найдена"
            return result

        company_id = company_link['href'].split('/')[-1]
        company_url = f"{BASE_URL}/company/{company_id}"
        result["company_url"] = company_url

        # Получаем ссылку на Excel
        d = get_excel_url_and_founders(driver, company_url)
        # founders_data = d['founders']
        arb_data = d["Арбитраж"]
        manufacture_data = d['Исполнительные производства по данным fssprus.ru']
        excel_url = d['excel_url']
        if not excel_url:
            result["error"] = "Не удалось получить ссылку на Excel"
            return result

        result["excel_url"] = excel_url

        # Собираем cookies из Selenium
        selenium_cookies = {c['name']: c['value'] for c in driver.get_cookies()}

        # Скачиваем файл в память
        excel_file = download_excel_to_memory(excel_url, selenium_cookies)
        if not excel_file:
            result["error"] = "Не удалось скачать файл"
            return result

        # Парсим данные из Excel
        parsed_data = parse_excel_with_multiple_tables(excel_file)
        if not parsed_data:
            result["error"] = "Не удалось распарсить данные из Excel"
            return result

        result["data"] = parsed_data
        result["data"]['company_info']['Статус'] = companium_parser(inn)
        result["data"]["Учредители"] = get_company_founders(company_id)
        result["data"]["Арбитраж"] = arb_data
        result["data"]["Исполнительные производства по данным fssprus.ru"] = manufacture_data
        result["success"] = True

        # result["data"]["company_info"]["Блокировка банковских счетов"] = block_info     

        return result

    except Exception as e:
        result["error"] = str(e)
        return result
    finally:
        if driver:
            driver.quit()
        # print("Завершение работы")


if __name__ == "__main__":
    start = time.time()
    print(main(INN))
    finish = time.time()
    print(finish - start)