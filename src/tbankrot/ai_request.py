import json
import os
import re
from typing import Any, Dict, List, Union

import requests
from dotenv import load_dotenv

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "google/gemini-2.5-flash-lite"
"""
The `ai_request.py` module provides a single entrypoint function `update_debtor_data(data)` that takes a Python dictionary with at least the key `"announcement_text"` and enriches it by calling the OpenRouter API (Gemini 2.5 flash-lite) to extract structured debtor information. It automatically loads your `OPENROUTER_APIKEY` from `.env`, sends the text to the model, and parses the JSON response into consistent arrays: `debtor_name`, `debtor_inn`, `debtor_ogrn`, `case_number`, and `nominal_debt` (floats). The function gracefully handles malformed responses, ensures those keys always exist as lists, and appends any extracted values into them.

To use it, import the function and pass a dict containing `"announcement_text"`. Example:

```python
from ai_request import update_debtor_data

data = {"announcement_text": "Задолженность ООО «МАКСМАРКЕТ» ..."}
result = update_debtor_data(data)
print(result)
```
This will return the same dict, augmented with parsed debtor details.

"""

def _first_json_block(text: str) -> str:
    """
    Извлекает первый корректно сбалансированный JSON-блок из произвольной строки.
    Поддерживает как объект { ... }, так и массив [ ... ], а также игнорирует
    возможные обрамления в виде ```json ... ``` и т.п.
    """
    if not text:
        return ""

    # Срежем кодовые блоки ```...```
    fence = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
    text = fence.sub("", text.strip())

    # Найти первый символ { или [
    start_idx = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start_idx = i
            break
    if start_idx is None:
        return text.strip()

    opening = text[start_idx]
    closing = "}" if opening == "{" else "]"

    depth = 0
    in_string = False
    escape = False

    for j in range(start_idx, len(text)):
        ch = text[j]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == opening:
                depth += 1
            elif ch == closing:
                depth -= 1
                if depth == 0:
                    return text[start_idx : j + 1].strip()

    # Если не удалось корректно сбалансировать — вернём хвост как есть
    return text[start_idx:].strip()


def _to_list(value: Any) -> List[Any]:
    """Нормализует значение к списку (если уже список — возвращает как есть; None -> [])."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _ensure_lists_in_data(data: Dict[str, Any], keys: List[str]) -> None:
    """Гарантирует, что у data есть массивы под нужными ключами."""
    for k in keys:
        data.setdefault(k, [])
        if not isinstance(data[k], list):
            data[k] = _to_list(data[k])


def _extend_field(data: Dict[str, Any], key: str, vals: Union[List[Any], Any]) -> None:
    """Добавляет в data[key] одно или несколько значений без дедупликации."""
    if isinstance(vals, list):
        data[key].extend(v for v in vals if v is not None and v != "")
    else:
        if vals is not None and vals != "":
            data[key].append(vals)


def _as_float_list(vals: Union[List[Any], Any]) -> List[float]:
    """Пытается привести значения к списку float, пропуская непереводимые элементы."""
    out: List[float] = []
    for v in _to_list(vals):
        try:
            # Разделители тысяч/пробелы/непробельные символы типа NBSP чистим грубо
            if isinstance(v, str):
                cleaned = v.replace("\xa0", " ").replace(" ", "").replace(",", ".")
                out.append(float(cleaned))
            else:
                out.append(float(v))
        except Exception:
            # мягко игнорируем мусор
            continue
    return out


def update_debtor_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Делает запрос к OpenRouter, парсит JSON-ответ и добавляет найденные поля в data.
    Всегда возвращает массивы:
      - debtor_name (List[str])
      - debtor_inn (List[str])
      - debtor_ogrn (List[str])
      - case_number (List[str])
      - nominal_debt (List[float])
    """
    load_dotenv()
    api_key = os.getenv("OPENROUTER_APIKEY")
    if not api_key:
        print("Ошибка: переменная окружения OPENROUTER_APIKEY не установлена.")
        # Гарантируем наличие ключей
        _ensure_lists_in_data(data, ["debtor_name", "debtor_inn", "debtor_ogrn", "case_number", "nominal_debt"])
        return data

    text = data.get("announcement_text", "") or ""

    prompt = f"""Ты — эксперт по автоматическому извлечению данных (information extraction) из текстов о задолженностях. 
Твоя задача — извлечь сведения о должниках и вернуть их в строго структурированном JSON.

**Инструкция:**
1. Определи всех должников в тексте. Должник — лицо, к которому предъявляется финансовое требование.
2. Извлеки для каждого должника:
- debtor_name — массив строк с именами должников(могут быть и физ. лица)
- debtor_inn — массив строк с ИНН 
- debtor_ogrn — массив строк с ОГРН 
- case_number — массив строк с номерами дел (формат типа А40-113129/2022).
- nominal_debt — массив чисел (float). Указывай все упомянутые суммы долгов (основной, проценты, общий размер и т.п.).
3. Если данные не найдены, соответствующее поле — пустой массив [].
4. Ответ — только JSON. Никакого дополнительного текста.

**Примеры:**

**Пример 1:**
*Текст:*  
Дебиторская задолженность ООО «Белоярский центр генеральных подрядов (ИНН: 6670292134) на сумму 1 367 775 154,22 руб.  

*Результат:*  
```json
{{
"debtor_name": ["ООО «Белоярский центр генеральных подрядов"],
"debtor_inn": ["6670292134"],
"debtor_ogrn": [],
"case_number": [],
"nominal_debt": [1367775154.22]
}}
```

**Пример 2:**
*Текст:*
Задолженность ООО «МАКСМАРКЕТ» (ИНН 5032257375) в размере 3 899 283,00 рублей основного долга и 73 298,00 рублей процентов, а также проценты, рассчитанные по ст. 395 ГК РФ с 21.05.2024 по дату фактической оплаты суммы задолженности, установленная вступившем в силу Решением Арбитражного суда Московской области от 16 августа 2024 года по делу №А41-42654/2024, заявленная ко включению в реестр требований кредиторов по делу А41-73860/2024 в общем размере 4 248 940,02 руб.

*Результат:*

```json
{{
"debtor_name": ["ООО «МАКСМАРКЕТ»"],
"debtor_inn": ["5032257375"],
"debtor_ogrn": [],
"case_number": ["А41-42654/2024", "А41-73860/2024"],
"nominal_debt": [3899283.0, 73298.0, 4248940.02]
}}
```

**Пример 3:**
*Текст:*
Права требования к АО «ВЕКТОРТРЕЙД», установленные решением Арбитражного суда г. Москвы от 25.08.22, Постановлением Девятого арбитражного апелляционного суда от 19.06.23 по делу № А40-113129/2022;
Права требования к ООО «Маренго», установленные определением Арбитражного суда г. Москвы от 27.10.23 по делу № А40-239608/2020.

*Результат:*

```json
{{
"debtor_name": ["АО «ВЕКТОРТРЕЙД»", "ООО «Маренго»"],
"debtor_inn": [],
"debtor_ogrn": [],
"case_number": ["А40-113129/2022", "А40-239608/2020"],
"nominal_debt": []
}}
```

**Пример 4:**
*Текст:*
Право требования к Администрации Пролетарского городского поселения (ИНН 5310017050, ОГРН 1115321002972, адрес: 173530, рп. Полетарий, ул. Пролетарская, д.19) в сумме 84 080,03 руб.

*Результат:*

```json
{{
"debtor_name": ["Администрации Пролетарского городского поселения"],
"debtor_inn": ["5310017050"],
"debtor_ogrn": ["1115321002972"],
"case_number": [],
"nominal_debt": [84080.03]
}}
```

**Теперь выполни задачу для следующего текста:**

*Текст:*
{text}

*Результат:*

```json
    """
    # prompt = data.get("_prompt_override") or f"[PROMPT_OMITTED_FOR_BREVITY]\n\n{text}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }

    # Гарантируем нужные ключи как списки заранее
    target_keys = ["debtor_name", "debtor_inn", "debtor_ogrn", "case_number", "nominal_debt"]
    _ensure_lists_in_data(data, target_keys)

    try:
        resp = requests.post(OPENROUTER_API_URL, headers=headers, data=json.dumps(payload), timeout=60)
        resp.raise_for_status()
        response_json = resp.json()
        content = (
            response_json.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        cleaned = _first_json_block(content)
        if not cleaned:
            return data

        # Иногда модель склеивает несколько объектов без [] — попробуем мягко обернуть
        # Но сначала обычная попытка распарсить как есть
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # Хак: удалить переводы строк/лишние пробелы между },{ и попробовать обернуть в []
            glued = re.sub(r"\s+", " ", cleaned).strip()
            if "}," in glued and "{" in glued and not glued.strip().startswith("["):
                try:
                    parsed = json.loads(f"[{glued}]")
                except Exception:
                    raise
            else:
                raise

        # Теперь нормализуем и переносим значения в data
        def absorb(obj: Dict[str, Any]) -> None:
            # Каждое поле может быть скаляром или списком
            # nominal_debt приводим к float
            if "debtor_name" in obj:
                _extend_field(data, "debtor_name", _to_list(obj.get("debtor_name")))
            if "debtor_inn" in obj:
                _extend_field(data, "debtor_inn", _to_list(obj.get("debtor_inn")))
            if "debtor_ogrn" in obj:
                _extend_field(data, "debtor_ogrn", _to_list(obj.get("debtor_ogrn")))
            if "case_number" in obj:
                _extend_field(data, "case_number", _to_list(obj.get("case_number")))
            if "nominal_debt" in obj:
                data["nominal_debt"].extend(_as_float_list(obj.get("nominal_debt")))

        if isinstance(parsed, dict):
            # Вариант: один объект сразу со списками
            absorb(parsed)
        elif isinstance(parsed, list):
            # Вариант: список объектов / список словарей
            for elem in parsed:
                if isinstance(elem, dict):
                    absorb(elem)
                elif isinstance(elem, list):
                    # иногда может быть вложенный список — попробуем разобрать словари внутри
                    for sub in elem:
                        if isinstance(sub, dict):
                            absorb(sub)
        else:
            # Ничего полезного
            pass

    except requests.RequestException as e:
        print(f"Ошибка запроса к API: {e}")
    except json.JSONDecodeError:
        print(f"Ошибка: не удалось распознать JSON в ответе: {cleaned if 'cleaned' in locals() else '<<empty>>'}")
    except Exception as e:
        print(f"Непредвиденная ошибка при обработке ответа: {e}")

    return data


def update_debtor_flags(data: dict) -> dict:
    """
    Sends a separate AI request to classify:
      - foreign_debtor_flag: 0 (no foreign), 1 (mixed), or "иностранная" (all foreign)
      - individuals: "физлицо" if exclusively individuals, else ""

    Input:
      data: {
        "announcement_text": str,
        ...
      }

    Output (mutates and returns data):
      data["foreign_debtor_flag"] in {0, 1, "иностранная"}
      data["individuals"] in {"физлицо", ""}
    """
    # Ensure defaults
    if "foreign_debtor_flag" not in data:
        data["foreign_debtor_flag"] = 0
    if "individuals" not in data:
        data["individuals"] = ""

    load_dotenv()
    api_key = os.getenv("OPENROUTER_APIKEY")
    if not api_key:
        print("Ошибка: переменная окружения OPENROUTER_APIKEY не установлена.")
        return data

    text = (data.get("announcement_text") or "").strip()

    prompt = f"""
Ты — эксперт по извлечению структурированных признаков из юридических объявлений о дебиторской задолженности.
Задача: по полному тексту объявления (далее: announcement_text) определить два признака и вернуть СТРОГИЙ JSON без лишнего текста.

Определения:
- foreign_debtor_flag:
  • 0 — если среди должников нет иностранных;
  • 1 — если есть смешение: часть должников иностранные, часть — российские;
  • "иностранная" — если все должники иностранные.
- individuals:
  • "физлицо" — если должники представлены ИСКЛЮЧИТЕЛЬНО как физические лица (население, граждане, люди), без упоминаний организаций;
  • "" — во всех остальных случаях (включая смешанные списки, компании и т.п.).

Используй ТОЛЬКО announcement_text. Не используй никаких других полей.

Агрегация:
- Если ВСЕ обнаруженные должники — иностранные → foreign_debtor_flag = "иностранная".
- Если есть и иностранные, и российские → foreign_debtor_flag = 1.
- Если иностранных нет → foreign_debtor_flag = 0.
- individuals = "физлицо" только если должники представлены исключительно как физлица; иначе "".

Формат ответа — СТРОГИЙ JSON, без комментариев и без обрамления ```:
{{
  "foreign_debtor_flag": 0 | 1 | "иностранная",
  "individuals": "физлицо" | ""
}}

Пример:
announcement_text: "Право требования к физическим лицам …"
Результат:
{{
  "foreign_debtor_flag": 0,
  "individuals": "физлицо"
}}

Теперь обработай следующий текст и верни только JSON:
announcement_text:
{text}
"""

 

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        resp = requests.post(OPENROUTER_API_URL, headers=headers, data=json.dumps(payload), timeout=60)
        resp.raise_for_status()
        response_json = resp.json()
        content = (
            response_json.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        cleaned = _first_json_block(content)
        if not cleaned:
            return data

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            glued = re.sub(r"\s+", " ", cleaned).strip()
            parsed = json.loads(glued)  # last-ditch attempt

        if not isinstance(parsed, dict):
            return data

        raw_foreign = parsed.get("foreign_debtor_flag", data["foreign_debtor_flag"])
        raw_indiv = parsed.get("individuals", data["individuals"])

        # Normalize foreign_debtor_flag -> {0, 1, "иностранная"}
        def norm_foreign(v):
            if isinstance(v, str):
                vs = v.strip().lower()
                if vs in {"0", "none", "no", "нет", "domestic", "российская", "только российская"}:
                    return 0
                if vs in {"1", "some", "mixed", "смешанная", "частично", "да"}:
                    return 1
                if vs in {"иностранная", "иностранный", "all", "foreign", "all_foreign", "только иностранная", "полностью иностранная"}:
                    return "иностранная"
            if isinstance(v, (int, float)):
                i = int(v)
                if i == 0:
                    return 0
                if i == 1:
                    return 1
                if i >= 2:  # tolerate 2 meaning "all foreign"
                    return "иностранная"
            return 0

        # Normalize individuals -> "физлицо" | ""
        def norm_individuals(v):
            if not isinstance(v, str):
                return ""
            vs = v.strip().lower()
            if vs in {
                "физлицо", "физ.лицо", "физические лица", "физлица",
                "граждане", "гражданин", "individual", "natural_persons"
            }:
                return "физлицо"
            return ""

        data["foreign_debtor_flag"] = norm_foreign(raw_foreign)
        data["individuals"] = norm_individuals(raw_indiv)

    except requests.RequestException as e:
        print(f"Ошибка запроса к API: {e}")
    except json.JSONDecodeError:
        print(f"Ошибка: не удалось распознать JSON в ответе: {cleaned if 'cleaned' in locals() else '<<empty>>'}")
    except Exception as e:
        print(f"Непредвиденная ошибка при обработке ответа: {e}")

    return data
