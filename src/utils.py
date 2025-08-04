import json
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
import logging
import sys
from datetime import datetime

from .config import DATA_DIR, LOGS_DIR

# ---------- Logging ----------

def setup_logging(run_name: str | None = None) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if not run_name:
        run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"run_{run_name}.log"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("ts=%(asctime)s level=%(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)


# ---------- JSON IO ----------

def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        # backup corrupt file
        backup = path.with_suffix(path.suffix + ".bak")
        try:
            path.replace(backup)
        except Exception:
            pass
        return {}


def save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ---------- Excel ----------

def read_inns_from_excel(xlsx_path: Path, column: str = "ИНН") -> List[str]:
    df = pd.read_excel(xlsx_path)
    if column not in df.columns:
        raise KeyError(f'The Excel file must contain a column named "{column}"')
    inns = (
        df[column]
        .dropna()
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
        .tolist()
    )
    return [i for i in inns if i]