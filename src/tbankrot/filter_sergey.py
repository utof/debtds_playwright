# markers_core.py
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

# ───────────────────────────── Logging ─────────────────────────────
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.add(
    LOG_DIR / "markers.log",
    rotation="00:00",        # daily
    retention="14 days",     # adjust as needed
    compression="zip",       # save space
    enqueue=True,            # safe for multi-process
    backtrace=True,
    diagnose=False,
    level="INFO",
)

# ───────────────────────────── Helpers ─────────────────────────────
YearsDict = Dict[str | int, float | int | str | None]

PREF_YEARS_ORDER = [2025, 2024, 2023, 2022]  # prefer newer if present

# ───────────────────────── Export helpers ─────────────────────────


def process_batch_for_export(
    input_path: str | Path = "debug/lot_details_with_finances_analyzed.json",
    *,
    keep_only_autopass: bool = False,  # Step 1: drop items where autopass == False (any INN)
    drop_financials: bool = False,  # Step 4: drop finances_data[inn].financials
) -> list[dict]:
    """
    Load the JSON produced by analyze_lots_finances_batch (the _analyzed file by default),
    optionally filter items, and return a *list of cleaned data dicts* (no file is written).

    Steps (matching your spec):
      1) (optional via keep_only_autopass) remove items where NO INN autopasses
      2) flatten one level: each item becomes item["data"] (this step is *on*; see FLATTEN_TO_DATA)
      3) remove 'raw_api_response'
      4) (optional via drop_financials) remove 'financials' inside each INN's finances_data
      5) remove 'prev_lots_count'
    """
    path = Path(input_path)
    if not path.exists():
        logger.warning(
            f"[export] Input file {input_path} does not exist. Returning empty list."
        )
        return []

    with open(path, "r", encoding="utf-8") as f:
        batch = json.load(f)

    items = batch.get("items", [])
    processed: list[dict] = []

    # This is the always-on flatten step per your request.
    # If you want to disable it later, just set this to False or comment this line.
    FLATTEN_TO_DATA = True

    for it in items:
        obj = it
        if FLATTEN_TO_DATA:
            obj = it.get("data", {}) if isinstance(it, dict) else {}

        if not isinstance(obj, dict):
            continue

        # Step 1: keep only if ANY INN autopasses (when keep_only_autopass is True)
        if keep_only_autopass:
            markers_analysis = obj.get("markers_analysis", {})
            any_autopass = False

            if isinstance(markers_analysis, dict):
                # Check if this is the NEW structure: {inn: {markers, totals, autopass}}
                # vs OLD structure: {markers, totals, autopass}
                # NEW structure would have INN strings as keys, OLD has "markers", "totals", "autopass"
                has_markers_key = "markers" in markers_analysis

                if has_markers_key:
                    # OLD structure: {markers: {...}, totals: {...}, autopass: {...}}
                    autopass_info = markers_analysis.get("autopass", {})
                    if isinstance(autopass_info, dict) and autopass_info.get(
                        "pass", False
                    ):
                        any_autopass = True
                else:
                    # NEW structure: {inn: {markers, totals, autopass}, ...}
                    for inn, inn_markers in markers_analysis.items():
                        if isinstance(inn_markers, dict):
                            autopass_info = inn_markers.get("autopass", {})
                            if isinstance(autopass_info, dict) and autopass_info.get(
                                "pass", False
                            ):
                                any_autopass = True
                                break

            if not any_autopass:
                continue

        # Work on a shallow copy to avoid mutating original data attached to batch
        row = dict(obj)

        # Step 3: remove raw_api_response
        row.pop("raw_api_response", None)

        # Step 4: optionally drop financials from finances_data
        if drop_financials:
            fd = row.get("finances_data")
            if isinstance(fd, dict):
                fd = dict(fd)
                # Check if OLD structure (has "financials" key) or NEW (INN keys)
                has_financials_key = "financials" in fd

                if has_financials_key:
                    # OLD structure: remove financials directly
                    fd.pop("financials", None)
                else:
                    # NEW structure: remove financials from each INN
                    for inn, inn_data in fd.items():
                        if isinstance(inn_data, dict):
                            inn_data = dict(inn_data)
                            inn_data.pop("financials", None)
                            fd[inn] = inn_data
                row["finances_data"] = fd

        # Step 5: remove prev_lots_count
        row.pop("prev_lots_count", None)

        processed.append(row)

    logger.info(f"[export] Prepared {len(processed)}/{len(items)} items for export")
    return processed


def save_items_to_xlsx(
    items: list[dict],
    output_path: str | Path = "debug/name.xlsx",
) -> str:
    """
    Save items (from process_batch_for_export) into an .xlsx:
      • Each item = 1 row, each key/value = a column.
      • If a value is a list → join elements with '\\n'
      • Remove 'coefficients' from finances_data (do not export them)
      • 'financials' is collapsed into a single text column:
         'ФХ.ХХХХ NAME\\n  2022: VAL\\n  2023: VAL\\n ...' (years shown earliest→latest)
      • 'markers' column (from markers_analysis):
         'marker: value\\n\\n totals: key: val' (all totals listed)
    """
    try:
        import pandas as pd  # local import to avoid hard dependency at module import time
    except Exception as e:
        logger.error(f"[export] pandas is required to export xlsx: {e}")
        raise

    def _to_str(v) -> str:
        """Generic stringify with special handling for lists (newline-join) and dicts (compact JSON)."""
        if isinstance(v, list):

            def _elem_to_str(x):
                if isinstance(x, (dict, list)):
                    return json.dumps(x, ensure_ascii=False)
                return "" if x is None else str(x)

            return "\n".join(_elem_to_str(x) for x in v)
        if isinstance(v, dict):
            return json.dumps(v, ensure_ascii=False)
        return "" if v is None else str(v)

    def _render_financials(financials_block: dict) -> str:
        """
        Render finances_data['financials'] into the specified multiline format.
        Expects shape like {"Ф1.1150": {"name": "...", "values": {"2024":"...", "2023":"..."}}}
        """
        if not isinstance(financials_block, dict):
            return ""

        # Sort by numeric code inside "Ф?.XXXX" if possible; else by key.
        def _code_num(k: str) -> tuple[int, str]:
            # extract last 4+ digits from the key to sort: e.g. "Ф1.1200" -> 1200
            digits = "".join(ch for ch in k if ch.isdigit())
            # digits may include the "1" before dot: prefer the tail 4 if present
            if len(digits) >= 4:
                try:
                    return int(digits[-4:]), k
                except Exception:
                    pass
            try:
                return int(digits), k
            except Exception:
                return (10**9, k)

        parts: list[str] = []
        for fkey in sorted(financials_block.keys(), key=_code_num):
            block = financials_block.get(fkey) or {}
            name = (block.get("name") or "").strip()
            vals = block.get("values") or {}
            # years earliest→latest
            try:
                years_sorted = sorted(int(y) for y in vals.keys())
            except Exception:
                # fallback to original order if keys are non-int
                years_sorted = list(vals.keys())
            header = f"{fkey} {name}".strip()
            parts.append(header)
            for y in years_sorted:
                y_str = str(y)
                v_raw = vals.get(y_str, "")
                v_norm = (
                    v_raw
                    if isinstance(v_raw, str)
                    else ("" if v_raw is None else str(v_raw))
                )
                parts.append(f"  {y_str}: {v_norm}")
        return "\n".join(parts)

    def _render_markers_single_inn(markers_analysis: dict) -> str:
        """Render markers for a single INN."""
        if not isinstance(markers_analysis, dict):
            return ""
        markers = markers_analysis.get("markers") or {}
        totals = markers_analysis.get("totals") or {}
        autopass = markers_analysis.get("autopass") or {}
        error = markers_analysis.get("error")

        out: list[str] = []

        # Show error if present
        if error:
            out.append(f"ERROR: {error}")
            return "\n".join(out)

        # sort markers by numeric key if possible
        def _mk_key(k):
            try:
                return int(k)
            except Exception:
                return k

        for k in sorted(markers.keys(), key=_mk_key):
            out.append(f"{k}: {markers.get(k)}")
        out.append("")  # blank line
        out.append("totals:")
        for k, v in totals.items():
            out.append(f"  {k}: {v}")
        out.append("")
        out.append(f"autopass: {autopass.get('pass', False)}")
        if autopass.get("reason"):
            out.append(f"  reason: {autopass.get('reason')}")
        return "\n".join(out).strip()

    def _render_markers(markers_analysis: dict) -> str:
        """
        Render markers_analysis. Handles both:
        - NEW structure: {inn: {markers, totals, autopass}, ...}
        - OLD structure: {markers, totals, autopass}
        """
        if not isinstance(markers_analysis, dict):
            return ""

        # Check if this is OLD structure (has "markers" key) or NEW (INN keys)
        has_markers_key = "markers" in markers_analysis

        if has_markers_key:
            # OLD structure: render directly
            return _render_markers_single_inn(markers_analysis)
        else:
            # NEW structure: render each INN
            inn_parts: list[str] = []
            for inn in sorted(markers_analysis.keys()):
                inn_markers = markers_analysis[inn]
                if not isinstance(inn_markers, dict):
                    continue
                inn_parts.append(f"INN: {inn}")
                inn_parts.append(_render_markers_single_inn(inn_markers))
                inn_parts.append("")  # blank line between INNs

            return "\n".join(inn_parts).strip()

    # Build rows
    flat_rows: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row: dict[str, str] = {}
        # We will replace 'finances_data' and 'markers_analysis' with special columns,
        # and pass through everything else (lists -> newline-joined; dicts -> JSON).
        finances_data = item.get("finances_data")
        markers_analysis = item.get("markers_analysis")

        for k, v in item.items():
            if k in ("finances_data", "markers_analysis"):
                continue  # handled below
            row[k] = _to_str(v)

        # finances_data can be:
        # - NEW: {inn: {financials: {...}, ...}, ...}
        # - OLD: {financials: {...}, ...}
        if isinstance(finances_data, dict):
            # Check if this is OLD structure (has "financials" key) or NEW (INN keys)
            has_financials_key = "financials" in finances_data

            if has_financials_key:
                # OLD structure: direct financials
                financials = finances_data.get("financials")
                row["financials"] = (
                    _render_financials(financials)
                    if isinstance(financials, dict)
                    else ""
                )
            else:
                # NEW structure: render each INN's financials
                inn_financials_parts: list[str] = []
                for inn in sorted(finances_data.keys()):
                    inn_data = finances_data[inn]
                    if not isinstance(inn_data, dict):
                        continue
                    financials = inn_data.get("financials")
                    if financials:
                        inn_financials_parts.append(f"INN: {inn}")
                        inn_financials_parts.append(_render_financials(financials))
                        inn_financials_parts.append("")  # blank line between INNs
                row["financials"] = "\n".join(inn_financials_parts).strip()

        # markers_analysis is now {inn: {markers, totals, autopass}}
        if isinstance(markers_analysis, dict):
            row["markers"] = _render_markers(markers_analysis)

        flat_rows.append(row)

    df = pd.DataFrame(flat_rows)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Write
    try:
        df.to_excel(out_path, index=False)
    except Exception as e:
        logger.error(f"[export] Failed to write {out_path}: {e}")
        raise

    logger.info(f"[export] Wrote {len(df)} rows to {out_path}")
    return str(out_path)


def _coerce_number(v) -> Optional[float]:
    """
    Try to coerce a value to float. Return None if impossible.
    Empty string, None -> None.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(" ", "").replace(",", ".")
        if s == "":
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _valid_num(v: Optional[float]) -> bool:
    return v is not None


def safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """
    Division that returns None if denominator is invalid (None or == 0) or if
    numerator is None. (Per your rule: any invalid denominator -> 0 points upstream.)
    """
    if num is None or den is None:
        return None
    if den == 0:
        return None
    try:
        return num / den
    except Exception:
        return None


def _normalize_years_dict(d: YearsDict) -> Dict[int, Optional[float]]:
    """
    Convert keys to ints (years) and values to floats (or None).
    Unknown keys are ignored.
    """
    out: Dict[int, Optional[float]] = {}
    for k, v in d.items():
        try:
            year = int(k)
        except Exception:
            continue
        out[year] = _coerce_number(v)
    return out


def _pick_latest_year_with_all(fields: List[YearsDict]) -> Optional[Tuple[int, List[float]]]:
    """
    For single-year checks: pick the **latest** year where all given fields
    have valid numbers and (implicitly) usable (no denominator concerns here).
    Returns (year, [values per field]) or None.
    """
    norm_fields: List[Dict[int, Optional[float]]] = [_normalize_years_dict(f) for f in fields]

    for yr in PREF_YEARS_ORDER:
        vals: List[Optional[float]] = [nf.get(yr) for nf in norm_fields]
        if all(_valid_num(v) for v in vals):
            return yr, [float(v) for v in vals]  # type: ignore
    return None


def _pick_latest_consecutive_pair(fields: List[YearsDict]) -> Optional[Tuple[int, int, List[float], List[float]]]:
    """
    For two-year comparisons: try (2023, 2024) first, then (2022, 2023).
    Return (prev_year, curr_year, prev_vals[], curr_vals[]) or None.
    """
    norm_fields: List[Dict[int, Optional[float]]] = [_normalize_years_dict(f) for f in fields]
    candidate_pairs = [(2023, 2024), (2022, 2023)]

    for prev_y, curr_y in candidate_pairs:
        prev_vals = [nf.get(prev_y) for nf in norm_fields]
        curr_vals = [nf.get(curr_y) for nf in norm_fields]
        if all(_valid_num(v) for v in prev_vals) and all(_valid_num(v) for v in curr_vals):
            return prev_y, curr_y, [float(v) for v in prev_vals], [float(v) for v in curr_vals]  # type: ignore
    return None


def pct_change(prev: float, curr: float) -> Optional[float]:
    """
    Percentage change from prev to curr, i.e., (curr - prev)/abs(prev).
    Return None if prev == 0 to avoid division issues.
    """
    if prev == 0:
        return None
    try:
        return (curr - prev) / abs(prev)
    except Exception:
        return None


def analyze_lots_finances_batch(
    input_path: str = "debug/lot_details_with_finances.json", output_path: str = None
) -> None:
    """
    Load the batch JSON, analyze finances_data for each lot using markers,
    add results under "markers_analysis" key, and save to a new output file.

    Args:
        input_path: Path to input JSON file
        output_path: Path to output JSON file (defaults to input_path with '_analyzed' suffix)
    """
    path = Path(input_path)
    if not path.exists():
        logger.warning(f"Input file {input_path} does not exist. Skipping.")
        return

    # Determine output path
    if output_path is None:
        output_path = path.with_stem(path.stem + "_analyzed")
    output = Path(output_path)

    # Load JSON
    with open(path, "r", encoding="utf-8") as f:
        batch_data = json.load(f)

    items = batch_data.get("items", [])
    updated_count = 0

    for item in items:
        data = item.get("data", {})
        finances_data = data.get("finances_data", {})

        # Check if already analyzed
        if "markers_analysis" in data:
            logger.info(f"Skipping already analyzed item: {item.get('url', 'unknown')}")
            continue

        url = item.get("url", "unknown")

        # Skip conditions (same as in fetch_finances_batch.py)
        if (
            data.get("individuals") == "физлицо"
            or data.get("empty_individuals_but_no_inn_orgn")
            or data.get("empty_inn_but_nonempty_orgn")
        ):
            data["markers_analysis"] = {}
            logger.info(f"Skipping {url}: matches skip conditions")
            updated_count += 1
            continue

        # NEW: finances_data is now a dict of {inn: {financials: {...}, error: ...}}
        if not isinstance(finances_data, dict) or len(finances_data) == 0:
            data["markers_analysis"] = {}
            logger.info(f"Skipping {url}: empty finances_data")
            updated_count += 1
            continue

        # Process each INN in finances_data
        markers_analysis = {}

        for inn, inn_data in finances_data.items():
            if not isinstance(inn_data, dict):
                # Create empty structure for consistency
                markers_analysis[inn] = {
                    "error": "Invalid inn_data format",
                    "markers": {},
                    "totals": {"sum": 0, "strong": 0, "medium": 0, "weak": 0},
                    "autopass": {"pass": False, "reason": None},
                }
                continue

            # Check for error in this INN's data
            if "error" in inn_data:
                markers_analysis[inn] = {
                    "error": f"Financials fetch error: {inn_data['error']}",
                    "markers": {},
                    "totals": {"sum": 0, "strong": 0, "medium": 0, "weak": 0},
                    "autopass": {"pass": False, "reason": None},
                }
                logger.info(f"[{url}] INN {inn}: has error - {inn_data['error']}")
                continue

            # Extract financials for this INN
            raw_financials = inn_data.get("financials", {})
            if not isinstance(raw_financials, dict) or len(raw_financials) == 0:
                markers_analysis[inn] = {
                    "error": "No financials data",
                    "markers": {},
                    "totals": {"sum": 0, "strong": 0, "medium": 0, "weak": 0},
                    "autopass": {"pass": False, "reason": None},
                }
                logger.info(f"[{url}] INN {inn}: empty financials")
                continue

            # DIAGNOSTIC LOGS
            logger.info(f"[DIAG] Processing lot: URL={url}, INN={inn}")
            if raw_financials:
                sample_keys = list(raw_financials.keys())[:3]
                sample_vals = {
                    k: list(raw_financials[k].get("values", {}).items())[:2]
                    for k in sample_keys
                }
                logger.info(
                    f"[DIAG] Raw financials sample for {inn}: keys={sample_keys}, sample_values={sample_vals}"
                )

            # Run markers for this INN
            try:
                analysis = calculate_all_markers_from_json(raw_financials)
                # DIAGNOSTIC: Log normalized sample and total score
                normalized = normalize_rsbu_json(raw_financials)
                sample_norm = {
                    k: dict(list(v.items())[:2])
                    for k, v in list(normalized.items())[:3]
                }
                logger.info(
                    f"[DIAG] Normalized sample for {inn}: {sample_norm}, total_points={analysis['totals']['sum']}"
                )
                markers_analysis[inn] = analysis
                logger.info(
                    f"Analyzed {url} INN {inn}: total points {analysis['totals']['sum']}"
                )
            except Exception as e:
                logger.error(f"Error analyzing {url} INN {inn}: {e}")
                markers_analysis[inn] = {
                    "error": str(e),
                    "markers": {},
                    "totals": {"sum": 0, "strong": 0, "medium": 0, "weak": 0},
                    "autopass": {"pass": False, "reason": None},
                }

        # Store markers_analysis as dict of INNs
        data["markers_analysis"] = markers_analysis
        updated_count += 1

    # Save to output file
    with open(output, "w", encoding="utf-8") as f:
        json.dump(batch_data, f, ensure_ascii=False, indent=2)

    logger.info(
        f"Batch analysis complete. Updated {updated_count}/{len(items)} items. Output saved to {output_path}"
    )


# ───────────────────────── Normalizer ─────────────────────────


_KEY_RE = re.compile(r"[ФF]\s*\d+[.\s](\d+)", re.IGNORECASE)


def normalize_rsbu_json(raw_data: dict) -> dict[str, dict[int, float | None]]:
    """
    Converts:
      {"Ф1.1200": {"name": "...", "values": {"2021": "35545", "2022": ""}}, ...}
    → into:
      {"f1200": {2021: 35545.0, 2022: None}, ...}

    NOTE: We intentionally drop the form prefix (1/2). "Ф1.1150" -> f1150; "Ф2.2110" -> f2110.
    """
    out: dict[str, dict[int, float | None]] = {}

    for key, block in raw_data.items():
        if not isinstance(key, str):
            continue

        m = _KEY_RE.search(key)
        if not m:
            # If someone already passed "f1200" etc., accept as-is
            if key.startswith("f") and key[1:].isdigit():
                cleaned_key = key
            else:
                continue
        else:
            cleaned_key = f"f{m.group(1)}"

        values = (block or {}).get("values", {})
        out_vals: dict[int, float | None] = {}
        for y_str, val in values.items():
            try:
                year = int(y_str)
            except Exception:
                continue
            out_vals[year] = _coerce_number(val)

        out[cleaned_key] = out_vals

    return out


# ───────────────────────────── Markers ─────────────────────────────
# NOTE: All marker functions return **int points only**, per your requirement.
# If required inputs are missing/invalid (esp. denominators), they return 0.


def marker_1_negative_equity(f1300: YearsDict) -> int:
    """
    Маркер 1. Отрицательный собственный капитал (строка 1300)
    - 2 балла, если текущий год < 0
    - 3 балла, если второй год подряд < 0 (т.е. и текущий, и предыдущий < 0)
    Pair selection rule:
      - Prefer (2023, 2024) if both valid, else fall back to (2022, 2023).
      - If only a single recent year is available and < 0 -> 2 points.
    """
    nf = _normalize_years_dict(f1300)

    pair = _pick_latest_consecutive_pair([f1300])
    if pair:
        prev_y, curr_y, [prev_val], [curr_val] = pair
        logger.info(
            f"[M1] Using pair {prev_y}->{curr_y}: prev={prev_val}, curr={curr_val}"
        )
        if curr_val < 0 and prev_val < 0:
            return 3
        if curr_val < 0:
            return 2
        return 0

    # Fallback: pick any single latest year with a value
    single = _pick_latest_year_with_all([f1300])
    if single:
        yr, [v] = single
        logger.info(f"[M1] Using single year {yr}: v={v}")
        if v < 0:
            return 2
        return 0

    logger.info("[M1] No valid data -> 0 points")
    return 0


def marker_2_low_current_liquidity(f1200: YearsDict, f1500: YearsDict) -> int:
    """
    Маркер 2. Низкая текущая ликвидность
    - Расчёт: 1200 / 1500 (оборотные / краткосрочные)
    - Триггер: ratio < 1.0  → 2 балла
      (ниже 0.7 — критично; 0.7–1.0 — повышенный риск; таблица баллов даёт единый вес 2)
    - Если denominator (1500) отсутствует/некорректен/0 → 0 баллов
    - Берём **последний доступный** год с валидными 1200 и 1500
    """
    sel = _pick_latest_year_with_all([f1200, f1500])
    if not sel:
        logger.info("[M2] No valid single year with 1200 & 1500 -> 0 points")
        return 0

    yr, [a1200, a1500] = sel
    ratio = safe_div(a1200, a1500)
    logger.info(f"[M2] Year {yr}: 1200={a1200}, 1500={a1500}, ratio={ratio}")

    if ratio is None:
        return 0
    if ratio < 1.0:
        return 2
    return 0


def marker_3_low_quick_liquidity(
    f1200: YearsDict, f1210: YearsDict, f1500: YearsDict
) -> int:
    """
    Маркер 3. Низкая быстрая ликвидность
    - Расчёт: (1200 - 1210) / 1500
    - Триггер: < 0.6 → 2 балла
    - Если denominator (1500) отсутствует/некорректен/0 → 0 баллов
    - Берём **последний доступный** год, где все три значения валидны
    """
    sel = _pick_latest_year_with_all([f1200, f1210, f1500])
    if not sel:
        logger.info("[M3] No valid single year with 1200, 1210, 1500 -> 0 points")
        return 0

    yr, [a1200, a1210, a1500] = sel
    quick_assets = a1200 - a1210
    ratio = safe_div(quick_assets, a1500)
    logger.info(
        f"[M3] Year {yr}: (1200-1210)={quick_assets}, 1500={a1500}, ratio={ratio}"
    )

    if ratio is None:
        return 0
    if ratio < 0.6:
        return 2
    return 0


def marker_4_low_absolute_liquidity(f1250: YearsDict, f1500: YearsDict) -> int:
    """
    Маркер 4. Низкая абсолютная ликвидность
    - Расчёт: 1250 / 1500
    - Триггер: < 0.1 → 2 балла
    - Берём последний год с валидными 1250 и 1500. Если denominator невалиден → 0.
    """
    sel = _pick_latest_year_with_all([f1250, f1500])
    if not sel:
        logger.info("[M4] No valid single year with 1250 & 1500 -> 0 points")
        return 0

    yr, [a1250, a1500] = sel
    ratio = safe_div(a1250, a1500)
    logger.info(f"[M4] Year {yr}: 1250={a1250}, 1500={a1500}, ratio={ratio}")

    if ratio is None:
        return 0
    return 2 if ratio < 0.1 else 0


def marker_5_ppe_drop_25(f1150: YearsDict) -> int:
    """
    Маркер 5. Существенное сокращение основных средств
    - Сравнение 1150 за год (пара лет): снижение на 25% и более → 2 балла
    - Пара: сначала (2023→2024), затем (2022→2023). Нет пары → 0.
    """
    pair = _pick_latest_consecutive_pair([f1150])
    if not pair:
        logger.info("[M5] No valid pair for 1150 -> 0 points")
        return 0

    prev_y, curr_y, [prev_v], [curr_v] = pair
    ch = pct_change(prev_v, curr_v)  # (curr - prev)/abs(prev)
    logger.info(
        f"[M5] {prev_y}->{curr_y}: 1150 prev={prev_v}, curr={curr_v}, pct_change={ch}"
    )

    if ch is None:
        return 0
    return 2 if ch <= -0.25 else 0


def marker_6_lt_investments_shift(f1170: YearsDict, f1600: YearsDict) -> int:
    """
    Маркер 6. Перевод активов в долгосрочные финансовые вложения
    - Критерий (реализуем строго определённый из ТЗ):
        Доля 1170/1600 стала ≥ 20% И выросла минимум на 10 п.п. за год → 2 балла
    - Пара лет: (2023→2024), иначе (2022→2023). Нет пары/деноминатора → 0.
    - Примечание: ветку «рост заметный по сумме» опускаем из-за отсутствия точного порога.
    """
    pair = _pick_latest_consecutive_pair([f1170, f1600])
    if not pair:
        logger.info("[M6] No valid pair for 1170 & 1600 -> 0 points")
        return 0

    prev_y, curr_y, [p1170, p1600], [c1170, c1600] = pair
    share_prev = safe_div(p1170, p1600)
    share_curr = safe_div(c1170, c1600)
    logger.info(
        f"[M6] {prev_y}->{curr_y}: share_prev={share_prev}, share_curr={share_curr}"
    )

    if share_prev is None or share_curr is None:
        return 0

    grew_pp = share_curr - share_prev
    if share_curr >= 0.20 and grew_pp >= 0.10:
        return 2
    return 0


def marker_7_frozen_receivables(f1230: YearsDict, f2110: YearsDict) -> int:
    """
    Маркер 7. «Застывшая» дебиторская задолженность
    - Базовый триггер: (1230/2110) > 1 и показатель растёт второй год подряд.
      Практика расчёта:
        * Если доступны три последовательных года (2022, 2023, 2024), проверяем:
          r22 < r23 < r24 и r24 > 1 → 2 балла.
        * Если доступны только два года (последняя пара), допускаем упрощение:
          r_prev < r_curr и r_curr > 1 → 2 балла.
    - Доп. показатель (в логах): DSO = 365 * 1230 / 2110; >240 и растёт — усиливает вывод (баллы не увеличиваем).
    """
    # Try full 3-year trend first
    nf1230 = _normalize_years_dict(f1230)
    nf2110 = _normalize_years_dict(f2110)

    years = [2022, 2023, 2024]
    r = {}
    for y in years:
        r[y] = (
            safe_div(nf1230.get(y), nf2110.get(y))
            if (y in nf1230 and y in nf2110)
            else None
        )

    if all(rv is not None for rv in (r[2022], r[2023], r[2024])):
        r22, r23, r24 = r[2022], r[2023], r[2024]
        logger.info(f"[M7] 3y ratios: r22={r22}, r23={r23}, r24={r24}")
        if r22 < r23 < r24 and r24 > 1:
            # Log DSO trend for info
            dso22 = 365 * r22 if r22 is not None else None
            dso23 = 365 * r23 if r23 is not None else None
            dso24 = 365 * r24 if r24 is not None else None
            logger.info(f"[M7] DSO 3y: {dso22} -> {dso23} -> {dso24}")
            return 2

    # Fallback to the latest pair (2023->2024, else 2022->2023)
    pair = _pick_latest_consecutive_pair([f1230, f2110])
    if not pair:
        logger.info("[M7] No valid pair for 1230 & 2110 -> 0 points")
        return 0

    prev_y, curr_y, [p1230, p2110], [c1230, c2110] = pair
    r_prev = safe_div(p1230, p2110)
    r_curr = safe_div(c1230, c2110)
    logger.info(f"[M7] {prev_y}->{curr_y}: r_prev={r_prev}, r_curr={r_curr}")

    if r_prev is None or r_curr is None:
        return 0
    if r_curr > 1 and r_curr > r_prev:
        # Log 2-pt DSO info
        dso_prev = 365 * r_prev
        dso_curr = 365 * r_curr
        logger.info(f"[M7] DSO {prev_y}->{curr_y}: {dso_prev} -> {dso_curr}")
        return 2
    return 0


def marker_8_ap_up_rev_down(f1520: YearsDict, f2110: YearsDict) -> int:
    """
    Маркер 8. Резкий рост кредиторской задолженности при падении выручки
    - Условия на одной и той же паре лет:
        * 1520 выросла ≥ 50% (pct_change ≥ +0.5)
        * 2110 упала ≥ 30% (pct_change ≤ -0.3)
    - Пара: (2023→2024), иначе (2022→2023).
    """
    pair = _pick_latest_consecutive_pair([f1520, f2110])
    if not pair:
        logger.info("[M8] No valid pair for 1520 & 2110 -> 0 points")
        return 0

    prev_y, curr_y, [p1520, p2110], [c1520, c2110] = pair
    ch_ap = pct_change(p1520, c1520)
    ch_rev = pct_change(p2110, c2110)
    logger.info(f"[M8] {prev_y}->{curr_y}: 1520 Δ={ch_ap}, 2110 Δ={ch_rev}")

    if ch_ap is None or ch_rev is None:
        return 0
    if ch_ap >= 0.5 and ch_rev <= -0.3:
        return 2
    return 0


def marker_9_cash_vs_ap(f1250: YearsDict, f1520: YearsDict) -> int:
    """
    Маркер 9. Денег крайне мало относительно кредиторской задолженности
    - Расчёт: 1250 / 1520 < 0.1 → 2 балла
    - Берём последний год с валидными 1250 и 1520.
    """
    sel = _pick_latest_year_with_all([f1250, f1520])
    if not sel:
        logger.info("[M9] No valid single year with 1250 & 1520 -> 0 points")
        return 0

    yr, [a1250, a1520] = sel
    ratio = safe_div(a1250, a1520)
    logger.info(f"[M9] Year {yr}: 1250={a1250}, 1520={a1520}, ratio={ratio}")

    if ratio is None:
        return 0
    return 2 if ratio < 0.1 else 0


def marker_10_debt_load_and_interest_cover(
    f1410: YearsDict,
    f1510: YearsDict,
    f2110: YearsDict,
    f2200: YearsDict,
    f2330: YearsDict,
) -> int:
    """
    Маркер 10. Чрезмерная долговая нагрузка и слабое покрытие процентов
    - Критерий A (долговая нагрузка): (1410 + 1510) / 2110 > 2  → 2 балла
    - Критерий B (покрытие процентов): 2200 / 2330 < 1, при этом 2330 > 0 → 2 балла
    - Берём по каждому критерию последний год, где все необходимые поля валидны.
      Если выполняется хотя бы один критерий → 2 балла, иначе 0.
    """
    # Criterion A: leverage vs revenue
    selA = _pick_latest_year_with_all([f1410, f1510, f2110])
    if selA:
        yrA, [a1410, a1510, a2110] = selA
        leverage = safe_div(a1410 + a1510, a2110)
        logger.info(
            f"[M10.A] Year {yrA}: (1410+1510)={a1410 + a1510}, 2110={a2110}, leverage={leverage}"
        )
        if leverage is not None and leverage > 2:
            return 2

    # Criterion B: operating profit vs interest expense
    selB = _pick_latest_year_with_all([f2200, f2330])
    if selB:
        yrB, [a2200, a2330] = selB
        # 2330 must be positive for a meaningful denominator per rule
        ratio = safe_div(a2200, a2330) if a2330 and a2330 > 0 else None
        logger.info(f"[M10.B] Year {yrB}: 2200={a2200}, 2330={a2330}, cover={ratio}")
        if ratio is not None and ratio < 1:
            return 2

    logger.info("[M10] No criteria met -> 0 points")
    return 0


def marker_11_inventories_up_revenue_down(f1210: YearsDict, f2110: YearsDict) -> int:
    """
    Маркер 11. Запасы растут, а выручка падает
    - Условия на одной и той же паре лет:
        * 1210 выросли ≥ 30%  (pct_change ≥ +0.30)
        * 2110 упала  ≥ 20%   (pct_change ≤ -0.20)
      Доп.: share = 1210/2110 > 0.5 усиливает вывод (баллы остаются 2).
    - Пара: (2023→2024), иначе (2022→2023).
    """
    pair = _pick_latest_consecutive_pair([f1210, f2110])
    if not pair:
        logger.info("[M11] No valid pair for 1210 & 2110 -> 0 points")
        return 0

    prev_y, curr_y, [p1210, p2110], [c1210, c2110] = pair
    ch_inv = pct_change(p1210, c1210)
    ch_rev = pct_change(p2110, c2110)
    share_curr = safe_div(c1210, c2110)
    logger.info(
        f"[M11] {prev_y}->{curr_y}: Δ1210={ch_inv}, Δ2110={ch_rev}, share_curr={share_curr}"
    )

    if ch_inv is None or ch_rev is None:
        return 0
    if ch_inv >= 0.30 and ch_rev <= -0.20:
        # note: share_curr > 0.5 only logged (doesn't change points per spec)
        return 2
    return 0


def marker_12_large_asset_shifts(
    f1150: YearsDict, f1170: YearsDict, f1240: YearsDict, f1600: YearsDict
) -> int:
    """
    Маркер 12. Крупные сдвиги в структуре активов
    - Сработал, если изменение любого из {1150, 1170, 1240} за год
      по модулю ≥ 25% от прошлогодней 1600 (валюта баланса).
    - Пара: (2023→2024), иначе (2022→2023).
    - Баллы: 2. (Вариант 3 балла с резким падением налога на имущество
      невозможно оценить здесь — налог не передаётся в аргументах.)
    """
    pair = _pick_latest_consecutive_pair([f1150, f1170, f1240, f1600])
    if not pair:
        logger.info("[M12] No valid pair for 1150/1170/1240 & 1600 -> 0 points")
        return 0

    prev_y, curr_y, [p1150, p1170, p1240, p1600], [c1150, c1170, c1240, c1600] = pair
    if p1600 is None or p1600 == 0:
        logger.info("[M12] prev 1600 invalid -> 0 points")
        return 0

    threshold = 0.25 * abs(p1600)
    diff_1150 = abs(c1150 - p1150)
    diff_1170 = abs(c1170 - p1170)
    diff_1240 = abs(c1240 - p1240)

    logger.info(
        f"[M12] {prev_y}->{curr_y}: |Δ1150|={diff_1150}, |Δ1170|={diff_1170}, |Δ1240|={diff_1240}, thr={threshold}"
    )

    if diff_1150 >= threshold or diff_1170 >= threshold or diff_1240 >= threshold:
        return 2
    return 0


def marker_13_reporting_problems(
    f1600: YearsDict,
    f1700: YearsDict,
    f2110: YearsDict,
    f1200: YearsDict,
    f1500: YearsDict,
) -> int:
    """
    3 points if:
      (1) No reporting in the latest year (none of the *available* key lines exist there), or
      (2) 1600 != 1700 in the latest year where both exist, or
      (3) Two consecutive years miss at least one *required* key line.
          Here 2110 (revenue) is required only if revenue is present in the dataset at least once.
    """
    nf1600 = _normalize_years_dict(f1600)
    nf1700 = _normalize_years_dict(f1700)
    nf2110 = _normalize_years_dict(f2110)
    nf1200 = _normalize_years_dict(f1200)
    nf1500 = _normalize_years_dict(f1500)

    has_any_revenue = any(v is not None for v in nf2110.values())

    def line_has_any(d: dict[int, Optional[float]]) -> bool:
        return any(v is not None for v in d.values())

    # (1) No reporting in the latest year that we expect *something* for
    for yr in PREF_YEARS_ORDER:
        # Only include lines that exist somewhere in the history
        candidates = []
        if line_has_any(nf1600):
            candidates.append(nf1600.get(yr))
        if line_has_any(nf1700):
            candidates.append(nf1700.get(yr))
        if has_any_revenue and line_has_any(nf2110):
            candidates.append(nf2110.get(yr))
        if line_has_any(nf1200):
            candidates.append(nf1200.get(yr))
        if line_has_any(nf1500):
            candidates.append(nf1500.get(yr))

        if candidates:  # we expect something in this year
            if all(v is None for v in candidates):
                logger.info(
                    f"[M13] Missing all available key lines in latest year {yr} -> 3 points"
                )
                return 3
            break  # stop at the latest year we consider

    # (2) 1600 != 1700 in the latest year where both exist
    for yr in PREF_YEARS_ORDER:
        a = nf1600.get(yr)
        b = nf1700.get(yr)
        if a is not None and b is not None:
            if a != b:
                logger.info(f"[M13] 1600 != 1700 in {yr}: {a} != {b} -> 3 points")
                return 3
            break

    # (3) Two consecutive years with at least one required key missing.
    # Required = {1200, 1500} (+2110 if we actually have revenue in this dataset).
    def year_has_missing_keys(y: int) -> bool:
        required = [nf1200.get(y), nf1500.get(y)]
        if has_any_revenue:
            required.append(nf2110.get(y))
        # if nothing is required (shouldn't happen), say not missing
        if not required:
            return False
        return any(v is None for v in required)

    if year_has_missing_keys(2023) and year_has_missing_keys(2024):
        logger.info(
            "[M13] Missing required key lines in both 2023 and 2024 -> 3 points"
        )
        return 3
    if year_has_missing_keys(2022) and year_has_missing_keys(2023):
        logger.info(
            "[M13] Missing required key lines in both 2022 and 2023 -> 3 points"
        )
        return 3

    logger.info("[M13] No reporting problems detected -> 0 points")
    return 0


def marker_14_bankruptcy_obligation_composite(
    f1300: YearsDict,
    f1200: YearsDict,
    f1500: YearsDict,
    f1210: YearsDict,
    f1410: YearsDict,
    f1510: YearsDict,
    f2110: YearsDict,
    f1250: YearsDict,
    f1520: YearsDict,
) -> int:
    """
    Маркер 14. Сводный признак обязанности подать заявление о банкротстве — 3 балла при ЛЮБОМ из сценариев:

    A) 1300 < 0 И 1200/1500 < 0.7 (в одном и том же году, берём последний год, где есть все поля)
    B) (1200-1210)/1500 < 0.6 И (1410+1510)/2110 > 2 (оба в одном последнем доступном году по каждой группе)
    C) 1250/1500 < 0.1 (в последнем доступном году) И ОДНОВРЕМЕННО условие маркера 8 на паре лет:
       кредиторка (1520) выросла ≥ 50% и выручка (2110) упала ≥ 30% на той же паре.

    Любая проблема с деноминатором/отсутствием данных в конкретной группе → та группа не срабатывает.
    """

    # Scenario A
    selA = _pick_latest_year_with_all([f1300, f1200, f1500])
    if selA:
        yr, [a1300, a1200, a1500] = selA
        r = safe_div(a1200, a1500)
        logger.info(f"[M14.A] Year {yr}: 1300={a1300}, 1200/1500={r}")
        if a1300 is not None and a1300 < 0 and r is not None and r < 0.7:
            return 3

    # Scenario B
    selB1 = _pick_latest_year_with_all([f1200, f1210, f1500])
    selB2 = _pick_latest_year_with_all([f1410, f1510, f2110])
    if selB1 and selB2:
        yr1, [b1200, b1210, b1500] = selB1
        yr2, [b1410, b1510, b2110] = selB2
        r_quick = safe_div(b1200 - b1210, b1500)
        r_lev = safe_div(b1410 + b1510, b2110)
        logger.info(f"[M14.B] Years {yr1}/{yr2}: quick={r_quick}, leverage={r_lev}")
        if r_quick is not None and r_quick < 0.6 and r_lev is not None and r_lev > 2:
            return 3

    # Scenario C
    selC = _pick_latest_year_with_all([f1250, f1500])
    if selC:
        yrC, [c1250, c1500] = selC
        r_abs = safe_div(c1250, c1500)
        logger.info(f"[M14.C] Year {yrC}: 1250/1500={r_abs}")
        if r_abs is not None and r_abs < 0.1:
            # need marker 8 condition on a pair
            pair = _pick_latest_consecutive_pair([f1520, f2110])
            if pair:
                prev_y, curr_y, [p1520, p2110], [c1520, c2110] = pair
                ch_ap = pct_change(p1520, c1520)
                ch_rev = pct_change(p2110, c2110)
                logger.info(
                    f"[M14.C] M8 check {prev_y}->{curr_y}: Δ1520={ch_ap}, Δ2110={ch_rev}"
                )
                if (
                    ch_ap is not None
                    and ch_rev is not None
                    and ch_ap >= 0.5
                    and ch_rev <= -0.3
                ):
                    return 3

    logger.info("[M14] Composite not triggered -> 0 points")
    return 0


def marker_15_ppe_share_drop_with_flat_or_falling_revenue(
    f1150: YearsDict, f1600: YearsDict, f2110: YearsDict
) -> int:
    """
    Маркер 15. Падение доли основных средств в активах
    - Условия:
        * Доля 1150/1600 снизилась за год ≥ 15 п.п. (0.15)
        * При этом выручка (2110) падает или не растёт «второй год».
      Практика:
        * Сначала проверяем 3-летнюю последовательность (2022,2023,2024):
            - r23 ≤ r22 и r24 ≤ r23 (non-increasing два года подряд),
            - и для пары 2023→2024 доля 1150/1600 упала ≥ 0.15.
        * Если 3 года недоступны — проверяем последнюю доступную пару:
            - доля упала ≥ 0.15 И выручка curr ≤ prev.
    """
    nf1150 = _normalize_years_dict(f1150)
    nf1600 = _normalize_years_dict(f1600)
    nf2110 = _normalize_years_dict(f2110)

    # Helper to compute share
    def share(y: int) -> Optional[float]:
        return (
            safe_div(nf1150.get(y), nf1600.get(y))
            if (y in nf1150 and y in nf1600)
            else None
        )

    # 3-year preferred route
    s22, s23, s24 = share(2022), share(2023), share(2024)
    r22, r23, r24 = nf2110.get(2022), nf2110.get(2023), nf2110.get(2024)

    if all(v is not None for v in (s23, s24)) and all(
        v is not None for v in (r23, r24)
    ):
        drop_pp = s24 - s23  # negative if drop
        # If all three rev years exist, enforce two-year non-increase; else fallback to pair-only logic later
        if all(v is not None for v in (s22, r22)):
            if r23 <= r22 and r24 <= r23 and drop_pp <= -0.15:
                logger.info(
                    f"[M15] 3y OK: shares 23->{s23}, 24->{s24}, drop={drop_pp}; rev 22->{r22},23->{r23},24->{r24}"
                )
                return 2

    # Fallback to last pair with valid shares and revenues
    pair = _pick_latest_consecutive_pair([f1150, f1600, f2110])
    if not pair:
        logger.info("[M15] No valid pair for 1150/1600 & 2110 -> 0 points")
        return 0

    prev_y, curr_y, [p1150, p1600, p2110], [c1150, c1600, c2110] = pair
    sh_prev = safe_div(p1150, p1600)
    sh_curr = safe_div(c1150, c1600)
    logger.info(
        f"[M15] {prev_y}->{curr_y}: share_prev={sh_prev}, share_curr={sh_curr}, rev_prev={p2110}, rev_curr={c2110}"
    )

    if sh_prev is None or sh_curr is None:
        return 0
    if (
        (sh_curr - sh_prev) <= -0.15
        and c2110 is not None
        and p2110 is not None
        and c2110 <= p2110
    ):
        return 2
    return 0


def marker_16_st_investments_growth(f1240: YearsDict, f1600: YearsDict) -> int:
    """
    Маркер 16. Рост краткосрочных финансовых вложений
    - Срабатывает, если на одной паре лет ИЛИ:
        A) 1240 выросли ≥ 50% (pct_change ≥ +0.50)
        B) доля 1240/1600 в текущем году ≥ 15% И выросла за год ≥ 8 п.п. (0.08)
    - Пара: (2023→2024), иначе (2022→2023).
    """
    pair = _pick_latest_consecutive_pair([f1240, f1600])
    if not pair:
        logger.info("[M16] No valid pair for 1240 & 1600 -> 0 points")
        return 0

    prev_y, curr_y, [p1240, p1600], [c1240, c1600] = pair
    ch_1240 = pct_change(p1240, c1240)
    share_prev = safe_div(p1240, p1600)
    share_curr = safe_div(c1240, c1600)

    logger.info(
        f"[M16] {prev_y}->{curr_y}: Δ1240={ch_1240}, share_prev={share_prev}, share_curr={share_curr}"
    )

    # A) raw growth
    if ch_1240 is not None and ch_1240 >= 0.50:
        return 2

    # B) share jump to >=15% with +8pp
    if share_prev is not None and share_curr is not None:
        grew_pp = share_curr - share_prev
        if share_curr >= 0.15 and grew_pp >= 0.08:
            return 2

    return 0


def marker_17_ca_not_up_ap_up(f1200: YearsDict, f1520: YearsDict) -> int:
    """
    Маркер 17. Оборотные активы не растут или уменьшаются, а кредиторка растёт
    - Условия на одной паре лет:
        * 1200_curr ≤ 1200_prev
        * 1520 выросли ≥ 30% (pct_change ≥ +0.30)
    - Пара: (2023→2024), иначе (2022→2023).
    """
    pair = _pick_latest_consecutive_pair([f1200, f1520])
    if not pair:
        logger.info("[M17] No valid pair for 1200 & 1520 -> 0 points")
        return 0

    prev_y, curr_y, [p1200, p1520], [c1200, c1520] = pair
    ch_ap = pct_change(p1520, c1520)
    logger.info(f"[M17] {prev_y}->{curr_y}: 1200 {p1200}->{c1200}, Δ1520={ch_ap}")

    if ch_ap is None:
        return 0
    if c1200 is not None and p1200 is not None and c1200 <= p1200 and ch_ap >= 0.30:
        return 2
    return 0


def marker_18_structural_anomalies(
    f1200: YearsDict,
    f1210: YearsDict,
    f1500: YearsDict,
    f1520: YearsDict,
    f2110: YearsDict,
) -> int:
    """
    Маркер 18. Структурные несоответствия — 1 балл при ЛЮБОМ из условий:
      (A) 1200 < 1210 в последнем году, где обе строки есть.
      (B) 1500 < 1520 в последнем году, где обе строки есть. (инфо-флаг; считаем как 1 балл)
      (C) 'Выручки' (2110) НЕТ два года подряд при наличии оборотных активов:
          трактуем как: в двух последовательных годах 2110 is None, при этом 1200 существует (и >0) хотя бы в одном из этих двух лет.
    Проверяем пары (2023,2024) затем (2022,2023). Если что-то триггерится — возвращаем 1.
    """
    # A) 1200 < 1210 on the latest year with both
    selA = _pick_latest_year_with_all([f1200, f1210])
    if selA:
        yr, [a1200, a1210] = selA
        logger.info(f"[M18.A] Year {yr}: 1200={a1200}, 1210={a1210}")
        if a1200 < a1210:
            return 1

    # B) 1500 < 1520 on the latest year with both
    selB = _pick_latest_year_with_all([f1500, f1520])
    if selB:
        yr, [a1500, a1520] = selB
        logger.info(f"[M18.B] Year {yr}: 1500={a1500}, 1520={a1520}")
        if a1500 < a1520:
            return 1

    # C) no revenue two years in a row, with CA present
    nf1200 = _normalize_years_dict(f1200)
    nf2110 = _normalize_years_dict(f2110)

    for prev_y, curr_y in [(2023, 2024), (2022, 2023)]:
        r_prev = nf2110.get(prev_y)
        r_curr = nf2110.get(curr_y)
        ca_prev = nf1200.get(prev_y)
        ca_curr = nf1200.get(curr_y)

        # revenue absent means None (not zero). CA considered present if value is not None and > 0
        if (
            r_prev is None
            and r_curr is None
            and (
                (ca_prev is not None and ca_prev > 0)
                or (ca_curr is not None and ca_curr > 0)
            )
        ):
            logger.info(
                f"[M18.C] No revenue in {prev_y} & {curr_y} with CA present -> 1 point"
            )
            return 1

    logger.info("[M18] No structural anomaly -> 0 points")
    return 0


def marker_19_off_balance_indicators(
    property_tax: YearsDict,  # налог на имущество
    transport_tax: YearsDict,  # транспортный налог
    egrul_active: YearsDict,  # 1/0: активность по ЕГРЮЛ (1=активна, 0=не подтверждается)
    rosstat_active: YearsDict,  # 1/0: активность по Росстату (1=активна, 0=нет)
    f1230: YearsDict,  # дебиторская задолженность
    f1170: YearsDict,  # ДФВ
    f1240: YearsDict,  # КФВ
    f1600: YearsDict,  # валюта баланса
) -> int:
    """
    Маркер 19. Внебалансовые индикаторы из смежных реестров — 2 балла
    Срабатывает при совокупности признаков на одной паре лет:
      (1) Налог(и) резко упали почти до нуля:
          - property_tax или transport_tax: curr ≤ 5% от prev И prev > 0.
      (2) Активность в реестрах не подтверждается в текущем году:
          - egrul_active_curr == 0 ИЛИ rosstat_active_curr == 0.
      (3) Одновременно в балансе есть крупные дебиторки/вложения:
          - (1230/1600 ≥ 20%) ИЛИ ((1170+1240)/1600 ≥ 20%) — в текущем году.
    Пара лет: (2023→2024) иначе (2022→2023).
    При отсутствии необходимых данных/деноминатора → 0 баллов.
    """
    # Pair for taxes + registers + balance totals
    pair = _pick_latest_consecutive_pair(
        [property_tax, transport_tax, egrul_active, rosstat_active, f1600]
    )
    if not pair:
        logger.info("[M19] No valid pair for taxes/registers/1600 -> 0 points")
        return 0

    (
        prev_y,
        curr_y,
        [p_prop, p_trans, p_egrul, p_rosstat, p1600],
        [c_prop, c_trans, c_egrul, c_rosstat, c1600],
    ) = pair

    # (1) tax collapse
    def collapsed(prev_v: Optional[float], curr_v: Optional[float]) -> bool:
        if prev_v is None or curr_v is None or prev_v <= 0:
            return False
        return curr_v <= 0.05 * prev_v

    tax_ok = collapsed(p_prop, c_prop) or collapsed(p_trans, c_trans)

    # (2) registers inactive at current year (treat non-zero as active)
    reg_inactive = False
    if (
        c_egrul is not None
        and _coerce_number(c_egrul) is not None
        and float(c_egrul) == 0
    ):
        reg_inactive = True
    if (
        c_rosstat is not None
        and _coerce_number(c_rosstat) is not None
        and float(c_rosstat) == 0
    ):
        reg_inactive = True

    # (3) large receivables/investments vs balance in current year
    sel_bal = _pick_latest_year_with_all(
        [f1600]
    )  # ensure we can fetch 1600 for the current selected year
    # But we need the SAME 'curr_y' year; pull directly from normalized dicts:
    nf1600 = _normalize_years_dict(f1600)
    nf1230 = _normalize_years_dict(f1230)
    nf1170 = _normalize_years_dict(f1170)
    nf1240 = _normalize_years_dict(f1240)

    bal = nf1600.get(curr_y)
    rec = nf1230.get(curr_y)
    lt_inv = nf1170.get(curr_y)
    st_inv = nf1240.get(curr_y)

    share_rec = safe_div(rec, bal) if (rec is not None and bal is not None) else None
    share_inv = (
        safe_div(
            (0 if lt_inv is None else lt_inv) + (0 if st_inv is None else st_inv), bal
        )
        if bal is not None
        else None
    )
    large_assets = (share_rec is not None and share_rec >= 0.20) or (
        share_inv is not None and share_inv >= 0.20
    )

    logger.info(
        f"[M19] {prev_y}->{curr_y}: tax_ok={tax_ok}, reg_inactive={reg_inactive}, "
        f"share_rec={share_rec}, share_inv={share_inv}, large_assets={large_assets}"
    )

    if tax_ok and reg_inactive and large_assets:
        return 2
    return 0


def calculate_all_markers_from_json(raw_data: dict) -> dict:
    """
    Pipe a raw RСБУ dump in, get back:
    {
      "markers": { "1": 3, "2": 2, ..., "19": 0 },
      "totals": { "sum": 14, "strong": 2, "medium": 4, "weak": 1 },
      "autopass": { "pass": True, "reason": "two_strongs" }
    }

    Notes:
    - Expects financial lines as "Ф1.xxxx" blocks (normalized to fxxxx).
    - For marker 19 (off-balance indicators), optionally accepts **non-РСБУ** keys at top-level:
        "property_tax": {"2023": 1000, "2024": 10},
        "transport_tax": {"2023": 300, "2024": 0},
        "egrul_active": {"2023": 1, "2024": 0},
        "rosstat_active": {"2023": 1, "2024": 0}
      Missing ones are treated as empty (marker returns 0).
    """
    data = normalize_rsbu_json(raw_data)

    # Helper to fetch or default to empty dict
    g = lambda k: data.get(k, {})

    # Non-РСБУ auxiliaries for marker 19 (gracefully handle if absent)
    def _norm_aux(name: str) -> dict[int, float | None]:
        block = raw_data.get(name)
        if not isinstance(block, dict):
            return {}
        # Accept {"2023": 1, "2024": 0} or {"values": {...}} shapes
        vals = block.get("values", block)
        out = {}
        for y, v in vals.items():
            try:
                y_int = int(y)
            except Exception:
                continue
            out[y_int] = _coerce_number(v)
        return out

    property_tax = _norm_aux("property_tax")
    transport_tax = _norm_aux("transport_tax")
    egrul_active = _norm_aux("egrul_active")
    rosstat_active = _norm_aux("rosstat_active")

    # ── Compute all markers ──
    m = {}
    m["1"] = marker_1_negative_equity(g("f1300"))
    m["2"] = marker_2_low_current_liquidity(g("f1200"), g("f1500"))
    m["3"] = marker_3_low_quick_liquidity(g("f1200"), g("f1210"), g("f1500"))
    m["4"] = marker_4_low_absolute_liquidity(g("f1250"), g("f1500"))
    m["5"] = marker_5_ppe_drop_25(g("f1150"))
    m["6"] = marker_6_lt_investments_shift(g("f1170"), g("f1600"))
    m["7"] = marker_7_frozen_receivables(g("f1230"), g("f2110"))
    m["8"] = marker_8_ap_up_rev_down(g("f1520"), g("f2110"))
    m["9"] = marker_9_cash_vs_ap(g("f1250"), g("f1520"))
    m["10"] = marker_10_debt_load_and_interest_cover(
        g("f1410"), g("f1510"), g("f2110"), g("f2200"), g("f2330")
    )
    m["11"] = marker_11_inventories_up_revenue_down(g("f1210"), g("f2110"))
    m["12"] = marker_12_large_asset_shifts(
        g("f1150"), g("f1170"), g("f1240"), g("f1600")
    )
    m["13"] = marker_13_reporting_problems(
        g("f1600"), g("f1700"), g("f2110"), g("f1200"), g("f1500")
    )
    m["14"] = marker_14_bankruptcy_obligation_composite(
        g("f1300"),
        g("f1200"),
        g("f1500"),
        g("f1210"),
        g("f1410"),
        g("f1510"),
        g("f2110"),
        g("f1250"),
        g("f1520"),
    )
    m["15"] = marker_15_ppe_share_drop_with_flat_or_falling_revenue(
        g("f1150"), g("f1600"), g("f2110")
    )
    m["16"] = marker_16_st_investments_growth(g("f1240"), g("f1600"))
    m["17"] = marker_17_ca_not_up_ap_up(g("f1200"), g("f1520"))
    m["18"] = marker_18_structural_anomalies(
        g("f1200"), g("f1210"), g("f1500"), g("f1520"), g("f2110")
    )

    # ── Scoring & autopass rules ──
    total = sum(m.values())
    strong = sum(1 for v in m.values() if v == 3)
    medium = sum(1 for v in m.values() if v == 2)
    weak = sum(1 for v in m.values() if v == 1)

    # Autopass:
    # • any pair of strong (3+3)
    # • OR 1 strong + 2 medium
    # • OR total ≥ 10
    autopass = {"pass": False, "reason": None}
    if strong >= 2:
        autopass = {"pass": True, "reason": "two_strongs"}
    elif strong >= 1 and medium >= 2:
        autopass = {"pass": True, "reason": "one_strong_two_mediums"}
    elif total >= 10:
        autopass = {"pass": True, "reason": "total_ge_10"}

    # Log a compact summary
    logger.info(
        f"[AGG] totals: sum={total}, strong={strong}, medium={medium}, weak={weak}, autopass={autopass}"
    )

    return {
        "markers": m,
        "totals": {"sum": total, "strong": strong, "medium": medium, "weak": weak},
        "autopass": autopass,
    }


# ───────────────────────────── Example usage (optional) ─────────────────────────────

def _demo() -> None:
    """
    Dummy financial data (years 2022–2024)
    Values are intentionally varied to trigger some markers
    """
    # Dummy financial data (years 2022–2024)
    # Values are intentionally varied to trigger some markers
    f = {
        "f1300": {2022: 5000, 2023: -2000, 2024: -1000},  # capital/reserves
        "f1200": {2022: 800, 2023: 700, 2024: 600},  # current assets
        "f1210": {2022: 300, 2023: 350, 2024: 400},  # inventories
        "f1250": {2022: 200, 2023: 100, 2024: 80},  # cash
        "f1150": {2022: 2000, 2023: 1800, 2024: 1200},  # PPE
        "f1170": {2022: 100, 2023: 200, 2024: 600},  # LT investments
        "f1240": {2022: 50, 2023: 60, 2024: 300},  # ST investments
        "f1410": {2022: 500, 2023: 600, 2024: 900},  # LT loans
        "f1500": {2022: 900, 2023: 1000, 2024: 1100},  # current liabilities
        "f1510": {2022: 200, 2023: 250, 2024: 400},  # ST loans
        "f1520": {2022: 400, 2023: 500, 2024: 800},  # accounts payable
        "f1600": {2022: 3000, 2023: 3200, 2024: 3100},  # balance total
        "f1700": {2022: 3000, 2023: 3200, 2024: 3150},  # balance liabilities total
        "f2110": {2022: 2000, 2023: 1500, 2024: 1000},  # revenue
        "f2200": {2022: 300, 2023: 250, 2024: 200},  # operating profit
        "f2330": {2022: 150, 2023: 200, 2024: 250},  # interest expenses
        "f1230": {
            2022: 500,
            2023: 600,
            2024: 700,
        },  # receivables (added to fix missing key)
    }

    # Run all 15 implemented markers
    results = {
        1: marker_1_negative_equity(f["f1300"]),
        2: marker_2_low_current_liquidity(f["f1200"], f["f1500"]),
        3: marker_3_low_quick_liquidity(f["f1200"], f["f1210"], f["f1500"]),
        4: marker_4_low_absolute_liquidity(f["f1250"], f["f1500"]),
        5: marker_5_ppe_drop_25(f["f1150"]),
        6: marker_6_lt_investments_shift(f["f1170"], f["f1600"]),
        7: marker_7_frozen_receivables(f["f1230"], f["f2110"]),
        8: marker_8_ap_up_rev_down(f["f1520"], f["f2110"]),
        9: marker_9_cash_vs_ap(f["f1250"], f["f1520"]),
        10: marker_10_debt_load_and_interest_cover(
            f["f1410"], f["f1510"], f["f2110"], f["f2200"], f["f2330"]
        ),
        11: marker_11_inventories_up_revenue_down(f["f1210"], f["f2110"]),
        12: marker_12_large_asset_shifts(
            f["f1150"], f["f1170"], f["f1240"], f["f1600"]
        ),
        13: marker_13_reporting_problems(
            f["f1600"], f["f1700"], f["f2110"], f["f1200"], f["f1500"]
        ),
        14: marker_14_bankruptcy_obligation_composite(
            f["f1300"],
            f["f1200"],
            f["f1500"],
            f["f1210"],
            f["f1410"],
            f["f1510"],
            f["f2110"],
            f["f1250"],
            f["f1520"],
        ),
        15: marker_15_ppe_share_drop_with_flat_or_falling_revenue(
            f["f1150"], f["f1600"], f["f2110"]
        ),
    }

    total_points = sum(results.values())

    print("\n=== Marker Results (1–15) ===")
    for k, v in results.items():
        print(f"Marker {k:>2}: {v} points")
    print(f"---\nTOTAL: {total_points} points\n")

    # Step 1: Analyze the finances file (adds markers_analysis to each lot)
    analyze_lots_finances_batch(
        input_path="debug/lot_details_with_finances2.json",
        output_path="debug/lot_details_with_finances2_analyzed.json",
    )

    # Step 2: Process and export (filters by autopass)
    processed = process_batch_for_export(
        input_path="debug/lot_details_with_finances2_analyzed.json",
        keep_only_autopass=True,
        drop_financials=False,
    )
    save_items_to_xlsx(processed, output_path="debug/lot_export2.xlsx")
    logger.info(f"Full marker check complete. Total={total_points}")

if __name__ == "__main__":
    # Uncomment to run the demo
    _demo()
