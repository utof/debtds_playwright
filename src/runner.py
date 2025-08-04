import logging
from pathlib import Path
from typing import Dict, Any

from .config import EXCEL_INPUT, JSON_OUTPUT, HEADLESS
from .utils import setup_logging, read_inns_from_excel, load_json, save_json_atomic
from .browser import playwright_session
from .flows import search_and_extract


def run(excel_path: Path = EXCEL_INPUT, json_out: Path = JSON_OUTPUT, headless: bool = HEADLESS) -> None:
    setup_logging()
    logging.info("step=runner_start excel=%s json=%s headless=%s", str(excel_path), str(json_out), headless)

    inns = read_inns_from_excel(excel_path)
    logging.info("step=load_excel outcome=ok count=%d", len(inns))

    db: Dict[str, Any] = load_json(json_out)
    logging.info("step=load_json outcome=ok existing=%d", len(db))

    with playwright_session(headless=headless) as (_, __, page):
        for idx, inn in enumerate(inns, start=1):
            if inn in db and db[inn]:
                logging.info("inn=%s step=skip_existing idx=%d", inn, idx)
                continue

            logging.info("inn=%s step=process_start idx=%d", inn, idx)
            res = search_and_extract(page, inn)

            # Choose stored value: overview text or a structured status string
            value = res.get("overview_text") or f"status:{res.get('status')} msg:{res.get('message')}"
            db[inn] = value

            save_json_atomic(json_out, db)
            logging.info("inn=%s step=process_done status=%s url=%s", inn, res.get("status"), res.get("url"))

    logging.info("step=runner_complete total_processed=%d", len(db))


if __name__ == "__main__":
    # Thin CLI entry; my_test_script.py will call run() as an entrypoint
    run()