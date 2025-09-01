import sys
from fastapi import FastAPI, HTTPException
from src.listorg.main import run as fetch_company_data # Import the refactored function
from loguru import logger
from src.browser import Browser
# NEW: import the test/extended extractor
from src.ZChB.main import run_test as run_extended_extraction  # <-- added
from fastapi.responses import FileResponse

# Configure Loguru
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("logs/api_runs.log", rotation="1 day", level="INFO")

app = FastAPI(
    title="Company Data API",
    description="An API to fetch company card and financial data from list-org.com",
    version="1.0.0"
)

@app.get('/company_card/{inn}')
def get_company_card(inn: str):
    """
    Retrieves general company information (card) for a given INN.
    This includes registration data and main activity.
    """
    logger.info(f"Received request for company_card with INN: {inn}")
    try:
        with Browser(headless=True) as browser:
            data = fetch_company_data(browser, inn, method='card')
            if data.get("error"):
                raise HTTPException(status_code=404, detail=data["error"])
            return {'success': True, 'data': data}
    except Exception as e:
        logger.error(f"Failed to process company_card for INN {inn}: {e}")
        # Re-raise as HTTPException to send a proper error response
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

@app.get('/company_finances/{inn}')
def get_company_finances(inn: str):
    """
    Retrieves financial data for a given INN.
    """
    logger.info(f"Received request for company_finances with INN: {inn}")
    try:
        with Browser(headless=True) as browser:
            data = fetch_company_data(browser, inn, method='finances')
            if data.get("error"):
                raise HTTPException(status_code=404, detail=data["error"])
            return {'success': True, 'data': data}
    except Exception as e:
        logger.error(f"Failed to process company_finances for INN {inn}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

# NEW: extended data endpoint (CEOs, founders, beneficiaries, employees_by_year, defendant_in_progress)
@app.get('/company_extended/{inn}')
def get_company_extended(inn: str):
    """
    Retrieves extended company data (CEOs, founders, beneficiaries, employees_by_year, defendant_in_progress)
    from zachestnyibiznes.ru for a given INN.
    """
    logger.info(f"Received request for company_extended with INN: {inn}")
    try:
        with Browser(headless=True) as browser:
            data = run_extended_extraction(browser, inn)
            if isinstance(data, dict) and data.get("error"):
                raise HTTPException(status_code=404, detail=data["error"])
            return {'success': True, 'data': data}
    except Exception as e:
        logger.error(f"Failed to process company_extended for INN {inn}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

@app.get("/")
def read_root():
    return {"message": "Welcome to the Company Data API. Visit /docs for documentation."}

@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/empty.ico")