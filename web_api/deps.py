from functools import lru_cache

from web_api.services.ai_settings_service import AiSettingsService
from web_api.services.human_lock_service import HumanLockService
from web_api.services.knowledge_center_service import KnowledgeCenterService
from web_api.services.live_chat_service import LiveChatService
from web_api.services.product_service import ProductService
from web_api.services.product_sync_service import ProductSyncService
from web_api.services.provider_status_service import ProviderStatusService
from web_api.services.rag_debug_service import RagDebugService
from web_api.services.rag_job_service import RagJobService
from web_api.services.shop_service import ShopService
from web_api.services.shop_onboarding_service import ShopOnboardingService
from web_api.services.sop_service import SopService
from web_api.services.trace_service import TraceService


@lru_cache
def get_shop_service() -> ShopService:
    return ShopService()


@lru_cache
def get_ai_settings_service() -> AiSettingsService:
    return AiSettingsService()


@lru_cache
def get_product_service() -> ProductService:
    return ProductService()


@lru_cache
def get_sop_service() -> SopService:
    return SopService()


@lru_cache
def get_rag_job_service() -> RagJobService:
    return RagJobService()


@lru_cache
def get_rag_debug_service() -> RagDebugService:
    return RagDebugService()


@lru_cache
def get_trace_service() -> TraceService:
    return TraceService()


@lru_cache
def get_live_chat_service() -> LiveChatService:
    return LiveChatService(trace_service=get_trace_service())


@lru_cache
def get_provider_status_service() -> ProviderStatusService:
    return ProviderStatusService()


@lru_cache
def get_knowledge_center_service() -> KnowledgeCenterService:
    service = KnowledgeCenterService()
    service.init_schema()
    return service


@lru_cache
def get_human_lock_service() -> HumanLockService:
    return HumanLockService()


@lru_cache
def get_shop_onboarding_service() -> ShopOnboardingService:
    service = ShopOnboardingService()
    service.init_schema()
    return service


@lru_cache
def get_product_sync_service() -> ProductSyncService:
    service = ProductSyncService()
    service.init_schema()
    return service
