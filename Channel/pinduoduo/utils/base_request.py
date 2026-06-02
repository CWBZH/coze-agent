import requests
import hashlib
import json
import time
import random
from typing import Dict, Any, Optional, Union, Callable
from utils.logger_loguru import get_logger
from database import db_manager

# 延迟导入，避免循环导入
import importlib


class BaseRequest:
    """
    API请求基类，统一管理requests请求

    功能特性：
    - 统一的请求重试机制（指数退避+随机抖动）
    - 自动会话过期检测和重新登录
    - 统一的错误处理和日志记录
    - 灵活的请求头和cookies管理

    自动重新登录说明：
    当API响应包含 error_code=43001 且 error_msg 包含"会话已过期"时，
    会自动调用 pdd_login.py 重新登录并更新cookies，然后重试原请求。
    """

    # 会话过期错误码
    SESSION_EXPIRED_ERROR_CODE = 43001
    # 重试抖动范围（随机因子乘数）
    RETRY_JITTER_MIN = 0.1
    RETRY_JITTER_MAX = 0.3

    def __init__(self, shop_id: str = None, user_id: str = None, channel_name: str = "pinduoduo",
                 max_retries: int = 3, retry_delay: float = 1.0, retry_backoff: float = 2.0):
        """
        初始化基类
        
        Args:
            shop_id: 店铺ID
            user_id: 用户ID  
            channel_name: 渠道名称
            max_retries: 最大重试次数
            retry_delay: 初始重试延迟时间（秒）
            retry_backoff: 重试退避倍数
        """
        self.logger = get_logger(self.__class__.__name__)
        self.shop_id = shop_id
        self.user_id = user_id
        self.channel_name = channel_name
        
        # 重试配置
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_backoff = retry_backoff
        
        # 默认请求头
        self.default_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
            'Content-Type': 'application/json',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'priority': 'u=1, i'
        }
        
        # 初始化账户信息和cookies
        self.cookies = {}
        self.auth_resolution = None
        self.account_name = "未知账号"
        
        if shop_id and user_id:
            self._init_account_info()
    
    def _init_account_info(self):
        """初始化账户信息"""
        try:
            resolved_auth = self._resolve_auth_cookies()
            self.auth_resolution = resolved_auth
            if resolved_auth is not None:
                if resolved_auth.status == "ok" and resolved_auth.cookies:
                    self.cookies = resolved_auth.cookies
                    if resolved_auth.account_name:
                        self.account_name = resolved_auth.account_name
                    self.logger.info(
                        f"账号授权读取成功: shop_id={self.shop_id}, user_id={self.user_id}, source={resolved_auth.source}, cookie_keys={len(self.cookies)}"
                    )
                    return
                if resolved_auth.status == "auth_invalid":
                    self.cookies = {}
                    return

            account_info = db_manager.get_account(self.channel_name, self.shop_id, self.user_id)
            if account_info:
                self.account_name = account_info.get('username', '未知账号')
                cookies_data = account_info.get('cookies')
                
                # 处理cookies格式
                if isinstance(cookies_data, str):
                    try:
                        self.cookies = json.loads(cookies_data)
                    except json.JSONDecodeError:
                        self.logger.error(f"解析账号 {self.account_name} 的cookies失败")
                        self.cookies = {}
                elif isinstance(cookies_data, dict):
                    self.cookies = cookies_data
                else:
                    self.logger.warning(f"账号 {self.account_name} 的cookies为空")
                    self.cookies = {}
            else:
                self.logger.error(f"无法在数据库中找到账户: shop_id={self.shop_id}, user_id={self.user_id}")
        except Exception as e:
            self.logger.error(f"初始化账户信息失败: {str(e)}")
    
    def _resolve_auth_cookies(self):
        try:
            from web_api.services.shop_auth_resolver import ShopAuthResolver

            resolved = ShopAuthResolver().get_cookies(
                str(self.shop_id),
                platform="pdd",
                user_id=str(self.user_id) if self.user_id else None,
            )
            if resolved.status in {"ok", "auth_invalid"}:
                if resolved.status == "auth_invalid":
                    self.logger.error(
                        f"账号授权无效: shop_id={self.shop_id}, user_id={self.user_id}, error_type={resolved.error_type}"
                    )
                return resolved
        except Exception as e:
            self.logger.warning(f"读取 shop_auth 授权失败，回退旧账号 cookies: {type(e).__name__}")
        return None

    def _is_session_expired(self, response_data: Dict[str, Any]) -> bool:
        """
        检测会话是否过期
        
        Args:
            response_data: 响应数据
            
        Returns:
            是否会话过期
        """
        if not response_data:
            return False
            
        # 检测拼多多会话过期的特征
        if (response_data.get('error_code') == self.SESSION_EXPIRED_ERROR_CODE and 
            '会话已过期' in str(response_data.get('error_msg', ''))):
            self.logger.warning(f"检测到账号 {self.account_name} 会话过期")
            return True
            
        return False
    
    def _run_async_login_func(self, func: callable, *args) -> Any:
        """
        在线程中安全执行异步登录函数（避免事件循环冲突）

        Args:
            func: 异步函数
            *args: 函数参数

        Returns:
            函数执行结果
        """
        from utils.async_helper import run_async_in_thread

        async def _run_wrapper() -> Any:
            return await func(*args)

        return run_async_in_thread(_run_wrapper(), timeout=60.0)

    def _get_account_credentials(self) -> Optional[tuple]:
        """
        获取账号凭证（用户名和密码）

        Returns:
            (username, password) 元组，或验证失败时返回 None
        """
        resolved = self.auth_resolution
        if resolved is not None and getattr(resolved, "credential_mode", "browser_only") == "password_available":
            username = getattr(resolved, "account_name", None) or self.account_name
            password = getattr(resolved, "password", None)
            if username and password:
                return username, password
            self.logger.error(f"账号 {self.account_name} 标记为可密码续登，但缺少加密密码凭据")
            return None

        account_info = db_manager.get_account(self.channel_name, self.shop_id, self.user_id)
        if not account_info:
            self.logger.error(f"无法获取账号信息: shop_id={self.shop_id}, user_id={self.user_id}")
            return None

        username = account_info.get('username')
        password = account_info.get('password')

        if not username:
            self.logger.error(f"账号 {self.account_name} 缺少用户名")
            return None

        return username, password

    def _is_playwright_relogin_allowed(self) -> bool:
        """Only password-backed authorization may use Playwright renewal."""
        resolved = self.auth_resolution
        credential_mode = getattr(resolved, "credential_mode", "browser_only") if resolved is not None else "browser_only"
        if credential_mode == "password_available":
            return True
        self._mark_auth_required("session_expired_browser_only_reauth_required")
        self.logger.warning(
            f"session expired for browser-only auth: shop_id={self.shop_id}, user_id={self.user_id}; noVNC reauth is required"
        )
        return False

    def _mark_auth_required(self, reason: str) -> None:
        """Mark Web Admin auth state invalid after PDD session renewal cannot continue."""
        if not self.shop_id:
            return
        try:
            from web_api.services.shop_auth_service import ShopAuthService

            ShopAuthService().mark_auth_required(
                str(self.shop_id),
                platform="pdd",
                reason=reason,
            )
        except Exception as exc:
            self.logger.warning(
                f"mark auth_required failed: shop_id={self.shop_id}, user_id={self.user_id}, "
                f"reason={reason}, error_type={type(exc).__name__}"
            )

    def _relogin_and_update_cookies(self) -> bool:
        """
        重新获取cookies并更新
        优先使用refresh_cookies（无需重新输入密码），失败时回退到完整重新登录

        Returns:
            是否重新获取cookies成功
        """
        try:
            if not self._is_playwright_relogin_allowed():
                return False
            credentials = self._get_account_credentials()
            if not credentials:
                self._mark_auth_required("session_expired_missing_credentials")
                return False
            username, password = credentials

            pdd_login_module = importlib.import_module('Channel.pinduoduo.pdd_login')

            # 优先尝试刷新cookies
            self.logger.info(f"尝试为账号 {self.account_name} 刷新cookies（无需重新登录）...")

            try:
                refresh_result = self._run_async_login_func(
                    pdd_login_module.refresh_pdd_cookies, username, password
                )

                if refresh_result and isinstance(refresh_result, dict):
                    new_cookies = refresh_result.get('cookies')
                    if new_cookies:
                        self._apply_new_cookies(new_cookies)
                        self.logger.info(f"账号 {self.account_name} 会话凭据刷新成功")
                        return True
                    else:
                        self.logger.warning(f"账号 {self.account_name} 会话凭据刷新返回无效数据")
                else:
                    self.logger.warning(f"账号 {self.account_name} 会话凭据刷新失败，可能登录状态已失效")

            except Exception as refresh_error:
                self.logger.warning(f"账号 {self.account_name} 会话凭据刷新异常: {str(refresh_error)}")

            # 回退到完整重新登录
            if not password:
                self.logger.error(f"账号 {self.account_name} 缺少密码，无法进行完整重新登录")
                self._mark_auth_required("session_expired_missing_password")
                return False

            self.logger.info(f"回退到完整重新登录模式（账号 {self.account_name}）...")

            try:
                login_result = self._run_async_login_func(
                    pdd_login_module.login_pdd, username, password
                )

                if login_result and isinstance(login_result, dict):
                    new_cookies = login_result.get('cookies')
                    if new_cookies:
                        self._apply_new_cookies(new_cookies)
                        self.logger.info(f"账号 {self.account_name} 完整重新登录成功，会话凭据已更新")
                        return True
                    else:
                        self.logger.error(f"账号 {self.account_name} 完整重新登录失败：未获取到有效会话凭据")
                        self._mark_auth_required("session_expired_relogin_failed")
                        return False
                else:
                    self.logger.error(f"账号 {self.account_name} 完整重新登录失败")
                    self._mark_auth_required("session_expired_relogin_failed")
                    return False

            except Exception as login_error:
                self.logger.error(f"账号 {self.account_name} 完整重新登录异常: {str(login_error)}")
                self._mark_auth_required("session_expired_relogin_exception")
                return False

        except Exception as e:
            self.logger.error(f"账号 {self.account_name} 重新获取会话凭据过程中发生错误: {str(e)}")
            self._mark_auth_required("session_expired_relogin_exception")
            return False
    
    def _should_retry(self, response: requests.Response = None, exception: Exception = None) -> bool:
        """
        判断是否应该重试
        
        Args:
            response: HTTP响应对象
            exception: 异常对象
            
        Returns:
            是否应该重试
        """
        if exception:
            # 网络相关异常应该重试
            if isinstance(exception, (requests.ConnectionError, requests.Timeout, 
                                    requests.HTTPError, requests.TooManyRedirects)):
                return True
        
        if response:
            # 服务器错误状态码应该重试
            if response.status_code >= 500:
                return True
            # 特定的客户端错误也可以重试
            if response.status_code in [429, 408, 502, 503, 504]:
                return True
        
        return False
    
    def _calculate_retry_delay(self, attempt: int) -> float:
        """
        计算重试延迟时间（指数退避+随机抖动）
        
        Args:
            attempt: 当前重试次数
            
        Returns:
            延迟时间（秒）
        """
        # 指数退避：base_delay * (backoff ^ attempt)
        delay = self.retry_delay * (self.retry_backoff ** attempt)
        
        # 添加随机抖动，避免雷鸣群体效应
        jitter = random.uniform(self.RETRY_JITTER_MIN, self.RETRY_JITTER_MAX) * delay
        
        return delay + jitter
    
    def _execute_with_retry(self, request_func: Callable, expect_json: bool = True) -> Optional[Dict[str, Any]]:
        """
        带重试机制执行请求
        
        Args:
            request_func: 请求函数
            expect_json: 是否期望JSON响应
            
        Returns:
            响应数据
        """
        last_exception = None
        last_response = None
        relogin_attempted = False  # 标记是否已尝试重新登录
        
        for attempt in range(self.max_retries + 1):
            try:
                response = request_func()
                
                # 检查响应是否成功
                if response and response.status_code == 200:
                    response_data = self._handle_response(response, expect_json)
                    
                    # 检测会话是否过期
                    if (response_data and self._is_session_expired(response_data) 
                        and not relogin_attempted and self.shop_id and self.user_id):
                        
                        self.logger.info(f"检测到会话过期，尝试重新登录...")
                        relogin_attempted = True
                        
                        if self._relogin_and_update_cookies():
                            self.logger.info(f"重新登录成功，重试请求...")
                            # 重新登录成功，继续下一次循环重试请求
                            continue
                        else:
                            self.logger.error(f"重新登录失败，请求终止")
                            return response_data
                    
                    return response_data
                
                last_response = response
                
                # 判断是否应该重试
                if attempt < self.max_retries and self._should_retry(response=response):
                    delay = self._calculate_retry_delay(attempt)
                    self.logger.warning(f"请求失败，状态码: {response.status_code}，"
                                      f"第 {attempt + 1} 次重试，延迟 {delay:.2f} 秒")
                    time.sleep(delay)
                    continue
                else:
                    # 不需要重试或已达最大重试次数
                    return self._handle_response(response, expect_json)
                    
            except Exception as e:
                last_exception = e
                
                # 判断是否应该重试
                if attempt < self.max_retries and self._should_retry(exception=e):
                    delay = self._calculate_retry_delay(attempt)
                    self.logger.warning(f"请求异常: {str(e)}，"
                                      f"第 {attempt + 1} 次重试，延迟 {delay:.2f} 秒")
                    time.sleep(delay)
                    continue
                else:
                    # 不需要重试或已达最大重试次数
                    self.logger.error(f"请求最终失败: {str(e)}")
                    return None
        
        # 如果所有重试都失败了
        if last_exception:
            self.logger.error(f"重试 {self.max_retries} 次后仍然失败，最后异常: {str(last_exception)}")
        elif last_response:
            self.logger.error(f"重试 {self.max_retries} 次后仍然失败，最后状态码: {last_response.status_code}")
        
        return None
    
    def _merge_headers(self, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        合并请求头
        
        Args:
            headers: 自定义请求头
            
        Returns:
            合并后的请求头
        """
        merged_headers = self.default_headers.copy()
        if headers:
            merged_headers.update(headers)
        return merged_headers
    
    def _handle_response(self, response: requests.Response, expect_json: bool = True) -> Optional[Dict[str, Any]]:
        """
        统一处理响应
        
        Args:
            response: requests响应对象
            expect_json: 是否期望JSON响应
            
        Returns:
            解析后的响应数据，失败返回None
        """
        try:
            # 检查HTTP状态码
            if response.status_code != 200:
                text_length, text_hash = self._text_fingerprint(response.text)
                self.logger.error(
                    f"请求失败，状态码: {response.status_code}, response_length={text_length}, response_hash={text_hash}"
                )
                return None
            
            if expect_json:
                try:
                    return response.json()
                except json.JSONDecodeError:
                    text_length, text_hash = self._text_fingerprint(response.text)
                    self.logger.error(
                        f"解析JSON响应失败: response_length={text_length}, response_hash={text_hash}"
                    )
                    return None
            else:
                return {"text": response.text, "status_code": response.status_code}
                
        except Exception as e:
            self.logger.error(f"处理响应时发生错误: {str(e)}")
            return None
    
    _SENSITIVE_KEYS = {'password', 'cookies', 'token', 'api_key', 'access_token', 'anti-content', 'anti_content'}

    def _text_fingerprint(self, value: Any) -> tuple[int, str]:
        if value is None:
            return 0, ""
        text = value if isinstance(value, str) else str(value)
        digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12] if text else ""
        return len(text), digest

    def _sanitize_for_log(self, data: Any) -> Any:
        """对日志中的敏感字段进行脱敏处理"""
        if not isinstance(data, dict):
            return data
        result = {}
        for k, v in data.items():
            if k.lower() in self._SENSITIVE_KEYS or any(s in k.lower() for s in self._SENSITIVE_KEYS):
                result[k] = '***'
            elif isinstance(v, dict):
                result[k] = self._sanitize_for_log(v)
            elif isinstance(v, list):
                result[k] = [self._sanitize_for_log(i) if isinstance(i, dict) else i for i in v]
            else:
                result[k] = v
        return result

    def _log_request(self, method: str, url: str, **kwargs):
        """记录请求日志（自动脱敏敏感字段）"""
        self.logger.debug(f"发起{method}请求: {url}")
        if 'data' in kwargs or 'json' in kwargs:
            params = kwargs.get('data') or kwargs.get('json')
            self.logger.debug(f"请求参数: {self._sanitize_for_log(params)}")
    
    def get(self, url: str, params: Optional[Dict] = None, headers: Optional[Dict[str, str]] = None, 
            timeout: int = 30, expect_json: bool = True, **kwargs) -> Optional[Dict[str, Any]]:
        """
        发起GET请求
        
        Args:
            url: 请求URL
            params: URL参数
            headers: 自定义请求头
            timeout: 超时时间
            expect_json: 是否期望JSON响应
            **kwargs: 其他requests参数
            
        Returns:
            响应数据
        """
        merged_headers = self._merge_headers(headers)
        self._log_request("GET", url, params=params)
        
        def _make_request():
            return requests.get(
                url, 
                params=params,
                headers=merged_headers,
                cookies=self.cookies,
                timeout=timeout,
                **kwargs
            )
        
        return self._execute_with_retry(_make_request, expect_json=expect_json)
    
    def post(self, url: str, data: Optional[Union[Dict, str]] = None, json_data: Optional[Dict] = None,
             headers: Optional[Dict[str, str]] = None, timeout: int = 30, 
             expect_json: bool = True, **kwargs) -> Optional[Dict[str, Any]]:
        """
        发起POST请求
        
        Args:
            url: 请求URL
            data: 表单数据
            json_data: JSON数据
            headers: 自定义请求头
            timeout: 超时时间
            expect_json: 是否期望JSON响应
            **kwargs: 其他requests参数
            
        Returns:
            响应数据
        """
        merged_headers = self._merge_headers(headers)
        self._log_request("POST", url, data=data, json=json_data)
        
        def _make_request():
            return requests.post(
                url,
                data=data,
                json=json_data,
                headers=merged_headers,
                cookies=self.cookies,
                timeout=timeout,
                **kwargs
            )
        
        return self._execute_with_retry(_make_request, expect_json=expect_json)
    
    def generate_request_id(self) -> int:
        """生成请求ID"""
        return int(time.time() * 1000)
    
    def update_cookies(self, new_cookies: Union[Dict, str]) -> None:
        """
        更新cookies
        
        Args:
            new_cookies: 新的cookies数据
        """
        if isinstance(new_cookies, str):
            try:
                self.cookies = json.loads(new_cookies)
            except json.JSONDecodeError:
                self.logger.error("更新cookies失败: JSON解析错误")
        elif isinstance(new_cookies, dict):
            self.cookies = new_cookies
        else:
            self.logger.error("更新cookies失败: 不支持的数据类型")
    
    def set_default_header(self, key: str, value: str) -> None:
        """
        设置默认请求头
        
        Args:
            key: 请求头键
            value: 请求头值
        """
        self.default_headers[key] = value
    
    def remove_default_header(self, key: str) -> None:
        """
        移除默认请求头
        
        Args:
            key: 请求头键
        """
        if key in self.default_headers:
            del self.default_headers[key]
    
    def set_retry_config(self, max_retries: int = None, retry_delay: float = None,
                        retry_backoff: float = None) -> None:
        """
        动态设置重试配置
        
        Args:
            max_retries: 最大重试次数
            retry_delay: 初始重试延迟时间（秒）
            retry_backoff: 重试退避倍数
        """
        if max_retries is not None:
            self.max_retries = max_retries
        if retry_delay is not None:
            self.retry_delay = retry_delay
        if retry_backoff is not None:
            self.retry_backoff = retry_backoff
        
        self.logger.info(f"重试配置已更新: max_retries={self.max_retries}, "
                        f"retry_delay={self.retry_delay}, retry_backoff={self.retry_backoff}")
    
    def disable_retry(self) -> None:
        """禁用重试功能"""
        self.max_retries = 0
        self.logger.info("重试功能已禁用")

    def enable_retry(self, max_retries: int = 3) -> None:
        """启用重试功能"""
        self.max_retries = max_retries
        self.logger.info(f"重试功能已启用，最大重试次数: {max_retries}")
    
    def get_retry_config(self) -> Dict[str, Union[int, float]]:
        """
        获取当前重试配置
        
        Returns:
            重试配置字典
        """
        return {
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'retry_backoff': self.retry_backoff
        }
    
    def _apply_new_cookies(self, new_cookies: Any) -> None:
        """
        应用新cookies到当前实例并持久化到数据库

        Args:
            new_cookies: 新cookies
        """
        self.update_cookies(new_cookies)
        try:
            from web_api.services.shop_auth_service import AuthSavePayload, ShopAuthService

            account_info = db_manager.get_account(self.channel_name, self.shop_id, self.user_id)
            shop_info = db_manager.get_shop(self.channel_name, self.shop_id)
            username = (account_info or {}).get("username") or self.account_name
            ShopAuthService().save_auth(
                AuthSavePayload(
                    shop_id=str(self.shop_id),
                    shop_name=(shop_info or {}).get("shop_name") or str(self.shop_id),
                    platform="pdd",
                    account_name=str(username or ""),
                    user_id=str(self.user_id or username or ""),
                    cookie_value=json.dumps(self.cookies, ensure_ascii=False),
                    credential_mode=getattr(self.auth_resolution, "credential_mode", "browser_only")
                    if self.auth_resolution is not None
                    else "browser_only",
                    auth_state_reason="playwright_cookie_refresh_succeeded",
                )
            )
            self.logger.info(f"账号 {self.account_name} 会话凭据已加密保存到 shop_auth")
        except Exception as e:
            self.logger.warning(f"账号 {self.account_name} 新 cookies 仅更新到内存，shop_auth 加密保存失败: {type(e).__name__}")

    def force_relogin(self) -> bool:
        """
        强制重新获取cookies
        优先尝试刷新cookies，失败时进行完整重新登录

        Returns:
            是否重新获取cookies成功
        """
        if not self.shop_id or not self.user_id:
            self.logger.error("无法强制重新获取cookies：缺少shop_id或user_id")
            return False

        self.logger.info(f"手动触发账号 {self.account_name} 重新获取cookies...")
        return self._relogin_and_update_cookies()

    def force_refresh_cookies(self) -> bool:
        """
        强制只刷新cookies（不进行完整重新登录）

        Returns:
            是否刷新cookies成功
        """
        if not self.shop_id or not self.user_id:
            self.logger.error("无法强制刷新cookies：缺少shop_id或user_id")
            return False

        try:
            credentials = self._get_account_credentials()
            if not credentials:
                self.logger.error(f"无法获取账号信息进行cookies刷新")
                return False
            username, password = credentials

            self.logger.info(f"手动触发账号 {self.account_name} 刷新cookies（仅刷新模式）...")

            pdd_login_module = importlib.import_module('Channel.pinduoduo.pdd_login')
            refresh_result = self._run_async_login_func(
                pdd_login_module.refresh_pdd_cookies, username, password
            )

            if refresh_result and isinstance(refresh_result, dict):
                new_cookies = refresh_result.get('cookies')
                if new_cookies:
                    self._apply_new_cookies(new_cookies)
                    self.logger.info(f"账号 {self.account_name} 会话凭据刷新成功（仅刷新模式）")
                    return True
                else:
                    self.logger.error(f"账号 {self.account_name} 会话凭据刷新失败：未获取到有效会话凭据")
                    return False
            else:
                self.logger.error(f"账号 {self.account_name} 会话凭据刷新失败")
                return False

        except Exception as e:
            self.logger.error(f"账号 {self.account_name} 会话凭据刷新过程中发生错误: {str(e)}")
            return False
