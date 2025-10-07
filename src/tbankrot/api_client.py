import requests
import logging
import time
from typing import Dict, Any, Optional
from .config import config

logger = logging.getLogger(__name__)

class APIClient:
    """Клиент для взаимодействия с API TBankrot."""

    def __init__(self):
        self.session = requests.Session()
        self.session.cookies.update(config.cookies)
        self.session.headers.update(config.headers)

    def make_request(self, url: str, json_data: Dict[str, Any], retries: int = 0) -> requests.Response:
        try:
            response = self.session.post(url, json=json_data, timeout=30)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if retries < config.MAX_RETRIES:
                logger.warning(f"Запрос не удался, повторяем ({retries + 1}/{config.MAX_RETRIES}): {e}")
                time.sleep(config.RETRY_DELAY * (retries + 1))
                return self.make_request(url, json_data, retries + 1)
            else:
                logger.error(f"Запрос не удался после {config.MAX_RETRIES} попыток: {e}")
                raise Exception(f"Запрос не удался: {e}")

    def fetch_trade_list(self, limit: int = None, offset: int = 0) -> Dict[str, Any]:
        """Получить список торгов из API."""
        if limit is None:
            limit = config.LIMIT

        json_data = {
            **config.api_config,
            'limit': limit,
            'offset': offset,
            'search': config.default_search_params
        }

        url = config.API_URL + config.TRADE_LIST_ENDPOINT
        logger.info(f"Получение данных из API с offset: {offset}, limit: {limit}")

        response = self.make_request(url, json_data)
        return response.json()

    def fetch_trade_details(self, trade_id: str) -> Dict[str, Any]:
        """Получить детальную информацию о конкретных торгах."""
        json_data = {
            **config.api_config,
            'id': trade_id
        }

        url = config.API_URL + config.TRADE_GET_ENDPOINT
        response = self.make_request(url, json_data)
        return response.json()

    def validate_auth(self, response_data: Dict[str, Any]) -> bool:
        """Проверить что API ответ указывает на успешную аутентификацию."""
        return response_data.get('userAuth') == True

    def close(self):
        """Закрыть сессию."""
        self.session.close()
