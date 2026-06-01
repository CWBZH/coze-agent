from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from web_api.routes import admin_auth, ai_settings, dashboard, health, human_locks, knowledge_center, live_chat, observability, product_sync, products, provider_status, rag_debug, rag_jobs, shop_onboarding, shops, sop, traces, worker_control
from web_api.services.admin_auth_service import AdminAuthError, AdminAuthService, SESSION_COOKIE_NAME, is_admin_auth_exempt_path


app = FastAPI(title="InternalEngine Web Admin API", version="mvp")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_admin_session(request: Request, call_next):
    path = request.url.path
    if request.method != "OPTIONS" and path.startswith("/api/") and not is_admin_auth_exempt_path(path):
        auth = AdminAuthService()
        if not auth.configured:
            return JSONResponse(
                status_code=503,
                content={
                    "error_type": "AUTH_NOT_CONFIGURED",
                    "error_summary": "后台登录密码未配置，请先设置 WEB_ADMIN_PASSWORD 或 WEB_ADMIN_PASSWORD_SHA256。",
                    "next_action": "配置 .env.web 后重启 Web API。",
                },
            )
        try:
            auth.verify_token(request.cookies.get(SESSION_COOKIE_NAME))
        except AdminAuthError as exc:
            return JSONResponse(
                status_code=401,
                content={
                    "error_type": "AUTH_REQUIRED",
                    "error_summary": "请先登录 AI 客服运营后台。",
                    "next_action": "跳转到登录页后重新登录。",
                    "reason": str(exc),
                },
            )
    return await call_next(request)


app.include_router(health.router, prefix="/api")
app.include_router(admin_auth.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(provider_status.router, prefix="/api")
app.include_router(shop_onboarding.router, prefix="/api")
app.include_router(shops.router, prefix="/api")
app.include_router(ai_settings.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(product_sync.router, prefix="/api")
app.include_router(sop.router, prefix="/api")
app.include_router(knowledge_center.router, prefix="/api")
app.include_router(human_locks.router, prefix="/api")
app.include_router(rag_jobs.router, prefix="/api")
app.include_router(rag_debug.router, prefix="/api")
app.include_router(live_chat.router, prefix="/api")
app.include_router(traces.router, prefix="/api")
app.include_router(worker_control.router, prefix="/api")
app.include_router(observability.router, prefix="/api")
