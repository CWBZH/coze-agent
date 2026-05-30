from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from web_api.routes import ai_settings, dashboard, health, human_locks, knowledge_center, live_chat, observability, product_sync, products, provider_status, rag_debug, rag_jobs, shop_onboarding, shops, sop, traces, worker_control


app = FastAPI(title="InternalEngine Web Admin API", version="mvp")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
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
