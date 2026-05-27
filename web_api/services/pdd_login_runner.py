from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


LOGIN_SELECTOR_GROUPS: dict[str, list[str]] = {
    "login_tab": [
        "text=账号登录",
        "text=账户登录",
        "text=密码登录",
        "div.Common_item__3diIn",
    ],
    "account_input": [
        "input[name='username']",
        "input[placeholder*='账号']",
        "input[placeholder*='手机号']",
        "input[placeholder*='手机']",
        "input[type='text']",
    ],
    "password_input": [
        "input[name='password']",
        "input[placeholder*='密码']",
        "input[type='password']",
    ],
    "login_button": [
        "button:has-text('登录')",
        "text=登录",
        "button[type='submit']",
    ],
    "sms_input": [
        "input[placeholder*='短信']",
        "input[placeholder*='验证码']",
        "input[type='tel']",
    ],
    "sms_submit": [
        "button:has-text('确定')",
        "button:has-text('提交')",
        "button:has-text('登录')",
        "button[type='submit']",
    ],
    "logged_in": [
        "text=店铺",
        "text=订单查询",
        "text=商家后台",
    ],
    "sms_prompt": [
        "input[placeholder*='短信']",
        "input[placeholder*='验证码']",
        "input[type='tel']",
        "text=短信验证码",
        "text=验证码",
    ],
    "complex_verification": [
        "text=拖动",
        "text=滑块",
        "text=扫码",
        "text=二维码",
        "text=安全验证",
        "canvas",
    ],
}


def login_stage_failure_state(stage: str, reason: str) -> "LoginRunnerState":
    return LoginRunnerState(status="failed", step=stage, error_summary=f"{stage}_{reason}")


@dataclass(frozen=True)
class LoginRunnerState:
    status: str
    step: str
    needs_sms_code: bool = False
    needs_captcha: bool = False
    captcha_image_ref: str | None = None
    error_summary: str | None = None


@dataclass(frozen=True)
class LoginRunnerSuccess:
    shop_id: str
    shop_name: str
    user_id: str
    account_name: str
    cookie_value: str
    token_value: str | None = None


class PddLoginRunnerProtocol:
    def start_session(self, session_id: str, account_name: str, password: str | None, shop_name: str | None = None) -> LoginRunnerState:
        raise NotImplementedError

    def get_state(self, session_id: str) -> tuple[LoginRunnerState, LoginRunnerSuccess | None]:
        raise NotImplementedError

    def submit_sms_code(self, session_id: str, sms_code: str) -> tuple[LoginRunnerState, LoginRunnerSuccess | None]:
        raise NotImplementedError

    def submit_captcha(self, session_id: str, captcha_code: str) -> tuple[LoginRunnerState, LoginRunnerSuccess | None]:
        raise NotImplementedError

    def cancel(self, session_id: str) -> LoginRunnerState:
        raise NotImplementedError


class FakePddLoginRunner(PddLoginRunnerProtocol):
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, str | None]] = {}
        self._states: dict[str, LoginRunnerState] = {}

    def start_session(self, session_id: str, account_name: str, password: str | None, shop_name: str | None = None) -> LoginRunnerState:
        self._sessions[session_id] = {"account_name": account_name, "shop_name": shop_name, "password": None}
        state = LoginRunnerState(status="waiting_sms_code", step="waiting_sms_code", needs_sms_code=True)
        self._states[session_id] = state
        return state

    def get_state(self, session_id: str) -> tuple[LoginRunnerState, LoginRunnerSuccess | None]:
        return (self._states.get(session_id) or LoginRunnerState(status="failed", step="failed", error_summary="session_not_found"), None)

    def submit_sms_code(self, session_id: str, sms_code: str) -> tuple[LoginRunnerState, LoginRunnerSuccess | None]:
        data = self._sessions.get(session_id, {})
        if sms_code == "999999":
            state = LoginRunnerState(
                status="blocked_complex_verification",
                step="blocked_complex_verification",
                error_summary="complex_verification_required",
            )
            self._states[session_id] = state
            return (
                LoginRunnerState(
                    status="blocked_complex_verification",
                    step="blocked_complex_verification",
                    error_summary="complex_verification_required",
                ),
                None,
            )
        if sms_code != "123456":
            state = LoginRunnerState(status="failed", step="failed", error_summary="sms_code_invalid")
            self._states[session_id] = state
            return (state, None)
        account_name = str(data.get("account_name") or "seller")
        shop_name = str(data.get("shop_name") or "测试店铺")
        state = LoginRunnerState(status="succeeded", step="succeeded")
        success = LoginRunnerSuccess(
            shop_id="565617",
            shop_name=shop_name,
            user_id="fake-user-565617",
            account_name=account_name,
            cookie_value="fake-cookie-value",
            token_value="fake-token-value",
        )
        self._states[session_id] = state
        return (state, success)

    def submit_captcha(self, session_id: str, captcha_code: str) -> tuple[LoginRunnerState, LoginRunnerSuccess | None]:
        state = LoginRunnerState(status="failed", step="waiting_captcha", error_summary="unsupported_captcha_flow")
        self._states[session_id] = state
        return (state, None)

    def cancel(self, session_id: str) -> LoginRunnerState:
        self._sessions.pop(session_id, None)
        state = LoginRunnerState(status="cancelled", step="cancelled")
        self._states[session_id] = state
        return state


class RealPddLoginRunner(PddLoginRunnerProtocol):
    """Stateful Playwright-backed PDD login runner for Web onboarding.

    The runner keeps password and SMS code only in memory for the current login
    session. It never writes credentials and never sends platform messages.
    """

    def __init__(self, *, timeout_seconds: int = 120, headless: bool | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.headless = headless if headless is not None else os.environ.get("WEB_PDD_LOGIN_HEADLESS", "1").lower() not in {"0", "false", "no"}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _set_state(self, session_id: str, state: LoginRunnerState, success: LoginRunnerSuccess | None = None) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return
            session["state"] = state
            if success is not None:
                session["success"] = success
            if state.status in {"succeeded", "failed", "cancelled", "expired", "blocked_complex_verification"}:
                session["password"] = None
                session["sms_code"] = None
                event = session.get("sms_event")
                if isinstance(event, threading.Event):
                    event.set()

    def _get_session_state(self, session_id: str) -> tuple[LoginRunnerState, LoginRunnerSuccess | None]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return (LoginRunnerState(status="failed", step="failed", error_summary="session_not_found"), None)
            return (session["state"], session.get("success"))

    def start_session(self, session_id: str, account_name: str, password: str | None, shop_name: str | None = None) -> LoginRunnerState:
        if not password:
            return LoginRunnerState(status="failed", step="failed", error_summary="password_required")
        state = LoginRunnerState(status="opening_login_page", step="opening_login_page")
        with self._lock:
            self._sessions[session_id] = {
                "account_name": account_name,
                "shop_name": shop_name,
                "password": password,
                "sms_code": None,
                "sms_event": threading.Event(),
                "state": state,
                "success": None,
                "cancel_requested": False,
            }
        thread = threading.Thread(target=self._run_session_thread, args=(session_id,), daemon=True)
        with self._lock:
            self._sessions[session_id]["thread"] = thread
        thread.start()
        return state

    def get_state(self, session_id: str) -> tuple[LoginRunnerState, LoginRunnerSuccess | None]:
        return self._get_session_state(session_id)

    def submit_sms_code(self, session_id: str, sms_code: str) -> tuple[LoginRunnerState, LoginRunnerSuccess | None]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return (LoginRunnerState(status="failed", step="failed", error_summary="session_not_found"), None)
            session["sms_code"] = sms_code
            session["state"] = LoginRunnerState(status="logging_in", step="logging_in")
            event = session.get("sms_event")
            if isinstance(event, threading.Event):
                event.set()
        time.sleep(0.1)
        return self._get_session_state(session_id)

    def submit_captcha(self, session_id: str, captcha_code: str) -> tuple[LoginRunnerState, LoginRunnerSuccess | None]:
        state = LoginRunnerState(status="failed", step="waiting_captcha", error_summary="unsupported_captcha_flow")
        self._set_state(session_id, state)
        return (state, None)

    def cancel(self, session_id: str) -> LoginRunnerState:
        state = LoginRunnerState(status="cancelled", step="cancelled")
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session["cancel_requested"] = True
                session["password"] = None
                session["sms_code"] = None
                event = session.get("sms_event")
                if isinstance(event, threading.Event):
                    event.set()
                page = session.get("page")
                context = session.get("context")
                playwright = session.get("playwright")
                session["state"] = state
            else:
                page = context = playwright = None
        if any([page, context, playwright]):
            threading.Thread(target=self._close_resources_thread, args=(page, context, playwright), daemon=True).start()
        return state

    def _run_session_thread(self, session_id: str) -> None:
        try:
            asyncio.run(self._run_session_v2(session_id))
        except Exception as exc:  # pragma: no cover - defensive boundary for real Playwright runtime
            self._set_state(session_id, LoginRunnerState(status="failed", step="failed", error_summary=f"login_runner_error:{type(exc).__name__}"))

    async def _run_session_v2(self, session_id: str) -> None:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        playwright = None
        context = None
        page = None
        account_name = ""
        current_stage = "start"
        try:
            with self._lock:
                session = self._sessions[session_id]
                account_name = str(session["account_name"])
                password = str(session["password"])

            self._set_state(session_id, LoginRunnerState(status="opening_login_page", step="opening_login_page"))
            current_stage = "playwright_start"
            playwright = await async_playwright().start()

            user_data_root = Path(os.environ.get("WEB_PDD_LOGIN_USER_DATA_DIR", str(Path.cwd() / "temp" / "pdd_web_onboarding")))
            user_data_dir = str(user_data_root / _safe_path_part(account_name))
            current_stage = "browser_context"
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=self.headless,
                args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-notifications",
                ],
            )

            current_stage = "new_page"
            page = await context.new_page()
            with self._lock:
                if session_id in self._sessions:
                    self._sessions[session_id]["page"] = page
                    self._sessions[session_id]["context"] = context
                    self._sessions[session_id]["playwright"] = playwright

            current_stage = "open_login_page"
            await page.goto("https://mms.pinduoduo.com/login", wait_until="domcontentloaded", timeout=30000)
            self._set_state(session_id, LoginRunnerState(status="waiting_account", step="waiting_account"))

            current_stage = "login_tab"
            await _click_first_available(page, LOGIN_SELECTOR_GROUPS["login_tab"])
            current_stage = "account_input"
            await _fill_first_available(page, LOGIN_SELECTOR_GROUPS["account_input"], account_name)
            current_stage = "password_input"
            await _fill_first_available(page, LOGIN_SELECTOR_GROUPS["password_input"], password)
            self._set_state(session_id, LoginRunnerState(status="logging_in", step="logging_in"))

            current_stage = "login_button"
            await _click_first_available(page, LOGIN_SELECTOR_GROUPS["login_button"])
            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                if self._is_cancelled(session_id):
                    return

                current_stage = "logged_in_check"
                if await _looks_logged_in(page):
                    if await self._complete_success(session_id, account_name, context):
                        return

                current_stage = "complex_verification_check"
                if await _has_complex_verification(page):
                    self._set_state(
                        session_id,
                        LoginRunnerState(
                            status="blocked_complex_verification",
                            step="blocked_complex_verification",
                            error_summary="complex_verification_required_remote_browser_needed",
                        ),
                    )
                    return

                current_stage = "sms_prompt_check"
                if await _has_sms_code_prompt(page):
                    self._set_state(session_id, LoginRunnerState(status="waiting_sms_code", step="waiting_sms_code", needs_sms_code=True))
                    with self._lock:
                        session = self._sessions.get(session_id)
                        event = session.get("sms_event") if session else None
                    if isinstance(event, threading.Event):
                        await asyncio.get_running_loop().run_in_executor(None, event.wait, self.timeout_seconds)
                    if self._is_cancelled(session_id):
                        return
                    with self._lock:
                        sms_code = self._sessions.get(session_id, {}).get("sms_code")
                    if not sms_code:
                        self._set_state(session_id, LoginRunnerState(status="expired", step="expired", error_summary="sms_code_timeout"))
                        return
                    self._set_state(session_id, LoginRunnerState(status="logging_in", step="logging_in"))
                    current_stage = "sms_input"
                    await _fill_first_available(page, LOGIN_SELECTOR_GROUPS["sms_input"], str(sms_code))
                    current_stage = "sms_submit"
                    await _click_first_available(page, LOGIN_SELECTOR_GROUPS["sms_submit"])

                await asyncio.sleep(1)

            self._set_state(session_id, LoginRunnerState(status="expired", step="expired", error_summary="login_timeout"))
        except PlaywrightTimeoutError:
            self._set_state(session_id, login_stage_failure_state(current_stage, "timeout"))
        except Exception as exc:
            self._set_state(session_id, LoginRunnerState(status="failed", step="failed", error_summary=f"login_failed:{type(exc).__name__}"))
        finally:
            self._clear_sensitive(session_id)
            await _safe_close_playwright_resource(page)
            await _safe_close_playwright_resource(context)
            await _safe_close_playwright_resource(playwright)

    async def _run_session(self, session_id: str) -> None:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        playwright = None
        context = None
        page = None
        account_name = ""
        try:
            with self._lock:
                session = self._sessions[session_id]
                account_name = str(session["account_name"])
                password = str(session["password"])
            self._set_state(session_id, LoginRunnerState(status="opening_login_page", step="opening_login_page"))
            playwright = await async_playwright().start()
            user_data_root = Path(os.environ.get("WEB_PDD_LOGIN_USER_DATA_DIR", str(Path.cwd() / "temp" / "pdd_web_onboarding")))
            user_data_dir = str(user_data_root / _safe_path_part(account_name))
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=self.headless,
                args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-notifications",
                ],
            )
            page = await context.new_page()
            with self._lock:
                if session_id in self._sessions:
                    self._sessions[session_id]["page"] = page
                    self._sessions[session_id]["context"] = context
                    self._sessions[session_id]["playwright"] = playwright
            await page.goto("https://mms.pinduoduo.com/login", wait_until="domcontentloaded", timeout=30000)
            self._set_state(session_id, LoginRunnerState(status="waiting_account", step="waiting_account"))
            await _click_first_available(page, ["text=账号登录", "text=密码登录", "div.Common_item__3diIn"])
            await _fill_first_available(page, ["input[type='text']", "input[name='username']", "input[placeholder*='账号']"], account_name)
            await _fill_first_available(page, ["input[type='password']", "input[name='password']", "input[placeholder*='密码']"], password)
            self._set_state(session_id, LoginRunnerState(status="logging_in", step="logging_in"))
            await _click_first_available(page, ["button:has-text('登录')", "text=登录", "button[type='submit']"])
            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                if self._is_cancelled(session_id):
                    return
                if await _looks_logged_in(page):
                    await self._complete_success(session_id, account_name, context)
                    return
                if await _has_complex_verification(page):
                    self._set_state(
                        session_id,
                        LoginRunnerState(
                            status="blocked_complex_verification",
                            step="blocked_complex_verification",
                            error_summary="complex_verification_required_remote_browser_needed",
                        ),
                    )
                    return
                if await _has_sms_code_prompt(page):
                    self._set_state(session_id, LoginRunnerState(status="waiting_sms_code", step="waiting_sms_code", needs_sms_code=True))
                    with self._lock:
                        session = self._sessions.get(session_id)
                        event = session.get("sms_event") if session else None
                    if isinstance(event, threading.Event):
                        await asyncio.get_running_loop().run_in_executor(None, event.wait, self.timeout_seconds)
                    if self._is_cancelled(session_id):
                        return
                    with self._lock:
                        sms_code = self._sessions.get(session_id, {}).get("sms_code")
                    if not sms_code:
                        self._set_state(session_id, LoginRunnerState(status="expired", step="expired", error_summary="sms_code_timeout"))
                        return
                    self._set_state(session_id, LoginRunnerState(status="logging_in", step="logging_in"))
                    await _fill_first_available(page, ["input[placeholder*='验证码']", "input[placeholder*='短信']", "input[type='tel']"], str(sms_code))
                    await _click_first_available(page, ["button:has-text('确定')", "button:has-text('提交')", "button:has-text('登录')", "button[type='submit']"])
                await asyncio.sleep(1)
            self._set_state(session_id, LoginRunnerState(status="expired", step="expired", error_summary="login_timeout"))
        except PlaywrightTimeoutError:
            self._set_state(session_id, LoginRunnerState(status="failed", step="failed", error_summary="playwright_timeout"))
        except Exception as exc:
            self._set_state(session_id, LoginRunnerState(status="failed", step="failed", error_summary=f"login_failed:{type(exc).__name__}"))
        finally:
            self._clear_sensitive(session_id)
            await _safe_close_playwright_resource(page)
            await _safe_close_playwright_resource(context)
            await _safe_close_playwright_resource(playwright)

    async def _complete_success(self, session_id: str, account_name: str, context: Any) -> bool:
        cookies_list = await context.cookies()
        cookies_dict = {cookie.get("name", ""): cookie.get("value", "") for cookie in cookies_list if cookie.get("name")}
        cookies_json = json.dumps(cookies_dict, ensure_ascii=False)
        user_info = _fetch_pdd_user_info(cookies_dict)
        shop_info = _fetch_pdd_shop_info(cookies_dict)
        user_id = user_info.get("user_id")
        shop_id = shop_info.get("shop_id")
        shop_name = shop_info.get("shop_name")
        if user_id is None or shop_id is None:
            return False
        success = LoginRunnerSuccess(
            shop_id=str(shop_id),
            shop_name=str(shop_name or shop_id),
            user_id=str(user_id),
            account_name=account_name,
            cookie_value=cookies_json,
            token_value=None,
        )
        self._set_state(session_id, LoginRunnerState(status="succeeded", step="succeeded"), success)
        return True

    def _is_cancelled(self, session_id: str) -> bool:
        with self._lock:
            return bool(self._sessions.get(session_id, {}).get("cancel_requested"))

    def _clear_sensitive(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session["password"] = None
                session["sms_code"] = None

    def _close_resources_thread(self, page: Any, context: Any, playwright: Any) -> None:
        async def _close() -> None:
            await _safe_close_playwright_resource(page)
            await _safe_close_playwright_resource(context)
            await _safe_close_playwright_resource(playwright)

        try:
            asyncio.run(_close())
        except Exception:
            return


def _safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:80] or "account"


async def _safe_close_playwright_resource(resource: Any) -> None:
    if not resource:
        return
    close_fn = getattr(resource, "close", None)
    stop_fn = getattr(resource, "stop", None)
    action = close_fn or stop_fn
    if not action:
        return
    try:
        result = action()
        if asyncio.iscoroutine(result):
            await asyncio.wait_for(result, timeout=5)
    except Exception:
        return


def _fetch_pdd_user_info(cookies: dict[str, str]) -> dict[str, str | None]:
    response = requests.post(
        "https://mms.pinduoduo.com/janus/api/new/userinfo",
        data="",
        cookies=cookies,
        headers=_pdd_headers(),
        timeout=20,
    )
    data = response.json()
    if not data.get("success"):
        return {}
    result = data.get("result") or {}
    return {"user_id": result.get("id"), "user_name": result.get("username"), "mall_id": result.get("mall_id")}


def _fetch_pdd_shop_info(cookies: dict[str, str]) -> dict[str, str | None]:
    response = requests.post(
        "https://mms.pinduoduo.com/earth/api/merchant/queryMerchantInfoByMallId",
        json={},
        cookies=cookies,
        headers=_pdd_headers(),
        timeout=20,
    )
    data = response.json()
    if not data.get("success"):
        return {}
    result = data.get("result") or {}
    return {"shop_id": result.get("mallId"), "shop_name": result.get("mallName"), "shop_logo": result.get("mallLogo")}


def _pdd_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


async def _click_first_available(page: Any, selectors: list[str]) -> None:
    last_error: Exception | None = None
    for selector in selectors:
        try:
            await page.locator(selector).first.click(timeout=5000)
            return
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error


async def _fill_first_available(page: Any, selectors: list[str], value: str) -> None:
    last_error: Exception | None = None
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            await locator.wait_for(timeout=5000)
            await locator.fill(value, timeout=5000)
            return
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error


async def _has_selector(page: Any, selectors: list[str], timeout: int = 300) -> bool:
    for selector in selectors:
        try:
            if await page.locator(selector).first.count() > 0:
                await page.locator(selector).first.wait_for(timeout=timeout)
                return True
        except Exception:
            continue
    return False


async def _looks_logged_in(page: Any) -> bool:
    try:
        title = await page.title()
        url = page.url
        if "login" not in url.lower() and any(text in title for text in ["商家后台", "首页", "订单查询"]):
            return True
        return await _has_selector(page, ["text=店铺", "text=订单查询", "text=商家后台"], timeout=200)
    except Exception:
        return False


async def _has_sms_code_prompt(page: Any) -> bool:
    return await _has_selector(page, ["input[placeholder*='短信']", "input[placeholder*='验证码']", "input[type='tel']", "text=短信验证码"])


async def _has_complex_verification(page: Any) -> bool:
    return await _has_selector(page, ["text=拖动", "text=滑块", "text=扫码", "text=二维码", "text=安全验证", "canvas"], timeout=200)


def _title_looks_logged_in(title: str, url: str) -> bool:
    if "login" in url.lower():
        return False
    return any(text in title for text in ["商家后台", "首页", "订单查询"])


async def _looks_logged_in(page: Any) -> bool:
    try:
        title = await page.title()
        url = page.url
        if _title_looks_logged_in(title, url):
            return True
        return await _has_selector(page, LOGIN_SELECTOR_GROUPS["logged_in"], timeout=200)
    except Exception:
        return False


async def _has_sms_code_prompt(page: Any) -> bool:
    return await _has_selector(page, LOGIN_SELECTOR_GROUPS["sms_prompt"])


async def _has_complex_verification(page: Any) -> bool:
    return await _has_selector(page, LOGIN_SELECTOR_GROUPS["complex_verification"], timeout=200)
