import sys
from fastapi import FastAPI, HTTPException, Query
from pydantic import HttpUrl
from contextlib import asynccontextmanager
import asyncio

from src.listorg.main import run as fetch_company_data
from loguru import logger
from src.browser import Browser  # Updated import
from src.ZChB.main import run_test as run_extended_extraction
from fastapi.responses import FileResponse
from src.apicloud import check_bankruptcy_status
from src.pdf_extractor import extract_text_from_url, close_global_pdf_session

# Configure Loguru
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("logs/api_runs.log", rotation="1 day", level="INFO")

# --- MODIFIED: Create a single, global browser instance ---
browser_manager = Browser(headless=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- On startup ---
    logger.info("FastAPI app starting up...")
    await browser_manager.launch()
    # Also initialize the PDF browser session if needed
    logger.info("PDF browser will be initialized on first use.")
    yield
    # --- On shutdown ---
    logger.info("FastAPI app shutting down...")
    await browser_manager.close()
    await close_global_pdf_session()
    logger.info("Global browser sessions closed.")

app = FastAPI(
    title="Company Data API",
    description="An API to fetch company card, financial, bankruptcy data, and extract text from PDFs.",
    version="1.4.0", # Version bump for the fix
    lifespan=lifespan
)

@app.get('/company_card/{inn}')
async def get_company_card(inn: str):
    """
    Retrieves general company information (card) for a given INN.
    This includes registration data and main activity.
    """
    logger.info(f"Received request for company_card with INN: {inn}")
    if not browser_manager.is_connected():
        raise HTTPException(status_code=503, detail="Browser service is not available.")
    try:
        # Use the shared browser instance
        data = await fetch_company_data(browser_manager.browser, inn, method='card')
        if data.get("error"):
            raise HTTPException(status_code=404, detail=data["error"])
        return {'success': True, 'data': data}
    except Exception as e:
        logger.error(f"Failed to process company_card for INN {inn}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

@app.get('/company_finances/{inn}')
async def get_company_finances(inn: str):
    """
    Retrieves financial data for a given INN.
    """
    logger.info(f"Received request for company_finances with INN: {inn}")
    if not browser_manager.is_connected():
        raise HTTPException(status_code=503, detail="Browser service is not available.")
    try:
        # Use the shared browser instance
        data = await fetch_company_data(browser_manager.browser, inn, method='finances')
        if data.get("error"):
            raise HTTPException(status_code=404, detail=data["error"])
        return {'success': True, 'data': data}
    except Exception as e:
        logger.error(f"Failed to process company_finances for INN {inn}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

@app.get('/company_extended/{inn}')
async def get_company_extended(inn: str):
    """
    Retrieves extended company data from zachestnyibiznes.ru for a given INN.
    """
    logger.info(f"Received request for company_extended with INN: {inn}")
    if not browser_manager.is_connected():
        raise HTTPException(status_code=503, detail="Browser service is not available.")
    try:
        # Use the shared browser instance
        data = await run_extended_extraction(browser_manager.browser, inn)
        if isinstance(data, dict) and data.get("error"):
            raise HTTPException(status_code=404, detail=data["error"])
        return {'success': True, 'data': data}
    except Exception as e:
        logger.error(f"Failed to process company_extended for INN {inn}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

@app.get('/bankrot/{inn}')
async def get_bankruptcy_status(inn: str):
    """
    Checks if an individual is listed in the bankruptcy register for a given INN.
    """
    logger.info(f"Received request for bankruptcy status with INN: {inn}")
    try:
        result = await check_bankruptcy_status(inn)
        if "error" in result:
            if "not found" in result["error"].lower():
                 raise HTTPException(status_code=404, detail=result["error"])
            else:
                 raise HTTPException(status_code=500, detail=result["error"])
        return {'success': True, 'data': result}
    except Exception as e:
        logger.error(f"Failed to process bankruptcy status for INN {inn}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

@app.get('/pdf_extract')
async def pdf_extract(url: HttpUrl = Query(..., description="The URL of the PDF file to extract text from.")):
    """
    Extracts text from a PDF file located at a given URL using a shared browser instance.
    """
    logger.info(f"Received request to extract text from PDF at URL: {url}")
    try:
        result = await extract_text_from_url(str(url))
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except Exception as e:
        logger.error(f"Failed to process PDF extraction for URL {url}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")


@app.get("/")
async def read_root():
    return {"message": "Welcome to the Company Data API. Visit /docs for documentation."}

@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/empty.ico")