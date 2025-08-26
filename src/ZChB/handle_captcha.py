import re
import time
from typing import Optional
from patchright.sync_api import Page, TimeoutError
from loguru import logger


def _is_browser_check_page(page: Page) -> bool:
    """
    Эвристики для детекта промежуточной проверки браузера (как в zachestnyibiznes.ru).
    Смотрим на характерные тексты и элементы, чтобы не привязываться жёстко к одному селектору.
    """
    try:
        # 1) Заголовок проверки
        if page.locator("#ddg-l10n-title").count() > 0:
            return True
        if page.get_by_text("Проверка браузера перед переходом", exact=False).count() > 0:
            return True

        # 2) Подпись "Подождите несколько секунд"
        if page.get_by_text("Подождите несколько секунд", exact=False).count() > 0:
            return True

        # 3) Блок с Request ID / IP / Time (часто присутствует на экране проверки)
        if page.get_by_text(re.compile(r"Request ID: .* \| IP: .* \| Time:")).count() > 0:
            return True

        # 4) Спиннер
        if page.locator("img#ddg-img-loading").count() > 0:
            return True

        # 5) Атрибуты на <body>, которые встречаются на этой странице
        body = page.locator("body")
        if body.count() > 0:
            attr_flag = body.get_attribute("data-ddg-origin") or body.get_attribute("data-ddg-l10n")
            if attr_flag:
                return True
    except Exception as e:
        logger.debug(f"_is_browser_check_page: не удалось проверить DOM: {e}")

    return False


def handle_captcha(
    page: Page,
    expected_url: Optional[str] = None,
    timeout: float = 10.0,
    check_interval: float = 0.25,
) -> bool:
    """
    Ждёт авто-редирект после страницы «Проверка браузера…», чтобы сценарий не “пугался”.
    Возвращает True, если мы успешно прошли проверку/редирект или если проверки нет.
    Возвращает False по таймауту.

    Args:
        page: Playwright/Patchright Page
        expected_url: URL/шаблон, куда вы ожидаете прийти. Можно указывать подстановку,
                      например "https://zachestnyibiznes.ru/**".
                      Если None — ждём исчезновения экрана проверки.
        timeout: максимум ожидания (сек), по умолчанию 10
        check_interval: как часто проверять состояние (сек), по умолчанию 0.25
    """

    start_url = page.url
    deadline = time.monotonic() + timeout

    # Если мы сходу НЕ на экране проверки — просто выходим.
    if not _is_browser_check_page(page):
        logger.debug("handle_captcha: экран проверки не обнаружен, продолжаем выполнение.")
        return True

    logger.info("Обнаружен экран 'Проверка браузера…'. Ждём авто-редирект.")

    # Если задан ожидаемый URL — сначала пробуем подождать его напрямую.
    if expected_url:
        remaining = max(0, deadline - time.monotonic())
        try:
            logger.debug(f"Ожидаем URL: {expected_url} (таймаут {remaining:.2f}s)")
            page.wait_for_url(expected_url, timeout=int(remaining * 1000))
            page.wait_for_load_state("domcontentloaded", timeout=int(min(3000, remaining * 1000)))
            logger.success(f"Достигнут ожидаемый URL: {page.url}")
            return True
        except TimeoutError:
            logger.debug("Прямое ожидание ожидаемого URL не сработало, переключаемся на поллинг DOM/URL.")

    # Фолбэк: циклически проверяем, исчез ли экран проверки, или поменялся URL.
    while time.monotonic() < deadline:
        try:
            if not _is_browser_check_page(page):
                logger.success(f"Экран проверки исчез. Текущий URL: {page.url}")
                return True

            # Иногда redirect уже случился, но DOM ещё не обновлён полностью — проверим смену URL.
            if expected_url:
                try:
                    # Неблокирующий короткий чек URL
                    page.wait_for_url(expected_url, timeout=1)
                    logger.success(f"Достигнут ожидаемый URL: {page.url}")
                    return True
                except TimeoutError:
                    pass

            # Маленькая пауза между проверками.
            time.sleep(check_interval)
        except Exception as e:
            logger.debug(f"handle_captcha: исключение при поллинге: {e}")
            time.sleep(check_interval)

    logger.warning(
        f"handle_captcha: истёк таймаут ожидания ({timeout}s). "
        f"Стартовый URL был: {start_url}, текущий: {page.url}"
    )
    return False
