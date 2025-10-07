import os
from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv()

class Config:
    # Конфигурация API
    API_URL = 'https://api.tbankrot.ru'
    TRADE_LIST_ENDPOINT = '/trade/getList'
    TRADE_GET_ENDPOINT = '/trade/get'

    # Лимиты запросов и повторы
    LIMIT = 40
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    AUTOSAVE_INTERVAL = 10

    # Файлы
    DEFAULT_OUTPUT_FILE = 'parsed_output.json'
    DEFAULT_CHECKPOINT_FILE = 'parsing_checkpoint.json'

    @property
    def auth_token(self) -> str:
        return os.getenv("TBANKROT_AUTH_TOKEN")

    @property
    def api_config(self) -> Dict[str, str]:
        return {
            "uid": os.getenv("TBANKROT_UID"),
            "hash": os.getenv("TBANKROT_HASH"),
            "device_id": os.getenv("TBANKROT_DEVICE_ID"),
        }

    @property
    def cookies(self) -> Dict[str, str]:
        return {"s360hash": os.getenv("TBANKROT_S360HASH")}

    @property
    def headers(self) -> Dict[str, str]:
        return {
            'auth-token': self.auth_token,
            'Content-Type': 'application/json',
            'Host': 'api.tbankrot.ru',
            'Connection': 'Keep-Alive',
            'User-Agent': 'okhttp/3.12.12',
        }
    # поменять запрос для второй части задачи
    @property
    def default_search_params(self) -> Dict[str, Any]:
        return {
            'text': None,
            'stop': None,
            'swp': None,
            'sort': None,
            'show_period': None,
            'num': None,
            'start_p1': None,
            'start_p2': None,
            'min_p1': None,
            'min_p2': None,
            'pp_1': None,
            'pp_2': None,
            'p1': None,
            'p2': None,
            'st_1': '17-09-24',
            'st_2': None,
            'et_1': None,
            'et_2': '17-09-25',
            'sz_1': None,
            'sz_2': None,
            'ez_1': None,
            'ez_2': None,
            'debtor': None,
            'au': None,
            'org': None,
            'keywords': None,
            'stopwords': None,
            'type_1': 'on',
            'type_2': None,
            'type_3': None,
            'type_4': None,
            'type_5': None,
            'region': None,
            'place': None,
            'sub_cat': [33],
            'show_checked': None,
            'photo': None,
            'show_closed': '1',
            'show_paused': None,
            'sort_order': 'asc',
            'mark': None,
        }

    # Конфигурация OpenRouter AI
    OPENROUTER_API_URL = 'https://openrouter.ai/api/v1/chat/completions'
    OPENROUTER_MODEL = 'google/gemini-2.5-flash-lite'
    
    @property
    def openrouter_token(self) -> str:
        """Токен для OpenRouter API."""
        return os.getenv("OPENROUTER_APIKEY")

    @property 
    def openrouter_headers(self) -> Dict[str, str]:
        """Заголовки для запросов к OpenRouter API."""
        return {
            "Authorization": f"Bearer {self.openrouter_token}",
            "Content-Type": "application/json"
        }

    # Конфигурация Федресурс
    FEDRESURS_TIMEOUT = 30

    @property
    def fedresurs_headers(self) -> Dict[str, str]:
        """Заголовки для запросов к Федресурс."""
        return {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
            'sec-ch-ua': '"Not.A/Brand";v="99", "Chromium";v="136"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Referer': 'https://tbankrot.ru/'
        }

config = Config()
