import os
import httpx
from loguru import logger
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

API_URL = "https://api-cloud.ru/api/bankrot.php"
API_TOKEN = os.getenv("api_cloud")

async def check_bankruptcy_status(inn: str) -> dict:
    """
    Checks the bankruptcy status of an individual (физическое лицо) by their INN.
    
    Args:
        inn: The INN of the individual to check.

    Returns:
        A dictionary containing the bankruptcy status and data.
    """
    if not API_TOKEN:
        logger.error("API token for api-cloud.ru is not configured. Please set 'api_cloud' in your .env file.")
        return {"error": "API token is not configured."}

    params = {
        'type': 'searchString',
        'string': inn,
        'legalStatus': 'fiz',
        'token': API_TOKEN,
    }

    try:
        # The API documentation recommends a long timeout.
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(API_URL, params=params)
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
            
            data = response.json()

            if data.get("status") != 200:
                logger.warning(f"API returned non-200 status in JSON body for INN {inn}: {data.get('message')}")
                return {"error": data.get("message", "An unknown API error occurred.")}

            # "Информация не найдена" indicates the person is not listed as bankrupt.
            if data.get("message") == "Информация не найдена" or data.get("totalCount", 0) == 0:
                logger.info(f"INN {inn} not found in bankruptcy register. Considered not bankrupt.")
                return {"is_bankrupt": False, "message": "действующее ФЛ", "inn": inn}
            
            # If there are results, the person is considered bankrupt.
            if data.get("totalCount", 0) > 0 and "rez" in data:
                logger.info(f"INN {inn} found in bankruptcy register.")
                return {"is_bankrupt": True, "message": "банкрот", "data": data["rez"], "inn": inn}

            # Fallback for unexpected response structure
            logger.warning(f"Unexpected API response structure for INN {inn}: {data}")
            return {"error": "Unexpected API response structure."}

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error occurred while checking INN {inn}: {e.response.status_code} - {e.response.text}")
        return {"error": f"API request failed with status code {e.response.status_code}."}
    except httpx.RequestError as e:
        logger.error(f"Request error occurred while checking INN {inn}: {e}")
        return {"error": "Failed to connect to the bankruptcy API."}
    except Exception as e:
        logger.error(f"An unexpected error occurred in check_bankruptcy_status for INN {inn}: {e}")
        return {"error": "An internal error occurred."}