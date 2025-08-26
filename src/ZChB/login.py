import os
import re
import time
from pathlib import Path
from datetime import datetime

from patchright.sync_api import Page, TimeoutError
from loguru import logger
from dotenv import load_dotenv
from .handle_captcha import CaptchaHandler

load_dotenv()
LOGIN = os.getenv("LOGIN")
PWD = os.getenv("PWD")

# Initialize the captcha handler
captcha_handler = CaptchaHandler()

# --------- Diagnostics helpers ---------

DUMPS_DIR = Path(".zchb_dumps")
DUMPS_DIR.mkdir(exist_ok=True)

def _ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")

def _safe(op, default=None, note: str = ""):
    try:
        return op()
    except Exception as e:
        logger.debug(f"[safe:{note}] {e}")
        return default

def dump_state(page: Page, label: str) -> None:
    """
    Save as much context as possible for debugging:
    - screenshot
    - full HTML
    - storage state
    - cookies summary
    - header/body key text snippets
    - locator counts & text contents for critical markers
    """
    stamp = _ts()
    base = DUMPS_DIR / f"{stamp}_{label}"

    # Files
    png = str(base.with_suffix(".png"))
    html = str(base.with_suffix(".html"))
    storage = str(base.with_suffix(".storage.json"))
    info_txt = str(base.with_suffix(".info.txt"))

    # Screenshot & HTML
    _safe(lambda: page.screenshot(path=png, full_page=True), note=f"shot:{label}")
    _safe(lambda: Path(html).write_text(page.content(), encoding="utf-8"), note=f"html:{label}")

    # Storage state
    _safe(lambda: page.context.storage_state(path=storage), note=f"storage:{label}")

    # Cookies summary
    cookies = _safe(lambda: page.context.cookies(), default=[], note=f"cookies:{label}")
    cookie_lines = []
    for c in cookies or []:
        try:
            cookie_lines.append(f"{c.get('name')} @ {c.get('domain')} path={c.get('path')} httpOnly={c.get('httpOnly')} expires={c.get('expires')}")
        except Exception:
            pass

    # Header/body text snippets
    header_candidates = ["header", ".header", "#header", ".topbar", ".wrap", ".navbar", ".menu", ".user-menu"]
    header_texts = []
    for sel in header_candidates:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                # First match's text
                header_texts.append(f"{sel} -> {_safe(lambda: loc.first.inner_text()[:1000], '')}")
        except Exception:
            continue

    body_text_snippet = _safe(lambda: page.evaluate("document.body.innerText.slice(0, 1200) || ''"), "")
    url_now = page.url
    ua = _safe(lambda: page.evaluate("navigator.userAgent"), "")
    lang = _safe(lambda: page.evaluate("navigator.language"), "")

    # Critical locators we care about
    L = {
        "guest_text": page.get_by_text("Вход / Регистрация", exact=False),
        "login_link": page.locator("a[href*='/login']"),
        "register_link": page.locator("a[href*='register'], a[href*='signup']"),
        "logout_link": page.locator("a[href*='logout'], a[href*='logoff']"),
        "profile_link": page.locator("a[href*='/profile'], a[href*='/lk']"),
        "user_email_text_exact": page.get_by_text(LOGIN or "", exact=True) if LOGIN else page.locator("__never__"),
        "premium_text": page.get_by_text("Вы вошли в Платный доступ", exact=False),
        "session_conflict_text": page.get_by_text("В Ваш аккаунт выполнен вход с другого устройства", exact=False),
        "captcha_iframe": page.locator("iframe[src*='ddg'], #ddg-iframe"),
        "captcha_title": page.get_by_text("Проверка браузера", exact=False),
        "enter_text": page.get_by_text("Вход", exact=False),
        "register_text": page.get_by_text("Регистрация", exact=False),
    }

    lines = [
        f"== dump_state: {label} ==",
        f"URL: {url_now}",
        f"UA: {ua}",
        f"Lang: {lang}",
        f"Screenshot: {png}",
        f"HTML: {html}",
        f"Storage: {storage}",
        "",
        "Cookies:",
        *(cookie_lines or ["<none>"]),
        "",
        "Header candidates (text excerpts):",
        *(header_texts or ["<none>"]),
        "",
        "Body text snippet:",
        (body_text_snippet or "<empty>"),
        "",
        "Locator counts:",
    ]

    # Counts
    for name, loc in L.items():
        cnt = _safe(loc.count, -1, note=f"count:{name}")
        lines.append(f"  {name}: {cnt}")

    # Some text contents (best effort)
    lines.append("")
    lines.append("Locator text contents (first 2 matches where applicable):")
    for name, loc in L.items():
        try:
            sample_texts = []
            n = min(_safe(loc.count, 0, note=f"count2:{name}"), 2)
            for i in range(n):
                t = _safe(lambda: loc.nth(i).inner_text()[:500], "", note=f"text:{name}[{i}]")
                if t:
                    sample_texts.append(f"[{i}] {t}")
            if sample_texts:
                lines.append(f"  {name}:")
                lines.extend([f"    {row}" for row in sample_texts])
        except Exception:
            continue

    try:
        Path(info_txt).write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        logger.debug(f"failed to write info file: {e}")

    logger.info(f"[dump_state] Wrote artifacts for '{label}' to {base}")


def is_on_verification_like_page(page: Page) -> bool:
    # Treat these as verification contexts we must not evaluate guest markers against
    try:
        if "ddg" in page.url or "check" in page.url or "verify" in page.url:
            return True
        if page.locator("#ddg-iframe, iframe[src*='ddg']").count() > 0:
            return True
        if page.get_by_text("Проверка браузера", exact=False).count() > 0:
            return True
    except Exception:
        pass
    return False


def canonical_login_success(page: Page) -> bool:
    """
    Your rule: if 'Вход / Регистрация' is absent (and we are not on a verification page),
    treat as success. Also cross-check logout/profile/email to be robust.
    """
    if is_on_verification_like_page(page):
        logger.debug("[success-check] On verification-like page; not considering logged-in.")
        return False

    guest_present = False
    try:
        guest_present = page.get_by_text("Вход / Регистрация", exact=False).count() > 0
        # Be extra defensive: guest presence if both login and register links exist
        login_cnt = page.locator("a[href*='/login']").count()
        reg_cnt = page.locator("a[href*='register'], a[href*='signup']").count()
        if login_cnt > 0 and reg_cnt > 0:
            guest_present = True
    except Exception:
        pass

    logout_present = _safe(lambda: page.locator("a[href*='logout'], a[href*='logoff']").count() > 0, False, "logout_present")
    profile_present = _safe(lambda: page.locator("a[href*='/profile'], a[href*='/lk'], .user-menu, .avatar").count() > 0, False, "profile_present")
    email_present = False
    if LOGIN:
        email_present = _safe(lambda: page.get_by_text(LOGIN, exact=True).count() > 0, False, "email_present")

    logger.info(
        f"[success-check] guest_present={guest_present} logout_present={logout_present} "
        f"profile_present={profile_present} email_present={email_present} url={page.url}"
    )

    # Primary: your rule
    if not guest_present:
        return True

    # Secondary: sometimes header never shows guest text but still exposes strong signals
    if logout_present or profile_present or email_present:
        return True

    return False

# --------- Main flow ---------

def login(page: Page) -> bool:
    """
    Ensure we are logged into zachestnyibiznes.ru.
    Uses LOGIN and PWD from .env file.

    Returns:
        True if login successful, False otherwise.
    """
    max_attempts = 3
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        logger.info(f"Login attempt {attempt}/{max_attempts}")

        try:
            logger.info("Navigating to main page...")
            page.goto("https://zachestnyibiznes.ru/", wait_until="domcontentloaded", timeout=60000)

            # Handle browser verification and CAPTCHA
            if not captcha_handler.handle_browser_check(page, timeout=30):
                logger.warning("Browser verification/CAPTCHA handling failed on main page")
            dump_state(page, f"01_after_main_{attempt}")

            # Early success (already logged)
            if canonical_login_success(page):
                logger.success(f"Already logged in (no guest marker). URL={page.url}")
                return True

            logger.info("Not logged in. Going to login page...")
            page.goto("https://zachestnyibiznes.ru/login", wait_until="domcontentloaded", timeout=60000)

            # Handle browser verification and CAPTCHA on login page
            if not captcha_handler.handle_browser_check(page, timeout=30):
                logger.warning("Browser verification/CAPTCHA handling failed on login page")
            dump_state(page, f"02_on_login_{attempt}")

            time.sleep(1.5)

            if "login" not in page.url.lower():
                logger.warning(f"Not on login page, URL is: {page.url}")
                dump_state(page, f"02b_not_on_login_{attempt}")
                continue

            # Fill login form (keep your original selectors)
            page.get_by_role("textbox", name="Email или номер телефона").fill(LOGIN)
            page.get_by_role("textbox", name="Пароль").fill(PWD)
            logger.debug("Filled login credentials.")

            time.sleep(0.8)
            dump_state(page, f"03_before_submit_{attempt}")

            # Submit with network expectation to avoid racing the UI
            try:
                with page.expect_response(
                    lambda r: ("/login" in r.url) and (r.request.method in ("POST", "GET")),
                    timeout=15000
                ) as resp_info:
                    page.get_by_role("button", name="Войти").click()
                resp = resp_info.value
                logger.info(f"Login submit got response: {resp.status} {resp.url}")
            except TimeoutError:
                logger.warning("Did not capture a login response (timeout). Proceeding.")
                page.get_by_role("button", name="Войти").click()

            # Let the page settle
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            # Handle potential CAPTCHA after login attempt
            if not captcha_handler.handle_browser_check(page, timeout=30):
                logger.warning("CAPTCHA appeared after login attempt")

            time.sleep(2.0)
            dump_state(page, f"04_after_submit_{attempt}")

            # Session conflict handling (keep your logic)
            if page.get_by_text("В Ваш аккаунт выполнен вход с другого устройства", exact=False).count() > 0:
                logger.warning("Detected 'другого устройства' session conflict.")
                try:
                    timer_text = page.locator("span#t").inner_text(timeout=5000)
                    logger.debug(f"Timeout countdown: {timer_text}")
                    if re.match(r"^\d+:\d{2}$", timer_text):
                        minutes, seconds = map(int, timer_text.split(":"))
                        wait_time = minutes * 60 + seconds + 5
                        logger.info(f"Waiting {wait_time}s for redirect...")
                        time.sleep(wait_time)
                        captcha_handler.handle_browser_check(page, timeout=20)
                except Exception as e:
                    logger.error(f"Could not read timeout countdown: {e}")
                page.wait_for_load_state("domcontentloaded", timeout=10000)
                dump_state(page, f"05_after_session_conflict_{attempt}")

            # Premium login confirmation (keep; purely informational)
            if page.get_by_text("Вы вошли в Платный доступ", exact=False).count() > 0:
                logger.info("Detected premium login confirmation.")
                # force reload to apply cookies
                page.goto("https://zachestnyibiznes.ru/", wait_until="domcontentloaded", timeout=30000)
                captcha_handler.handle_browser_check(page, timeout=20)
                dump_state(page, f"07_after_premium_reload_{attempt}")
                if canonical_login_success(page):
                    logger.success(f"Login successful as {LOGIN} (via premium confirmation)")
                    return True

            # Final success evaluation (your rule + cross-checks)
            if canonical_login_success(page):
                logger.success(f"Login successful as {LOGIN}")
                dump_state(page, f"99_success_{attempt}")
                return True

            logger.warning(f"Login attempt {attempt} did not succeed - trying again")
            dump_state(page, f"97_attempt_failed_{attempt}")
            time.sleep(4)
            continue

        except Exception as e:
            logger.error(f"Error during login attempt {attempt}: {e}")
            dump_state(page, f"98_exception_{attempt}")
            time.sleep(4)
            continue

    logger.error("All login attempts failed")
    dump_state(page, "00_all_failed")
    return False
