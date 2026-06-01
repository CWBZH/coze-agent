from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from web_api.services.admin_auth_service import AdminAuthError, AdminAuthService, SESSION_COOKIE_NAME


router = APIRouter(prefix="/auth", tags=["admin-auth"])


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = True


def _cookie_kwargs(auth: AdminAuthService, max_age: int | None = None) -> dict:
    kwargs = {
        "httponly": True,
        "samesite": "lax",
        "secure": auth.cookie_secure,
        "path": "/",
    }
    if max_age is not None:
        kwargs["max_age"] = max_age
    return kwargs


@router.post("/login")
def login(payload: LoginRequest) -> Response:
    auth = AdminAuthService()
    if not auth.configured:
        return JSONResponse(
            status_code=503,
            content={
                "error_type": "AUTH_NOT_CONFIGURED",
                "error_summary": "后台登录密码未配置，请先设置 WEB_ADMIN_PASSWORD 或 WEB_ADMIN_PASSWORD_SHA256。",
                "next_action": "在 .env.web 中配置 WEB_ADMIN_USERNAME 和 WEB_ADMIN_PASSWORD 后重启 Web API。",
            },
        )
    if not auth.verify_credentials(payload.username, payload.password):
        return JSONResponse(
            status_code=401,
            content={
                "error_type": "LOGIN_FAILED",
                "error_summary": "账号或密码不正确。",
                "next_action": "请检查后台管理员账号和密码。",
            },
        )
    token, ttl = auth.issue_token(auth.username, remember=payload.remember)
    response = JSONResponse(
        content={
            "authenticated": True,
            "username": auth.username,
            "configured": auth.configured,
            "insecure_default_secret": auth.insecure_default_secret,
        }
    )
    response.set_cookie(SESSION_COOKIE_NAME, token, **_cookie_kwargs(auth, max_age=ttl))
    return response


@router.post("/logout")
def logout() -> Response:
    auth = AdminAuthService()
    response = JSONResponse(content={"authenticated": False})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax", secure=auth.cookie_secure)
    return response


@router.get("/session")
def session(request: Request) -> Response:
    auth = AdminAuthService()
    if not auth.configured:
        return JSONResponse(
            status_code=503,
            content={
                "authenticated": False,
                "configured": False,
                "error_type": "AUTH_NOT_CONFIGURED",
                "error_summary": "后台登录密码未配置。",
            },
        )
    try:
        return JSONResponse(content=auth.public_session(request.cookies.get(SESSION_COOKIE_NAME)))
    except AdminAuthError as exc:
        return JSONResponse(
            status_code=401,
            content={
                "authenticated": False,
                "configured": True,
                "error_type": "AUTH_REQUIRED",
                "error_summary": "后台登录会话不存在或已过期。",
                "reason": str(exc),
            },
        )
