"""
自定义 CustomerAgent 实现 - V2.0 LangGraph 重构版

基于 LangGraph 状态机的客服 Agent，支持：
- 三级路由漏斗
- 生成检索隔离
- 会话状态管理

架构演进：
- V1.0: 简单 while 循环 + ReAct 工具调用
- V2.0: LangGraph 图工作流 + 状态机

V2.0 战役七：上线预备重构
- 抽离硬编码 TTL 到 core.config
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Literal

from Agent.bot import Bot

# 导入工具模块，触发 @agent_tool 装饰器注册
from Agent.CustomerAgent.tools import (
    send_goods_link,                  # noqa: F401
    move_conversation,                # noqa: F401
    get_product_list,                 # noqa: F401
    get_product_knowledge,            # noqa: F401
    search_customer_service_knowledge,  # noqa: F401
)
from bridge.context import Context
from bridge.reply import Reply, ReplyType
from Agent.CustomerAgent.custom.session_manager import SessionManager
from Agent.CustomerAgent.custom.tool_decorator import get_tools_for_llm
from utils.logger_loguru import get_logger

# 导入重构后的模块
from Agent.CustomerAgent.custom.agent_config import (
    AgentConfig,
    DEFAULT_DB_PATH,
    DEFAULT_TOKEN_WINDOW,
    DEFAULT_COMPRESS_RATIO,
    DEFAULT_RETAIN_COUNT,
    DEFAULT_MAX_LOOPS,
    DEFAULT_TEMPERATURE,
)
from Agent.CustomerAgent.custom.llm_client import LLMClient, LLMResponse
from Agent.CustomerAgent.custom.message_builder import MessageBuilder
from Agent.CustomerAgent.custom.tool_executor import ToolExecutor, ToolResult
from Agent.CustomerAgent.custom.local_llm_client import LocalLLMClient, LocalLLMConfig

# 导入 LangGraph 相关模块
from Agent.CustomerAgent.custom.graph_state import (
    CustomerServiceState,
    AlertLevel,
    IntentType,
    SubIntentType,
    RetrievalPolicy,
    NodeName,
    REDLINE_KEYWORDS,
    HUMAN_REQUEST_KEYWORDS,
    AFTER_SALES_KEYWORDS,
    PRE_SALE_KEYWORDS,
    RECOMMEND_KEYWORDS,
    LOGISTICS_KEYWORDS,
)

# 导入集中式配置和常量
from core.config import INTENT_CACHE_TTL, HUMAN_LOCK_TTL, SHORT_SENTENCE_THRESHOLD
from core.constants import HUMAN_BUSY_REPLY

# LangGraph 导入
try:
    from langgraph.graph import StateGraph, END, START
    from langgraph.checkpoint.memory import MemorySaver
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    get_logger("CustomerAgent").warning(
        "langgraph 未安装，请运行: pip install langgraph"
    )

logger = get_logger("CustomerAgent")


class CustomerAgent(Bot):
    """
    自定义客服 Agent - V2.0 LangGraph 版

    核心架构：
    - LangGraph 状态机驱动的工作流
    - 三级路由漏斗：规则引擎 → 语义路由 → LLM决策
    - 生成检索隔离：知识检索与回复生成分离

    节点流程：
    START → node_router → [node_human_fallback | node_retriever]
    node_retriever → node_generator → END
    node_human_fallback → END
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        token_window: int = DEFAULT_TOKEN_WINDOW,
        compress_ratio: float = DEFAULT_COMPRESS_RATIO,
        retain_count: int = DEFAULT_RETAIN_COUNT,
        max_loops: int = DEFAULT_MAX_LOOPS,
        temperature: float = DEFAULT_TEMPERATURE,
    ):
        super().__init__()
        self._is_initialized = False

        # 配置参数
        self._config = AgentConfig(
            db_path=db_path or DEFAULT_DB_PATH,
            token_window=token_window,
            compress_ratio=compress_ratio,
            retain_count=retain_count,
            max_loops=max_loops,
            temperature=temperature,
        )

        # 子组件（延迟初始化）
        self._llm_client: Optional[LLMClient] = None
        self._message_builder: Optional[MessageBuilder] = None
        self._tool_executor: Optional[ToolExecutor] = None
        self._session_manager: Optional[SessionManager] = None
        self._tools: List[Dict[str, Any]] = []
        self._local_llm_client: Optional[LocalLLMClient] = None
        self._product_memory_cache: Dict[str, Dict[str, Any]] = {}

        # LangGraph 工作流（延迟构建）
        self._graph = None
        self._checkpointer = None

        logger.info("CustomerAgent V2.0 实例创建成功")

    async def initialize_async(self) -> bool:
        """异步初始化 Agent"""
        if self._is_initialized:
            return True

        try:
            # 1. 从配置文件加载配置
            self._config = AgentConfig.load_from_config()

            # 2. 验证配置
            if not self._config.validate():
                return False

            # 3. 初始化 LLM 客户端
            self._llm_client = LLMClient(
                api_key=self._config.api_key,
                api_base=self._config.api_base,
                model_name=self._config.model_name,
                temperature=self._config.temperature,
            )
            await self._llm_client.initialize()

            # 4. 初始化会话管理器
            self._session_manager = SessionManager(
                db_path=self._config.db_path,
                token_window=self._config.token_window,
                compress_ratio=self._config.compress_ratio,
                retain_count=self._config.retain_count,
                model_name=self._config.model_name,
            )

            # 5. 初始化消息构建器
            self._message_builder = MessageBuilder(
                instructions=self._config.instructions,
            )

            # 6. 初始化工具执行器
            self._tool_executor = ToolExecutor()

            # 7. 加载工具列表
            self._tools = get_tools_for_llm()
            self._llm_client.tools = self._tools
            tool_names = [t.get("function", {}).get("name", "unknown") for t in self._tools]
            logger.info(f"已加载 {len(self._tools)} 个工具: {tool_names}")

            # 8. 初始化本地 LLM 客户端
            if self._config.local_model.enabled:
                self._local_llm_client = LocalLLMClient(self._config.local_model)
                local_ready = await self._local_llm_client.initialize()
                if local_ready:
                    logger.info("本地 LLM 客户端初始化成功")
                else:
                    logger.warning("本地 LLM 客户端初始化失败，将使用远程 API")
            else:
                self._local_llm_client = None

            # 9. 构建 LangGraph 工作流（Fail-Fast：必须成功）
            if not LANGGRAPH_AVAILABLE:
                raise RuntimeError(
                    "V2.0 架构加载失败！LangGraph 依赖缺失，请执行：pip install langgraph langchain langchain-core"
                )
            self._graph = self._build_graph()
            self._checkpointer = MemorySaver()
            logger.log("INNER", "LangGraph 工作流构建成功")

            self._is_initialized = True
            logger.info(f"CustomerAgent V2.0 初始化成功: model={self._config.model_name}")
            return True

        except Exception as e:
            logger.error(f"CustomerAgent 初始化失败: {e}")
            return False

    # =========================================================================
    # 商品推荐会话记忆与结构化检索 helpers
    # =========================================================================

    PRODUCT_MEMORY_TTL = 1800
    PRODUCT_MEMORY_PREFIX = "product_memory:"
    SECONDARY_ROUTING_ENABLED = False

    def _clean_user_query(self, query: str) -> str:
        """清洗平台消息前缀，保留买家真实语义。"""
        return (query or "").replace("内容：", "").replace("内容:", "").strip()

    ATTRIBUTE_SUB_INTENTS = {
        SubIntentType.USAGE_METHOD,
        SubIntentType.USAGE_DURATION,
        SubIntentType.AGE_SAFETY,
        SubIntentType.SKU_SPEC,
        SubIntentType.PRICE,
        SubIntentType.INGREDIENT,
        SubIntentType.FOAMING,
        SubIntentType.FRAGRANCE,
        SubIntentType.PRODUCT_ATTRIBUTE,
    }

    def _classify_sub_intent_detail(self, query: str) -> Dict[str, Any]:
        """Classify fine-grained product slots and keep explainable evidence."""
        if not self.SECONDARY_ROUTING_ENABLED:
            return {
                "sub_intent": SubIntentType.NONE,
                "confidence": 0.0,
                "matched_terms": [],
                "reason": "secondary_routing_disabled",
            }

        q = self._clean_user_query(query).lower()
        if not q:
            return {
                "sub_intent": SubIntentType.NONE,
                "confidence": 0.0,
                "matched_terms": [],
                "reason": "empty_query",
            }

        def has_any(terms: tuple[str, ...]) -> bool:
            return any(term in q for term in terms)

        def matched(terms: tuple[str, ...]) -> List[str]:
            return [term for term in terms if term in q]

        def result(sub_intent: str, terms: tuple[str, ...], confidence: float, reason: str) -> Dict[str, Any]:
            return {
                "sub_intent": sub_intent,
                "confidence": confidence,
                "matched_terms": matched(terms),
                "reason": reason,
            }

        logistics_terms = (
            "几天到", "多久到", "什么时候发货", "啥时候发货", "几天发货",
            "发货", "快递", "物流", "到货", "送到", "催发货",
        )
        usage_duration_terms = (
            "一瓶可以用几天", "一瓶能用几天", "一瓶用几天", "一瓶可以用多久",
            "一瓶能用多久", "一瓶用多久", "一支可以用几天", "一支能用多久",
            "一盒可以用几天", "一盒能用多久", "可以用几天", "能用几天",
            "用多久", "用多长时间", "几天用完", "能用几次", "可以用几次",
            "使用时长", "使用时间", "能使用多久", "可以使用多久", "用多长",
        )
        usage_method_terms = (
            "什么时候用", "啥时候用", "什么时间用", "怎么用", "如何用",
            "如何使用", "怎么使用", "使用方法", "用法",
            "早上用", "晚上用", "白天用", "白天能用", "一天几次", "喷哪里",
            "涂哪里", "敷多久", "怎么喷", "怎么涂", "怎么敷",
        )
        age_terms = (
            "岁", "小孩", "孩子", "儿童", "宝宝", "婴儿", "孕妇", "哺乳",
            "敏感肌", "学生", "老人", "青少年",
        )
        sku_terms = (
            "几片", "多少片", "几抽", "多少抽", "多大", "规格", "容量",
            "多少ml", "多少毫升", "几瓶", "几包", "几盒", "几个味道",
            "几种味", "哪些味", "什么味", "味道有哪些",
        )
        fragrance_terms = (
            "什么味", "什么味道", "是什么味", "味道", "香味", "最香",
            "香一点", "香味重", "味道重", "好闻", "哪种香",
            "哪个香", "哪款香", "留香久", "留香更久",
        )
        brand_terms = ("什么牌子", "啥牌子", "哪个牌子", "什么品牌", "啥品牌", "品牌", "牌子")
        price_terms = ("多少钱", "价格", "几块", "几元", "贵吗", "便宜吗", "优惠", "什么价", "啥价")
        ingredient_terms = ("成分", "含不含", "有没有酒精", "酒精", "香精", "材质")
        foaming_terms = (
            "起泡", "泡沫", "气泡", "泡泡", "绵密", "丰富吗", "泡多", "泡多吗",
        )
        discovery_terms = (
            "推荐", "有没有", "有吗", "有什么", "哪款", "哪种", "哪个",
            "想买", "想看", "换一款", "换一个", "便宜点", "类似",
        )

        if has_any(logistics_terms):
            return result(SubIntentType.LOGISTICS_DELIVERY, logistics_terms, 0.98, "logistics_strong_rule")
        if has_any(usage_duration_terms):
            return result(SubIntentType.USAGE_DURATION, usage_duration_terms, 0.96, "usage_duration_strong_rule")
        if has_any(usage_method_terms):
            return result(SubIntentType.USAGE_METHOD, usage_method_terms, 0.95, "usage_method_strong_rule")
        if has_any(foaming_terms):
            return result(SubIntentType.FOAMING, foaming_terms, 0.93, "foaming_strong_rule")
        if has_any(fragrance_terms):
            return result(SubIntentType.FRAGRANCE, fragrance_terms, 0.92, "fragrance_strong_rule")
        if has_any(sku_terms):
            return result(SubIntentType.SKU_SPEC, sku_terms, 0.92, "sku_spec_strong_rule")
        if has_any(price_terms):
            return result(SubIntentType.PRICE, price_terms, 0.94, "price_strong_rule")
        if has_any(ingredient_terms):
            return result(SubIntentType.INGREDIENT, ingredient_terms, 0.93, "ingredient_strong_rule")
        if has_any(brand_terms):
            return result(SubIntentType.PRODUCT_ATTRIBUTE, brand_terms, 0.9, "brand_strong_rule")
        if has_any(age_terms) and not has_any(usage_duration_terms + usage_method_terms):
            return result(SubIntentType.AGE_SAFETY, age_terms, 0.91, "age_safety_strong_rule")
        if has_any(discovery_terms):
            confidence = 0.86 if self._extract_route_product_terms(q) else 0.78
            return result(SubIntentType.PRODUCT_DISCOVERY, discovery_terms, confidence, "product_discovery_rule")
        if any(term in q for term in ("这款", "这个", "这支", "这瓶", "它")) and any(
            term in q for term in ("好吗", "好用", "怎么样", "如何", "适合", "刺激")
        ):
            return {
                "sub_intent": SubIntentType.PRODUCT_ATTRIBUTE,
                "confidence": 0.72,
                "matched_terms": matched(("这款", "这个", "这支", "这瓶", "它", "好用", "怎么样", "适合", "刺激")),
                "reason": "current_product_generic_attribute",
            }
        return {
            "sub_intent": SubIntentType.NONE,
            "confidence": 0.0,
            "matched_terms": [],
            "reason": "no_sub_intent_rule",
        }

    def _classify_sub_intent(self, query: str) -> str:
        """Compatibility wrapper for existing call sites."""
        return self._classify_sub_intent_detail(query).get("sub_intent", SubIntentType.NONE)

    def _product_memory_key(self, session_id: str) -> str:
        return f"{self.PRODUCT_MEMORY_PREFIX}{session_id}"

    def _resolve_retrieval_policy(
        self,
        *,
        query: str,
        intent: str,
        sub_intent: str,
        goods_id: Optional[str],
        product_memory: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resolve data source strategy after intent classification."""
        current_goods_id = goods_id or product_memory.get("goods_id")

        if intent in {IntentType.REDLINE, IntentType.AFTER_SALES, IntentType.LOGISTICS, IntentType.GENERAL}:
            scope = "shop" if intent != IntentType.GENERAL else "none"
            return {
                "retrieval_policy": RetrievalPolicy.SHOP_KNOWLEDGE,
                "locked_goods_id": str(current_goods_id) if current_goods_id else None,
                "entity_scope": scope,
            }

        if sub_intent in self.ATTRIBUTE_SUB_INTENTS:
            if current_goods_id:
                return {
                    "retrieval_policy": RetrievalPolicy.CURRENT_PRODUCT,
                    "locked_goods_id": str(current_goods_id),
                    "entity_scope": "current_product",
                }
            return {
                "retrieval_policy": RetrievalPolicy.CLARIFY_PRODUCT,
                "locked_goods_id": None,
                "entity_scope": "unknown",
            }

        if intent == IntentType.RECOMMEND or sub_intent in {SubIntentType.FRAGRANCE, SubIntentType.PRODUCT_DISCOVERY}:
            return {
                "retrieval_policy": RetrievalPolicy.PRODUCT_CANDIDATES,
                "locked_goods_id": str(current_goods_id) if current_goods_id else None,
                "entity_scope": "product_candidates",
            }

        if self._is_product_followup_query(query) and current_goods_id:
            return {
                "retrieval_policy": RetrievalPolicy.CURRENT_PRODUCT,
                "locked_goods_id": str(current_goods_id),
                "entity_scope": "current_product",
            }

        if intent == IntentType.PRE_SALE:
            if current_goods_id:
                return {
                    "retrieval_policy": RetrievalPolicy.CURRENT_PRODUCT,
                    "locked_goods_id": str(current_goods_id),
                    "entity_scope": "current_product",
                }
            return {
                "retrieval_policy": RetrievalPolicy.CLARIFY_PRODUCT,
                "locked_goods_id": str(current_goods_id) if current_goods_id else None,
                "entity_scope": "unknown",
            }

        return {
            "retrieval_policy": RetrievalPolicy.NONE,
            "locked_goods_id": str(current_goods_id) if current_goods_id else None,
            "entity_scope": "unknown",
        }

    def _ensure_retrieval_policy(self, state: CustomerServiceState) -> CustomerServiceState:
        """Attach retrieval policy for any router branch, including early returns."""
        if state.get("retrieval_policy") and state.get("retrieval_policy") != RetrievalPolicy.NONE:
            return state

        session_id = state.get("session_id", "")
        clean_query = self._clean_user_query(state.get("user_query", ""))
        product_memory = self._get_product_memory(session_id)
        detail = self._classify_sub_intent_detail(clean_query)
        policy = self._resolve_retrieval_policy(
            query=clean_query,
            intent=state.get("current_intent", IntentType.UNKNOWN),
            sub_intent=state.get("sub_intent") or detail["sub_intent"],
            goods_id=state.get("locked_goods_id"),
            product_memory=product_memory,
        )
        enriched = {
            **state,
            "sub_intent": state.get("sub_intent") or detail["sub_intent"],
            "sub_intent_confidence": state.get("sub_intent_confidence", detail["confidence"]),
            "sub_intent_terms": state.get("sub_intent_terms", detail["matched_terms"]),
            "retrieval_policy": policy["retrieval_policy"],
            "entity_scope": policy["entity_scope"],
        }
        if policy["locked_goods_id"]:
            enriched["locked_goods_id"] = policy["locked_goods_id"]
        return enriched

    def _get_product_memory(self, session_id: str) -> Dict[str, Any]:
        """读取最近一次推荐/锁定商品，用于“这个/这一包/能用吗”等追问。"""
        if not session_id:
            return {}

        try:
            from database.redis_manager import redis_manager

            client = getattr(redis_manager, "_client", None)
            if client is not None:
                raw = client.get(self._product_memory_key(session_id))
                if raw:
                    import json
                    return json.loads(raw)
        except Exception as e:
            logger.debug(f"[ProductMemory] Redis 读取失败，使用本地缓存: {e}")

        return self._product_memory_cache.get(session_id, {})

    def _set_product_memory(self, session_id: str, memory: Dict[str, Any]) -> None:
        """记录最近推荐商品。Redis 不可用时退回进程内缓存。"""
        if not session_id or not memory:
            return

        safe_memory = {
            "goods_id": memory.get("goods_id"),
            "goods_name": memory.get("goods_name"),
            "price": memory.get("price"),
            "selected_sku": memory.get("selected_sku"),
            "skus": memory.get("skus", [])[:8],
            "keywords": memory.get("keywords", []),
            "candidates": memory.get("candidates", [])[:5],
        }
        self._product_memory_cache[session_id] = safe_memory

        try:
            import json
            from database.redis_manager import redis_manager

            client = getattr(redis_manager, "_client", None)
            if client is not None:
                client.setex(
                    self._product_memory_key(session_id),
                    self.PRODUCT_MEMORY_TTL,
                    json.dumps(safe_memory, ensure_ascii=False),
                )
        except Exception as e:
            logger.debug(f"[ProductMemory] Redis 写入失败，仅使用本地缓存: {e}")

    def _is_product_followup_query(self, query: str) -> bool:
        """识别商品追问，避免重新推荐 TopN 导致上下文漂移。"""
        q = self._clean_user_query(query)
        if not q:
            return False

        followup_terms = (
            "这个", "这款", "这包", "这一包", "这瓶", "它", "刚才", "上面",
            "现在说", "刚才说", "说的什么", "什么产品", "是哪款", "是哪个产品",
            "多少片", "几片", "多少抽", "几抽", "多少ml", "多少毫升", "容量",
            "规格", "款式", "价格", "多少钱", "几包", "几瓶",
            "能用", "可以用", "适合", "婴儿", "宝宝", "儿童", "孕妇", "敏感肌",
            "成分", "材质", "保质期", "怎么用", "怎么喷", "留香", "味道",
            "品牌", "牌子", "什么品牌", "什么牌子", "啥品牌", "啥牌子",
            "黄皮", "黑皮", "白皮", "肤色", "肤质", "油皮", "干皮", "混油皮",
        )
        return any(term in q for term in followup_terms)

    def _is_skin_type_query(self, query: str) -> bool:
        """识别肤质/肤色适配问题，避免被“能用”泛词误判为年龄安全。"""
        q = self._clean_user_query(query)
        skin_terms = (
            "黄皮", "黑皮", "白皮", "冷白皮", "暖皮", "肤色", "肤质",
            "油皮", "干皮", "混油皮", "混干皮", "敏感肌", "痘肌",
        )
        return any(term in q for term in skin_terms)

    def _is_age_safety_query(self, query: str) -> bool:
        """只在明确年龄/人群词出现时回答适用年龄。"""
        q = self._clean_user_query(query)
        age_terms = (
            "几岁", "多少岁", "多大能用", "年龄", "适用年龄",
            "小孩", "孩子", "儿童", "宝宝", "婴儿", "孕妇", "哺乳", "青少年",
        )
        if any(term in q for term in age_terms):
            return True
        return bool(re.search(r"[一二三四五六七八九十\d]+\s*岁", q))

    def _resolve_product_slot(self, query: str) -> str:
        """把当前商品追问解析到结构化字段，避免把事实判断交给 LLM 或泛关键词。"""
        q = self._clean_user_query(query)
        if not q:
            return ""

        def has_any(terms: tuple[str, ...]) -> bool:
            return any(term in q for term in terms)

        if has_any(("什么牌子", "啥牌子", "哪个牌子", "什么品牌", "啥品牌", "品牌", "牌子")):
            return "brand"
        if self._is_skin_type_query(q):
            return "skin_type"
        if self._is_age_safety_query(q):
            return "suitable_age"
        if has_any(("一瓶可以用几天", "一瓶能用几天", "一瓶可以用多久", "一支可以用多久", "用多久", "使用时长", "能使用多久", "可以使用多久")):
            return "usage_duration"
        if has_any(("什么时候用", "啥时候用", "怎么用", "如何使用", "使用方法", "用法", "喷哪里", "涂哪里", "怎么喷", "怎么涂")):
            return "usage_method"
        if has_any(("起泡", "泡沫", "泡泡", "绵密", "泡多吗")):
            return "foaming"
        if has_any(("成分", "含不含", "有没有酒精", "酒精", "香精", "材质")):
            return "ingredients"
        if has_any(("什么味", "什么味道", "是什么味", "味道", "香味", "好闻", "留香")):
            return "fragrance"
        if has_any(("规格", "款式", "几瓶", "几支", "几包", "多少ml", "多少毫升", "容量")):
            return "sku_options"
        if has_any(("多少钱", "价格", "几块", "几元", "什么价", "啥价")):
            return "price"
        return ""

    def _build_product_slot_reply(
        self,
        slot: str,
        query: str,
        knowledge: str,
        rules: Dict[str, Any],
    ) -> Optional[str]:
        """从已注入的当前商品结构化上下文直接回答事实字段。"""
        if not slot:
            return None

        price = self._extract_context_value(knowledge, "价格")
        sku = self._first_context_sku(knowledge)

        if slot == "brand":
            brand = self._extract_context_value(knowledge, "品牌")
            return f"这款品牌是{brand}。" if brand else "页面没有明确标注品牌信息，建议以详情页说明为准哦。"

        if slot == "skin_type":
            skin_type = self._extract_context_value(knowledge, "适用肤质")
            effect = self._extract_context_value(knowledge, "功效").rstrip("。.!！")
            if skin_type and effect:
                return f"这款标注的是{skin_type}，主要卖点是{effect}。"
            if skin_type:
                return f"这款标注的是{skin_type}，建议按页面说明使用哦。"
            if effect:
                return f"页面没有单独标注适用肤质，当前卖点是{effect}，建议按页面说明选择哦。"
            return "页面没有明确标注适用肤质，建议以详情页说明为准哦。"

        if slot == "suitable_age":
            age = self._extract_age_hint(knowledge)
            if age:
                template = rules.get("child_known_age_reply_template") or "这款适用年龄是{age}，建议按页面说明使用哦。"
                return template.replace("{age}", age)
            return rules.get("child_unknown_age_reply")

        if slot == "usage_duration":
            duration = self._extract_context_value(knowledge, "使用时长")
            return f"这款使用时长参考：{duration}。" if duration else "这款页面暂时没有明确标注一瓶可用多久，具体会和每次用量有关，建议按页面规格参考哦。"

        if slot == "usage_method":
            usage = self._extract_context_value(knowledge, "使用方法")
            return f"这款使用方法是：{usage}。" if usage else "这款按页面使用说明操作即可，具体使用时间和频次以下单页说明为准哦。"

        if slot == "foaming":
            foaming = self._extract_context_value(knowledge, "起泡情况")
            return f"这款起泡情况是：{foaming}。" if foaming else "页面没有明确标注起泡情况，建议以详情页实际说明为准哦。"

        if slot == "ingredients":
            ingredients = self._extract_context_value(knowledge, "成分/材质")
            return f"这款成分信息是：{ingredients}。" if ingredients else "页面没有明确标注完整成分，建议以详情页说明为准哦。"

        if slot == "fragrance":
            fragrance = self._extract_context_value(knowledge, "香味")
            return f"这款是{fragrance}味的。" if fragrance else "页面没有明确标注具体香味，建议以详情页说明为准哦。"

        if slot == "sku_options":
            sku_options = self._context_sku_options(knowledge, limit=8)
            if sku_options:
                options_text = "、".join(sku_options)
                if any(term in self._clean_user_query(query) for term in ("合适", "推荐", "买几", "选几")):
                    return f"这款有{options_text}可选。第一次用可以先选{sku_options[0]}，想多囤一点可以选后面的多瓶规格。"
                return f"这款可选规格有：{options_text}。"
            return f"这款规格是{self._clean_sku_for_reply(sku)}。" if sku else "页面没有明确标注规格信息，建议以详情页说明为准哦。"

        if slot == "price":
            q = self._clean_user_query(query)
            if any(term in q for term in ("2瓶", "3瓶", "多瓶", "几瓶", "套装")):
                return f"这款价格区间是{price}，多瓶组合价以下单页为准哦。" if price else "多瓶组合价以下单页为准哦。"
            return f"这款价格是{price}，具体以下单页为准哦。" if price else "价格以下单页为准哦。"

        return None

    def _is_context_identity_query(self, query: str) -> bool:
        """识别“现在说的是哪款”这类商品上下文确认。"""
        q = self._clean_user_query(query)
        identity_terms = (
            "现在说", "刚才说", "说的什么", "什么产品", "是哪款", "是哪个产品",
            "是哪款", "是哪个", "你说的是",
        )
        return any(term in q for term in identity_terms)

    def _is_relative_product_choice_query(self, query: str) -> bool:
        """识别应限定在上一轮候选集内重排的相对导购表达。"""
        q = self._clean_user_query(query)
        relative_terms = (
            "便宜", "贵点", "贵一点", "便宜点", "便宜一点",
            "换一款", "换一个", "换个", "别的", "其他", "还有吗", "还有没有",
            "同类", "类似", "差不多",
        )
        return any(term in q for term in relative_terms)

    def _is_contextual_recommend_query(self, query: str) -> bool:
        """识别“推荐哪种/哪种最香”这类应沿用上一轮品类的泛推荐。"""
        q = self._clean_user_query(query)
        contextual_terms = (
            "推荐哪", "推荐一", "推荐个", "推荐款", "哪种", "哪款", "哪个",
            "哪个好", "最香", "香一点", "味道", "香味", "好闻",
        )
        return any(term in q for term in contextual_terms)

    def _is_general_chat_query(self, query: str) -> bool:
        """识别不应进入商品/售后链路的闲聊或身份类短问。"""
        q = self._clean_user_query(query)
        general_terms = (
            "真人吗", "你是真人", "人工吗", "有人吗", "在吗", "在不在",
            "说话", "回话", "理我", "有人回复吗",
        )
        return any(term in q for term in general_terms)

    def _is_short_default_query(self, query: str) -> bool:
        """识别无业务信息的短句，避免继承上一轮商品/售后/物流意图。"""
        import re

        q = self._clean_user_query(query).strip().lower()
        compact = re.sub(r"\s+", "", q)
        if not compact:
            return True

        default_phrases = set(self._reply_rules().get("short_default_phrases") or [])
        if compact in default_phrases:
            return True

        return len(compact) <= 2 and not self._extract_route_product_terms(compact)

    def _reply_rules(self) -> Dict[str, Any]:
        """读取 PyQt 可配置的一级拦截和固定话术规则。"""
        try:
            from core.config_manager import config_manager

            return config_manager.get_agent_reply_rules("default")
        except Exception as e:
            logger.debug(f"[Rules] 加载一级拦截话术配置失败，使用默认值: {e}")
            return {
                "general_reply": "在的，您想咨询哪方面呢？",
                "unknown_reply": "您想看哪类产品？香氛、湿敷棉、洗脸巾都可以说一下。",
                "logistics_reply": "正常48小时内发货，具体到达以物流为准哦。",
                "no_product_match_reply": "暂时没找到完全对应的款式，可以换个关键词我再帮您看～",
                "child_known_age_reply_template": "这款适用年龄是{age}，建议按页面说明使用哦。",
                "child_unknown_age_reply": "商品信息里没有明确标注儿童适用，建议先按页面说明确认后再用哦。",
                "short_default_phrases": [
                    "?", "？", "??", "？？", "???", "？？？",
                    "嗯", "嗯嗯", "哦", "哦哦", "噢", "噢噢", "啊", "啊？", "啊?",
                    "好", "好的", "好吧", "行", "行吧", "可以", "可以吧",
                    "ok", "okk", "okay", "嗯好", "知道了", "明白了",
                    "在吗", "在不在", "有人吗", "说话", "回话", "理我",
                ],
                "child_age_terms": [
                    "岁", "12岁", "十二岁", "小孩", "孩子", "婴儿", "宝宝",
                    "儿童", "孕妇",
                ],
            }

    def _route_keywords(self) -> Dict[str, set]:
        """读取 PyQt 可配置的路由关键词。"""
        try:
            from core.config_manager import config_manager

            data = config_manager.get_route_keywords("default")
            return {
                "redline": set(data.get("redline") or REDLINE_KEYWORDS),
                "human_request": set(data.get("human_request") or HUMAN_REQUEST_KEYWORDS),
                "after_sales": set(data.get("after_sales") or AFTER_SALES_KEYWORDS),
                "pre_sale": set(data.get("pre_sale") or PRE_SALE_KEYWORDS),
                "recommend": set(data.get("recommend") or RECOMMEND_KEYWORDS),
                "logistics": set(data.get("logistics") or LOGISTICS_KEYWORDS),
            }
        except Exception as e:
            logger.debug(f"[Router] 加载路由关键词配置失败，使用默认值: {e}")
            return {
                "redline": set(REDLINE_KEYWORDS),
                "human_request": set(HUMAN_REQUEST_KEYWORDS),
                "after_sales": set(AFTER_SALES_KEYWORDS),
                "pre_sale": set(PRE_SALE_KEYWORDS),
                "recommend": set(RECOMMEND_KEYWORDS),
                "logistics": set(LOGISTICS_KEYWORDS),
            }

    def _extract_query_keywords(self, query: str, known_terms: Optional[List[str]] = None) -> List[str]:
        """提取商品检索关键词，过滤导购口水词。"""
        try:
            from database.product_terms import extract_query_terms

            return extract_query_terms(self._clean_user_query(query), known_terms=known_terms or [])
        except Exception as e:
            logger.debug(f"[Retriever] 商品词典分词失败，降级为空关键词: {e}")
            return []

    def _extract_route_product_terms(self, query: str) -> List[str]:
        """只提取强商品词，用于路由，不使用泛化分词。"""
        try:
            from database.product_terms import extract_route_product_terms

            return extract_route_product_terms(self._clean_user_query(query))
        except Exception as e:
            logger.debug(f"[Router] 商品路由词提取失败: {e}")
            return []

    def _filter_product_candidate_keywords(self, keywords: List[str]) -> List[str]:
        """Remove attribute/coreference terms from product candidate recall."""
        blocked_terms = {
            "使用", "时长", "多久", "几天", "能用", "可以用", "使用时长",
            "起泡", "泡沫", "气泡", "泡泡", "怎么用", "什么时候用",
            "成分", "酒精", "香精", "适合", "肤质", "这款", "这个",
            "这支", "这瓶", "它", "刚才", "上面", "有吗", "多吗",
        }
        filtered: List[str] = []
        for keyword in keywords:
            normalized = str(keyword or "").strip().lower()
            if not normalized or normalized in blocked_terms:
                continue
            if normalized not in filtered:
                filtered.append(normalized)
        return filtered

    def _load_json_dict(self, raw: Any) -> Dict[str, Any]:
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            import json
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _is_negative_product_feedback(self, query: str) -> bool:
        q = self._clean_user_query(query)
        product_terms = self._extract_route_product_terms(q)
        negative_terms = (
            "不好闻", "不是很好闻", "难闻", "不喜欢", "不满意", "不好", "买错",
            "没效果", "没有效果", "没用", "没有用", "没味道", "没有味道",
            "不持久", "留香短", "留香太短", "几分钟就没", "一会儿就没",
            "效果差", "没什么效果",
        )
        return bool(product_terms) and any(term in q for term in negative_terms)

    def _is_explicit_after_sales_query(self, query: str) -> bool:
        """识别不应被短句继承/商品词典覆盖的明确售后表达。"""
        q = self._clean_user_query(query)
        if not q:
            return False

        direct_terms = (
            "买错", "拍错", "下错", "退款", "退货", "换货", "售后",
            "申请退", "申请退款", "申请售后",
            "坏了", "破损", "破了", "漏液", "漏了", "少发", "错发", "发错",
            "没效果", "没有效果", "没用", "没有用", "没味道", "没有味道",
            "不持久", "留香短", "留香太短", "几分钟就没", "一会儿就没",
            "效果差", "没什么效果",
        )
        if any(term in q for term in direct_terms):
            return True

        complaint_terms = (
            "不好闻", "不是很好闻", "难闻", "不喜欢", "不满意",
            "没效果", "没有效果", "没用", "没有用", "没味道", "没有味道",
            "不持久", "留香短", "留香太短", "几分钟就没", "一会儿就没",
            "效果差", "没什么效果",
        )
        pre_sale_uncertainty = ("会不会", "怕", "担心", "容易", "吗", "嘛", "么")
        return any(term in q for term in complaint_terms) and not any(
            term in q for term in pre_sale_uncertainty
        )

    def _resolve_db_shop_id(self, session, shop_id: Any) -> Any:
        """兼容原始店铺 ID 与数据库内部 shops.id。"""
        from database.models import Shop
        from sqlalchemy import select

        try:
            stmt = select(Shop).where(Shop.shop_id == str(shop_id))
            shop = session.scalar(stmt)
            if shop:
                return shop.id
        except Exception as e:
            logger.debug(f"[Retriever] 店铺ID解析失败，使用原值: {e}")
        return shop_id

    def _parse_product_specs(self, specs_raw: Any) -> Dict[str, List[str]]:
        """把 specifications 拆成真实 SKU 与类目，避免把商品分类当规格推荐。"""
        import json

        if not specs_raw:
            return {"skus": [], "categories": []}

        specs: Any = specs_raw
        if isinstance(specs_raw, str):
            try:
                specs = json.loads(specs_raw)
            except json.JSONDecodeError:
                specs = specs_raw

        raw_items: List[str] = []
        if isinstance(specs, list):
            for item in specs:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("款式") or item.get("spec") or ""
                    price = item.get("price") or item.get("价格")
                    desc = item.get("desc") or item.get("描述") or ""
                    text = str(name).strip()
                    if price:
                        text = f"{text}，价格: {price}"
                    if desc:
                        text = f"{text}，特点: {desc}"
                    raw_items.append(text)
                else:
                    raw_items.append(str(item).strip())
        elif isinstance(specs, dict):
            for name, detail in specs.items():
                if isinstance(detail, dict):
                    price = detail.get("price") or detail.get("价格")
                    desc = detail.get("desc") or detail.get("描述") or ""
                    text = str(name).strip()
                    if price:
                        text = f"{text}，价格: {price}"
                    if desc:
                        text = f"{text}，特点: {desc}"
                    raw_items.append(text)
                else:
                    raw_items.append(f"{name}: {detail}".strip())
        else:
            raw_items = [x.strip() for x in str(specs).replace("、", "/").split("/") if x.strip()]

        skus: List[str] = []
        categories: List[str] = []
        for item in raw_items:
            if not item:
                continue
            normalized = item.strip()
            if normalized.startswith("商品分类") or "商品分类:" in normalized or "商品分类：" in normalized:
                categories.append(normalized)
                continue
            if normalized.startswith("款式:") or normalized.startswith("款式："):
                normalized = normalized.split(":", 1)[-1].strip() if ":" in normalized else normalized.split("：", 1)[-1].strip()
            if normalized and normalized not in skus:
                skus.append(normalized)

        return {"skus": skus, "categories": categories}

    def _score_product_candidate(self, product: Any, keywords: List[str], parsed_specs: Dict[str, List[str]]) -> float:
        """商品候选重排：商品名/SKU 权重大，类目命中权重极低。"""
        import math

        name = product.goods_name or ""
        content = product.extracted_content or ""
        content = "\n".join(
            line for line in content.splitlines()
            if "商品分类" not in line
        )
        sku_text = " ".join(parsed_specs.get("skus", []))
        category_text = " ".join(parsed_specs.get("categories", []))

        relevance_score = 0.0
        for kw in keywords:
            if kw in name:
                relevance_score += 80
            if kw in sku_text:
                relevance_score += 55
            if kw in content:
                relevance_score += 18
            if kw in category_text:
                relevance_score += 2

        if keywords and relevance_score < 10:
            return 0.0

        sold = product.sold_quantity or 0
        return relevance_score + min(math.log10(max(sold, 0) + 1) * 3, 15)

    def _build_no_product_match_context(self, keywords: List[str]) -> str:
        keyword_text = "、".join(keywords) if keywords else "当前需求"
        return (
            f"【精准推荐库】：未找到与“{keyword_text}”明确匹配的商品。"
            "请回复买家：暂时没找到完全对应的款式，可以换个关键词或看看店内其他在售款；"
            "严禁编造商品名、商品ID、SKU 或价格。"
        )

    def _extract_context_value(self, knowledge: str, label: str) -> str:
        import re

        match = re.search(rf"{label}:\s*(.+)", knowledge)
        return match.group(1).strip() if match else ""

    def _extract_age_hint(self, knowledge: str) -> str:
        import re

        age = self._extract_context_value(knowledge, "适用年龄")
        if age:
            return age

        age = self._extract_context_value(knowledge, r"\*\*适用年龄\*\*")
        if age:
            return age

        patterns = (
            r"([一二三四五六七八九十\d]+岁以上[^。\n，,；;]*?(?:能用|可用|适用|使用))",
            r"([一二三四五六七八九十\d]+岁(?:以上|以下|左右)?[^。\n，,；;]*?(?:能用|可用|适用|使用))",
        )
        for pattern in patterns:
            match = re.search(pattern, knowledge)
            if match:
                return match.group(1).strip()
        return ""

    def _first_context_sku(self, knowledge: str) -> str:
        import re

        match = re.search(r"- \[SKU\d+\]\s*(.+)", knowledge)
        if match:
            return match.group(1).strip()
        return self._extract_context_value(knowledge, "规格")

    def _context_skus(self, knowledge: str, limit: int = 5) -> List[str]:
        import re

        skus = []
        for match in re.finditer(r"- \[SKU\d+\]\s*(.+)", knowledge):
            sku = self._clean_sku_for_reply(match.group(1).strip())
            if sku and sku not in skus:
                skus.append(sku)
            if len(skus) >= limit:
                break
        return skus

    def _context_sku_options(self, knowledge: str, limit: int = 8) -> List[str]:
        import re

        options = self._context_skus(knowledge, limit=limit)
        for label in ("可选规格", "规格"):
            value = self._extract_context_value(knowledge, label)
            if not value:
                continue
            for item in re.split(r"[、,，;；/]+", value):
                sku = self._clean_sku_for_reply(item)
                if sku and sku not in options:
                    options.append(sku)
                if len(options) >= limit:
                    return options
        return options

    def _taste_names_from_skus(self, skus: List[str]) -> tuple[List[str], bool]:
        import re

        taste_names = []
        has_combo = False
        combo_marks = ("+", "＋", "组合", "套装", "2盒", "两件", "三件")

        for sku in skus:
            if any(mark in sku for mark in combo_marks):
                has_combo = True
                continue

            match = re.search(r"【([^】]+)】", sku)
            name = match.group(1).strip() if match else sku
            name = re.sub(r"[*xX×]\s*\d+.*$", "", name).strip()
            name = re.sub(r"\d+\s*(瓶|盒|支|ml|ML|g|G).*$", "", name).strip()
            if name and name not in taste_names:
                taste_names.append(name)

        return taste_names, has_combo

    def _preferred_fragrance_advice(self, taste_names: List[str], query: str) -> str:
        q = self._clean_user_query(query)
        if not taste_names:
            return ""

        preferred = ""
        for candidate in ("茉莉花香", "茉莉", "栀子花", "纯栀子花"):
            for name in taste_names:
                if candidate in name:
                    preferred = name
                    break
            if preferred:
                break

        if not preferred:
            preferred = taste_names[0]

        if any(term in q for term in ("最香", "香一点", "香味重", "浓一点", "好闻")):
            alternatives = [name for name in taste_names if name != preferred]
            if alternatives:
                return f"想要香味明显一点，可以优先看{preferred}；喜欢清爽不冲的可以看{alternatives[0]}。"
            return f"想要香味明显一点，可以优先看{preferred}。"

        return ""

    def _clean_sku_for_reply(self, sku: str) -> str:
        import re

        text = (sku or "").strip()
        text = re.sub(r"^\d+%选择[:：]\s*", "", text)
        text = text.replace("【", "").replace("】", "")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _compact_goods_name(self, goods_name: str, max_len: int = 18) -> str:
        goods_name = (goods_name or "").strip()
        return goods_name if len(goods_name) <= max_len else f"{goods_name[:max_len]}..."

    def _parse_price_floor(self, price: Any) -> float:
        import re

        values = re.findall(r"\d+(?:\.\d+)?", str(price or ""))
        return float(values[0]) if values else 0.0

    def _select_sku_for_keywords(self, skus: List[str], keywords: List[str]) -> str:
        if not skus:
            return "标准款"

        if "套装" in keywords:
            for sku in skus:
                if "全套" in sku:
                    return sku
            for sku in skus:
                if "盒" in sku:
                    return sku

        for keyword in keywords:
            for sku in skus:
                if keyword and keyword in sku:
                    return sku

        return skus[0]

    def _build_deterministic_product_reply(self, intent: str, query: str, knowledge: str) -> Optional[str]:
        """商品推荐/追问场景优先走模板，避免模型输出商品ID、伪价格和伪SKU。"""
        clean_query = self._clean_user_query(query)
        rules = self._reply_rules()
        sub_intent = self._classify_sub_intent(clean_query)

        if intent == IntentType.GENERAL:
            return rules.get("general_reply")

        if intent == IntentType.UNKNOWN:
            return rules.get("unknown_reply")

        if intent == IntentType.LOGISTICS:
            return rules.get("logistics_reply")

        if "【澄清提示】" in knowledge:
            if sub_intent in self.ATTRIBUTE_SUB_INTENTS:
                return "您问的是哪款商品呢？发我一下商品页，我好按这款帮您确认。"
            return "您可以再具体说一下想了解哪款商品。"

        if intent == IntentType.AFTER_SALES:
            if clean_query in {"？", "?", "怎么办", "怎么处理", "咋办"}:
                return "您别着急，具体问题您直接说，我这边帮您处理。"
            if any(term in clean_query for term in ("买错", "退", "退款", "退货", "换货")):
                return "没关系，您可以在订单里申请售后，我这边会协助处理。"
            if any(term in clean_query for term in ("不好闻", "不是很好闻", "难闻", "不喜欢", "不满意")):
                return "抱歉没让您满意，香味感受因人而异，您可以先申请售后我帮您看看。"
            if any(term in clean_query for term in ("漏", "破", "坏", "少发", "错发")):
                return "抱歉给您添麻烦了，麻烦发下照片，我帮您核实处理。"

        if "未找到与" in knowledge or knowledge == "未找到相关知识":
            return rules.get("no_product_match_reply")

        if "【精准推荐库】" in knowledge and intent in [IntentType.RECOMMEND, IntentType.PRE_SALE]:
            if any(term in clean_query for term in ("几种味", "几款味", "什么味道", "哪些味", "香味")):
                skus = self._context_skus(knowledge, limit=6)
                taste_names, has_combo = self._taste_names_from_skus(skus)
                if taste_names:
                    suffix = "，另有组合装。" if has_combo else "。"
                    return f"这款有{len(taste_names)}种味道：{'、'.join(taste_names)}{suffix}"
            if any(term in clean_query for term in ("最香", "香一点", "香味重", "浓一点", "好闻")):
                skus = self._context_skus(knowledge, limit=8)
                taste_names, _ = self._taste_names_from_skus(skus)
                advice = self._preferred_fragrance_advice(taste_names, clean_query)
                if advice:
                    return advice
            goods_name = self._extract_context_value(knowledge, "商品名称")
            price = self._extract_context_value(knowledge, "价格")
            sku = self._first_context_sku(knowledge)
            if goods_name and sku:
                price_text = f"，价格{price}" if price else ""
                return f"推荐这款：{self._compact_goods_name(goods_name)}，{self._clean_sku_for_reply(sku)}{price_text}。"

        if "【锁定商品库】" in knowledge:
            goods_name = self._extract_context_value(knowledge, "商品名称")
            price = self._extract_context_value(knowledge, "价格")
            sku = self._first_context_sku(knowledge)
            slot_reply = self._build_product_slot_reply(
                self._resolve_product_slot(clean_query),
                clean_query,
                knowledge,
                rules,
            )
            if slot_reply:
                return slot_reply
            if sub_intent == SubIntentType.USAGE_DURATION:
                duration = self._extract_context_value(knowledge, "使用时长")
                if duration:
                    return f"这款使用时长参考：{duration}。"
                return "这款页面暂时没有明确标注一瓶可用多久，具体会和每次用量有关，建议按页面规格参考哦。"
            if sub_intent == SubIntentType.USAGE_METHOD:
                usage = self._extract_context_value(knowledge, "使用方法")
                if usage:
                    return f"这款使用方法是：{usage}。"
                return "这款按页面使用说明操作即可，具体使用时间和频次以下单页说明为准哦。"
            if sub_intent == SubIntentType.FOAMING:
                foaming = self._extract_context_value(knowledge, "起泡情况")
                if foaming:
                    return f"这款起泡情况是：{foaming}。"
                return "页面没有明确标注起泡情况，建议以详情页实际说明为准哦。"
            if sub_intent == SubIntentType.INGREDIENT:
                ingredients = self._extract_context_value(knowledge, "成分/材质")
                if ingredients:
                    return f"这款成分信息是：{ingredients}。"
                return "页面没有明确标注完整成分，建议以详情页说明为准哦。"
            if sub_intent == SubIntentType.FRAGRANCE:
                fragrance = self._extract_context_value(knowledge, "香味")
                if fragrance:
                    return f"这款是{fragrance}味的。"
                return "页面没有明确标注具体香味，建议以详情页说明为准哦。"
            if any(term in clean_query for term in ("什么牌子", "啥牌子", "哪个牌子", "什么品牌", "啥品牌", "品牌", "牌子")):
                brand = self._extract_context_value(knowledge, "品牌")
                if brand:
                    return f"这款品牌是{brand}。"
                return "页面没有明确标注品牌信息，建议以详情页说明为准哦。"
            if self._is_skin_type_query(clean_query):
                skin_type = self._extract_context_value(knowledge, "适用肤质")
                effect = self._extract_context_value(knowledge, "功效").rstrip("。.!！")
                if skin_type and effect:
                    return f"这款标注的是{skin_type}，主要卖点是{effect}。"
                if skin_type:
                    return f"这款标注的是{skin_type}，建议按页面说明使用哦。"
                if effect:
                    return f"页面没有单独标注适用肤质，当前卖点是{effect}，建议按页面说明选择哦。"
                return "页面没有明确标注适用肤质，建议以详情页说明为准哦。"
            if self._is_context_identity_query(clean_query):
                if goods_name and sku:
                    return f"现在说的是这款：{self._compact_goods_name(goods_name)}，{self._clean_sku_for_reply(sku)}。"
                if goods_name:
                    return f"现在说的是这款：{self._compact_goods_name(goods_name)}。"
            if any(term in clean_query for term in ("多少钱", "价格", "几钱")):
                if any(term in clean_query for term in ("2瓶", "3瓶", "多瓶", "几瓶", "套装")):
                    return f"这款价格区间是{price}，多瓶组合价以下单页为准哦。" if price else "多瓶组合价以下单页为准哦。"
                return f"这款价格是{price}，具体以下单页为准哦。" if price else "价格以下单页为准哦。"
            if (
                sub_intent == SubIntentType.SKU_SPEC
                or any(term in clean_query for term in ("几片", "多少片", "几抽", "多少抽", "规格"))
            ):
                sku_options = self._context_sku_options(knowledge, limit=8)
                if sku_options:
                    options_text = "、".join(sku_options)
                    if any(term in clean_query for term in ("合适", "推荐", "买几", "选几")):
                        return f"这款有{options_text}可选。第一次用可以先选{sku_options[0]}，想多囤一点可以选后面的多瓶规格。"
                    return f"这款可选规格有：{options_text}。"
                if not sku:
                    return "页面没有明确标注规格信息，建议以详情页说明为准哦。"
                return f"这款规格是{self._clean_sku_for_reply(sku)}。"
            if self._is_age_safety_query(clean_query):
                age = self._extract_age_hint(knowledge)
                if age:
                    template = rules.get("child_known_age_reply_template") or "这款适用年龄是{age}，建议按页面说明使用哦。"
                    return template.replace("{age}", age)
                return rules.get("child_unknown_age_reply")

        return None

    def _sanitize_generated_response(self, response: str, knowledge: str) -> str:
        """清理模型泄漏给买家的内部字段。"""
        import re

        text = (response or "").strip()
        text = re.sub(r"商品ID[:：]?\s*\d+", "", text)
        text = re.sub(r"\[SKU\d+\]\s*", "", text)
        text = re.sub(r"编号[:：]?\s*\d+", "", text)
        text = re.sub(r"真实SKU[:：]?\s*[A-Za-z0-9_-]+", "", text)
        text = re.sub(r"\s+", " ", text).strip(" ，,。")

        if "未找到与" in knowledge and any(term in text for term in ("编号", "商品ID", "SKU")):
            return "暂时没找到完全对应的款式，可以换个关键词我再帮您看～"

        return text or "抱歉，我暂时无法回复。"

    def _format_memory_candidates_context(
        self,
        memory: Dict[str, Any],
        query: str,
        session_id: str = "",
    ) -> str:
        """把上一轮候选集重排为推荐上下文，避免“便宜点/换一款”全店乱跳。"""
        candidates = list(memory.get("candidates") or [])
        if not candidates and memory.get("goods_id"):
            candidates = [memory]
        if not candidates:
            return self._build_no_product_match_context([])

        q = self._clean_user_query(query)
        current_goods_id = memory.get("goods_id")
        current_price = self._parse_price_floor(memory.get("price"))

        def candidate_price(item: Dict[str, Any]) -> float:
            return self._parse_price_floor(item.get("price"))

        ordered = candidates
        if "便宜" in q:
            cheaper = [
                item for item in candidates
                if item.get("goods_id") != current_goods_id
                and candidate_price(item) > 0
                and (not current_price or candidate_price(item) <= current_price)
            ]
            ordered = sorted(cheaper or candidates, key=candidate_price)
        elif any(term in q for term in ("贵点", "贵一点")):
            pricier = [
                item for item in candidates
                if item.get("goods_id") != current_goods_id
                and candidate_price(item) >= current_price
            ]
            ordered = sorted(pricier or candidates, key=candidate_price, reverse=True)
        elif any(term in q for term in ("换一款", "换一个", "换个", "别的", "其他")):
            ordered = [item for item in candidates if item.get("goods_id") != current_goods_id] or candidates

        lines = ["【精准推荐库】以下为上一轮同类候选商品，必须限定在这些商品内推荐，严禁跨品类编造。"]
        memory_candidates = []
        for i, item in enumerate(ordered[:3], 1):
            goods_name = str(item.get("goods_name") or "")
            price = item.get("price") or "价格详询"
            skus = list(item.get("skus") or [])
            selected_sku = item.get("selected_sku") or (skus[0] if skus else "标准款")
            label = "推荐首选" if i == 1 else f"备选商品{i}"
            lines.extend([
                f"\n[{label}]",
                f"商品ID: {item.get('goods_id')}",
                f"商品名称: {goods_name}",
                f"价格: {price}",
                "可推荐SKU:",
                f"- [SKU1] {selected_sku}",
            ])
            if i == 1:
                extra_skus = [sku for sku in skus if sku and sku != selected_sku][:5]
                for sku_index, sku in enumerate(extra_skus, 2):
                    lines.append(f"- [SKU{sku_index}] {sku}")
            memory_candidates.append({
                "goods_id": item.get("goods_id"),
                "goods_name": goods_name,
                "price": price,
                "selected_sku": selected_sku,
                "skus": skus,
            })

        if memory_candidates:
            top = {
                **memory_candidates[0],
                "keywords": memory.get("keywords", []),
                "candidates": memory_candidates,
            }
            self._set_product_memory(session_id, top)
            logger.info(
                f"[ProductMemory] 基于上一轮候选重排: session_id={session_id}, "
                f"goods_id={top.get('goods_id')}, sku={top.get('selected_sku')}"
            )

        return "\n".join(lines)

    def _format_product_candidates_context(
        self,
        products: List[Any],
        keywords: List[str],
        session_id: str = "",
    ) -> str:
        """格式化推荐候选，并把首选商品写入会话记忆。"""
        if not products:
            return "【精准推荐库】：店铺暂无匹配商品，请引导客户关注店铺。"

        lines = ["【精准推荐库】以下均为数据库中的真实商品和真实规格，严禁编造未列出的 SKU。"]
        memory_candidates = []
        top_memory: Dict[str, Any] = {}

        for i, product in enumerate(products, 1):
            parsed = self._parse_product_specs(product.specifications)
            skus = parsed.get("skus", [])
            categories = parsed.get("categories", [])
            label = "推荐首选" if i == 1 else f"备选商品{i}"
            price = product.price or "价格详询"
            sold = product.sold_quantity or 0
            selected_sku = self._select_sku_for_keywords(skus, keywords)
            display_skus = skus
            if selected_sku in skus:
                display_skus = [selected_sku] + [sku for sku in skus if sku != selected_sku]

            lines.append(f"\n[{label}]")
            lines.append(f"商品ID: {product.goods_id}")
            lines.append(f"商品名称: {product.goods_name}")
            lines.append(f"价格: {price}")
            lines.append(f"销量: {sold}")
            lines.append("可推荐SKU:")
            if skus:
                for j, sku in enumerate(display_skus[:5], 1):
                    lines.append(f"- [SKU{j}] {sku}")
            else:
                lines.append("- [SKU1] 标准款")
            if categories:
                lines.append(f"类目参考: {categories[0].replace('商品分类:', '').replace('商品分类：', '').strip()}")

            candidate_memory = {
                "goods_id": product.goods_id,
                "goods_name": product.goods_name,
                "price": price,
                "selected_sku": selected_sku,
                "skus": skus,
            }
            memory_candidates.append(candidate_memory)
            if i == 1:
                top_memory = {
                    **candidate_memory,
                    "keywords": keywords,
                    "candidates": memory_candidates,
                }

        if top_memory:
            top_memory["candidates"] = memory_candidates
            self._set_product_memory(session_id, top_memory)
            logger.info(
                f"[ProductMemory] 已锁定推荐商品: session_id={session_id}, "
                f"goods_id={top_memory.get('goods_id')}, sku={top_memory.get('selected_sku')}"
            )

        return "\n".join(lines)

    def _format_locked_product_context(self, product: Any, session_id: str = "", keywords: Optional[List[str]] = None) -> str:
        """格式化已锁定商品，供属性/安全/规格追问直接回答。"""
        parsed = self._parse_product_specs(product.specifications)
        skus = parsed.get("skus", [])
        price = product.price or "价格详询"
        selected_sku = skus[0] if skus else "标准款"
        previous_memory = self._get_product_memory(session_id)
        previous_candidates = previous_memory.get("candidates", [])

        self._set_product_memory(session_id, {
            "goods_id": product.goods_id,
            "goods_name": product.goods_name,
            "price": price,
            "selected_sku": selected_sku,
            "skus": skus,
            "keywords": keywords or [],
            "candidates": previous_candidates,
        })

        lines = [
            "【锁定商品库】用户正在追问上一轮推荐/当前锁定商品，请只围绕该商品回答。",
            f"商品ID: {product.goods_id}",
            f"商品名称: {product.goods_name}",
            f"价格: {price}",
            f"销量: {product.sold_quantity or 0}",
            "真实SKU:",
        ]
        if skus:
            for i, sku in enumerate(skus[:8], 1):
                lines.append(f"- [SKU{i}] {sku}")
        else:
            lines.append("- [SKU1] 标准款")
        attrs = self._load_json_dict(getattr(product, "attribute_json", None))
        if attrs:
            attr_labels = [
                ("类目", "category"),
                ("规格", "sku_summary"),
                ("成分/材质", "ingredients"),
                ("使用方法", "usage_method"),
                ("使用时长", "usage_duration"),
                ("起泡情况", "foaming"),
                ("适用年龄", "suitable_age"),
                ("适用肤质", "skin_type"),
                ("香味", "fragrance"),
                ("保质期", "shelf_life"),
            ]
            lines.append("结构化属性:")
            for label, key in attr_labels:
                value = attrs.get(key)
                if value:
                    lines.append(f"{label}: {value}")
            for label, key in (("功效", "effect"), ("注意事项", "warnings")):
                value = attrs.get(key)
                if value:
                    text = "、".join(value) if isinstance(value, list) else str(value)
                    lines.append(f"{label}: {text}")
        if product.extracted_content:
            lines.append("商品知识:")
            lines.append(product.extracted_content[:800])
        return "\n".join(lines)

    # =========================================================================
    # LangGraph 节点实现
    # =========================================================================

    def _search_current_product_vector_context(
        self,
        *,
        shop_id: Optional[int],
        goods_id: Optional[str],
        sub_intent: str,
        query: str,
    ) -> str:
        """Qdrant semantic fallback for current-product attributes.

        Existing Qdrant API supports shop/domain filtering. Product-level payload
        is not guaranteed in the current schema, so this is deliberately a
        conservative fallback: it only reads domains that are expected to contain
        product-attribute chunks and formats evidence if present.
        """
        if not shop_id or not goods_id or sub_intent not in self.ATTRIBUTE_SUB_INTENTS:
            return ""

        try:
            from database.qdrant_manager import qdrant_manager

            vector_results = qdrant_manager.search_knowledge(
                shop_id=str(shop_id),
                intent_domain=f"product_attribute:{goods_id}:{sub_intent}",
                query=query,
                top_k=2,
            )
            if not vector_results:
                vector_results = qdrant_manager.search_knowledge(
                    shop_id=str(shop_id),
                    intent_domain=f"product_attribute:{goods_id}",
                    query=query,
                    top_k=2,
                )
            if not vector_results:
                return ""

            lines = []
            for item in vector_results:
                content = item.get("answer") or item.get("content") or ""
                score = item.get("score", 0)
                if content and score >= 0.55:
                    lines.append(f"- {content[:180]} (相关度: {score:.2f})")
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"[Retriever-A] 当前商品向量兜底失败: {e}")
            return ""

    def node_router(self, state: CustomerServiceState) -> CustomerServiceState:
        """
        意图路由节点 - 三级漏斗混合路由（V2.0 重构版）

        优先级顺序（绝对不可乱）：
        Level 0: 红线关键词检测（最高优先级）
        Level 1: 极短句意图继承（排除危险词后）
        Level 2: 售后关键词检测
        Level 3: 售前关键词检测（带负向词过滤）
        Level 4: LLM 语义兜底（新增）
        """
        from database.redis_manager import redis_manager
        from Agent.CustomerAgent.custom.graph_state import AlertLevel, NEGATIVE_PRE_SALE, LOGISTICS_KEYWORDS

        query = state.get("user_query", "")
        session_id = state.get("session_id", "")
        logger.debug(f"[Router] 处理查询: {query[:30]}...")

        clean_query = self._clean_user_query(query)
        query_lower = query.lower()
        sub_intent_detail = self._classify_sub_intent_detail(clean_query)
        sub_intent = sub_intent_detail["sub_intent"]
        state = {
            **state,
            "sub_intent": sub_intent,
            "sub_intent_confidence": sub_intent_detail["confidence"],
            "sub_intent_terms": sub_intent_detail["matched_terms"],
        }
        route_keywords = self._route_keywords()
        product_memory = self._get_product_memory(session_id)
        memory_goods_id = product_memory.get("goods_id")

        # =====================================================
        # Level 0.5: 指代补全探测（Coreference Heuristics）
        # =====================================================
        COREFERENCE_INDICATORS = ['这个', '那个', '上一款', '第一款', '第二款', '刚才的', '刚才那个', '它']
        has_coreference = any(indicator in query for indicator in COREFERENCE_INDICATORS)

        if has_coreference:
            last_product = state.get("last_mentioned_product", "")
            if last_product:
                query = f"[上下文: 用户之前提到{last_product}] {query}"
                logger.info(f"[Router] 指代补全: 检测到指代词，补充上下文: {last_product}")

        # =====================================================
        # Level 0: 红线关键词检测（最高优先级，绝对不可跳过）
        # =====================================================
        for keyword in route_keywords["redline"]:
            if keyword in query_lower:
                logger.log("INNER", f"[Router] 命中红线关键词: {keyword}")
                # 红线意图不缓存，立即返回
                return {
                    **state,
                    "current_intent": IntentType.REDLINE,
                    "is_human_needed": True,
                    "alert_level": AlertLevel.HIGH,
                }

        # =====================================================
        # Level 0.1: 主动请求人工（普通转人工）
        # =====================================================
        for keyword in route_keywords["human_request"]:
            if keyword in clean_query:
                logger.log("INNER", f"[Router] 命中主动请求人工关键词: {keyword}")
                return {
                    **state,
                    "current_intent": IntentType.REDLINE,
                    "is_human_needed": True,
                    "alert_level": AlertLevel.LOW,
                }

        # =====================================================
        # Level 0.9: 明确售后表达，优先于极短句继承
        # =====================================================
        if self._is_explicit_after_sales_query(clean_query):
            logger.log("INNER", f"[Router] 命中明确售后表达: query='{clean_query[:30]}'")
            redis_manager.set_last_intent(session_id, IntentType.AFTER_SALES, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.AFTER_SALES,
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        # =====================================================
        # Level 0.95: 明确物流/闲聊/相对推荐，优先于极短句继承
        # =====================================================
        if sub_intent == SubIntentType.NONE and self._is_short_default_query(clean_query):
            logger.log("INNER", f"[Router] 命中短句默认回复: query='{clean_query[:30]}'")
            redis_manager.set_last_intent(session_id, IntentType.GENERAL, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.GENERAL,
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        for kw in route_keywords["logistics"]:
            if kw in query_lower:
                logger.log("INNER", f"[Router] 命中物流关键词: {kw}")
                redis_manager.set_last_intent(session_id, IntentType.LOGISTICS, ttl=INTENT_CACHE_TTL)
                return {
                    **state,
                    "current_intent": IntentType.LOGISTICS,
                    "is_human_needed": False,
                    "alert_level": AlertLevel.NONE,
                }

        if self._is_general_chat_query(clean_query):
            logger.log("INNER", f"[Router] 命中通用闲聊: query='{clean_query[:30]}'")
            redis_manager.set_last_intent(session_id, IntentType.GENERAL, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.GENERAL,
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        if sub_intent == SubIntentType.LOGISTICS_DELIVERY:
            logger.log("INNER", f"[Router] sub_intent={sub_intent}, query='{clean_query[:30]}'")
            redis_manager.set_last_intent(session_id, IntentType.LOGISTICS, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.LOGISTICS,
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        if sub_intent in {
            SubIntentType.USAGE_METHOD,
            SubIntentType.USAGE_DURATION,
            SubIntentType.AGE_SAFETY,
            SubIntentType.SKU_SPEC,
            SubIntentType.PRICE,
            SubIntentType.INGREDIENT,
            SubIntentType.FOAMING,
            SubIntentType.FRAGRANCE,
            SubIntentType.PRODUCT_ATTRIBUTE,
        }:
            locked_goods_id = state.get("locked_goods_id") or memory_goods_id
            logger.log(
                "INNER",
                f"[Router] sub_intent={sub_intent}, intent=pre_sale, goods_id={locked_goods_id}, query='{clean_query[:30]}'"
            )
            redis_manager.set_last_intent(session_id, IntentType.PRE_SALE, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.PRE_SALE,
                "locked_goods_id": str(locked_goods_id) if locked_goods_id else state.get("locked_goods_id"),
                "last_mentioned_product": product_memory.get("goods_name", state.get("last_mentioned_product", "")),
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        if sub_intent == SubIntentType.FRAGRANCE:
            logger.log("INNER", f"[Router] sub_intent={sub_intent}, intent=recommend, query='{clean_query[:30]}'")
            redis_manager.set_last_intent(session_id, IntentType.RECOMMEND, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.RECOMMEND,
                "locked_goods_id": str(memory_goods_id) if memory_goods_id else state.get("locked_goods_id"),
                "last_mentioned_product": product_memory.get("goods_name", state.get("last_mentioned_product", "")),
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        if sub_intent == SubIntentType.PRODUCT_DISCOVERY:
            logger.log("INNER", f"[Router] sub_intent={sub_intent}, intent=recommend, query='{clean_query[:30]}'")
            redis_manager.set_last_intent(session_id, IntentType.RECOMMEND, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.RECOMMEND,
                "locked_goods_id": str(memory_goods_id) if memory_goods_id else state.get("locked_goods_id"),
                "last_mentioned_product": product_memory.get("goods_name", state.get("last_mentioned_product", "")),
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        if (
            product_memory.get("candidates")
            and not self._extract_route_product_terms(clean_query)
            and (
                self._is_relative_product_choice_query(clean_query)
                or self._is_contextual_recommend_query(clean_query)
            )
        ):
            logger.log("INNER", f"[Router] 命中上下文推荐继承: query='{clean_query[:30]}'")
            redis_manager.set_last_intent(session_id, IntentType.RECOMMEND, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.RECOMMEND,
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        # =====================================================
        # Level 1: 极短句意图继承（排除危险词后）
        # =====================================================
        if (
            sub_intent == SubIntentType.NONE
            and len(query) <= SHORT_SENTENCE_THRESHOLD
            and not self._extract_route_product_terms(clean_query)
        ):
            last_intent = redis_manager.get_last_intent(session_id)
            if last_intent and last_intent in [
                IntentType.PRE_SALE,
                IntentType.AFTER_SALES,
                IntentType.LOGISTICS,
                IntentType.GENERAL,
            ]:
                logger.info(f"[Router] 极短句继承意图: query='{query}', intent={last_intent}")
                locked_goods_id = state.get("locked_goods_id")
                if last_intent == IntentType.PRE_SALE and self._is_product_followup_query(clean_query):
                    locked_goods_id = locked_goods_id or memory_goods_id
                return {
                    **state,
                    "current_intent": last_intent,
                    "locked_goods_id": str(locked_goods_id) if locked_goods_id else state.get("locked_goods_id"),
                    "last_mentioned_product": product_memory.get("goods_name", state.get("last_mentioned_product", "")),
                    "is_human_needed": False,
                    "alert_level": AlertLevel.NONE,
            }

        if self._is_relative_product_choice_query(clean_query):
            logger.log("INNER", f"[Router] 命中相对推荐/换款表达: query='{clean_query[:30]}'")
            redis_manager.set_last_intent(session_id, IntentType.RECOMMEND, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.RECOMMEND,
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        # =====================================================
        # Level 2: 售后关键词检测（优先级高于售前）
        # =====================================================
        for kw in route_keywords["after_sales"]:
            if kw in query_lower:
                logger.log("INNER", f"[Router] 命中售后关键词: {kw}")
                # 缓存意图
                redis_manager.set_last_intent(session_id, IntentType.AFTER_SALES, ttl=INTENT_CACHE_TTL)
                return {
                    **state,
                    "current_intent": IntentType.AFTER_SALES,
                    "is_human_needed": False,
                    "alert_level": AlertLevel.NONE,
                }

        # =====================================================
        # Level 2.5: 物流关键词检测（V2.0 新增）
        # =====================================================
        for kw in route_keywords["logistics"]:
            if kw in query_lower:
                logger.log("INNER", f"[Router] 命中物流关键词: {kw}")
                redis_manager.set_last_intent(session_id, IntentType.LOGISTICS, ttl=INTENT_CACHE_TTL)
                return {
                    **state,
                    "current_intent": IntentType.LOGISTICS,
                    "is_human_needed": False,
                    "alert_level": AlertLevel.NONE,
                }

        # =====================================================
        # Level 2.55: 商品负反馈（如“香氛不好闻”）优先按售后/安抚处理
        # =====================================================
        if self._is_negative_product_feedback(clean_query):
            logger.log("INNER", f"[Router] 命中商品负反馈: query='{clean_query[:30]}'")
            redis_manager.set_last_intent(session_id, IntentType.AFTER_SALES, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.AFTER_SALES,
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        # =====================================================
        # Level 2.6: 商品追问继承（上一轮推荐商品/当前商品）
        # =====================================================
        if self._is_product_followup_query(clean_query):
            locked_goods_id = state.get("locked_goods_id") or memory_goods_id
            if locked_goods_id:
                logger.log(
                    "INNER",
                    f"[Router] 商品追问继承: goods_id={locked_goods_id}, query='{clean_query[:30]}'"
                )
            else:
                logger.log("INNER", f"[Router] 商品属性追问但无锁定商品: query='{clean_query[:30]}'")
            redis_manager.set_last_intent(session_id, IntentType.PRE_SALE, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.PRE_SALE,
                "locked_goods_id": str(locked_goods_id) if locked_goods_id else state.get("locked_goods_id"),
                "last_mentioned_product": product_memory.get("goods_name", ""),
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        # =====================================================
        # Level 2.7: 推荐关键词检测（V2.0 新增）
        # =====================================================
        for kw in route_keywords["recommend"]:
            if kw in query_lower:
                logger.log("INNER", f"[Router] 命中推荐关键词: {kw}")
                redis_manager.set_last_intent(session_id, IntentType.RECOMMEND, ttl=INTENT_CACHE_TTL)
                return {
                    **state,
                    "current_intent": IntentType.RECOMMEND,
                    "is_human_needed": False,
                    "alert_level": AlertLevel.NONE,
                }

        # =====================================================
        # Level 2.8: 强商品词命中（如“湿敷棉/香氛/洗脸巾”）
        # =====================================================
        product_terms = self._extract_route_product_terms(clean_query)
        if product_terms:
            logger.log("INNER", f"[Router] 命中商品词典: terms={product_terms}")
            redis_manager.set_last_intent(session_id, IntentType.RECOMMEND, ttl=INTENT_CACHE_TTL)
            return {
                **state,
                "current_intent": IntentType.RECOMMEND,
                "is_human_needed": False,
                "alert_level": AlertLevel.NONE,
            }

        # =====================================================
        # Level 3: 售前关键词检测（带负向词过滤）
        # =====================================================
        # 检查是否包含负向关键词
        has_negative = any(neg_kw in query_lower for neg_kw in NEGATIVE_PRE_SALE)

        if not has_negative:
            for kw in route_keywords["pre_sale"]:
                if kw in query_lower:
                    logger.log("INNER", f"[Router] 命中售前关键词: {kw}")
                    # 缓存意图
                    redis_manager.set_last_intent(session_id, IntentType.PRE_SALE, ttl=INTENT_CACHE_TTL)
                    return {
                        **state,
                        "current_intent": IntentType.PRE_SALE,
                        "is_human_needed": False,
                        "alert_level": AlertLevel.NONE,
                    }

        # =====================================================
        # Level 4: LLM 语义兜底（Semantic Fallback）
        # =====================================================
        # 当上述 4 步全部走完，依然没有命中任何意图时，调用 LLM
        try:
            llm_intent = self._llm_semantic_fallback(query)
            valid_intents = ["pre_sale", "after_sales", "recommend", "logistics", "redline", "general", "unknown"]
            if llm_intent and llm_intent in valid_intents:
                logger.log("INNER", f"[Router] LLM 语义兜底: query='{query[:30]}', intent={llm_intent}")
                if llm_intent not in ["unknown", "redline"]:
                    redis_manager.set_last_intent(session_id, llm_intent, ttl=INTENT_CACHE_TTL)
                return {
                    **state,
                    "current_intent": llm_intent,
                    "is_human_needed": llm_intent == "redline",
                    "alert_level": AlertLevel.HIGH if llm_intent == "redline" else AlertLevel.NONE,
                }
        except Exception as e:
            logger.warning(f"[Router] LLM 语义兜底失败: {e}")

        # =====================================================
        # Level 5: 最终兜底 - unknown
        # =====================================================
        logger.info(f"[Router] 未命中任何意图，返回 unknown")
        return {
            **state,
            "current_intent": IntentType.UNKNOWN,
            "is_human_needed": False,
            "alert_level": AlertLevel.NONE,
        }

    def _llm_semantic_fallback(self, query: str) -> Optional[str]:
        """
        LLM 语义兜底分类

        使用本地 Ollama 进行意图分类，避免远程 API 延迟。
        """
        try:
            prompt = f"""你是一个意图分类器。请将用户的这句话分类到以下七个标签之一：
[pre_sale, after_sales, recommend, logistics, redline, general, unknown]

分类规则：
- pre_sale: 询问商品的成分、适用人群（如婴儿/孕妇能不能用）、保质期、使用方法等客观属性问题。不包括价格、优惠、推荐。
- after_sales: 退货、换货、退款、质量问题、漏液、破损
- recommend: 要求推荐、随便看看、有什么好物、选一个、询问价格优惠
- logistics: 询问发货、快递、物流状态、几天能到
- redline: 投诉、举报、假货、过敏、媒体曝光、法律威胁
- general: 日常闲聊、打招呼、感谢
- unknown: 完全看不懂的乱码或无意义内容

只需输出标签英文名，不要任何解释。
用户原话：{query}"""

            if not self._local_llm_client:
                return None

            response = self._local_llm_client.chat_sync(
                [{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.1,
            )
            if not response.success:
                logger.warning(f"[LLM Fallback] 调用失败: {response.error}")
                return None

            content = (response.content or "").strip().lower()
            for intent in ["pre_sale", "after_sales", "recommend", "logistics", "redline", "general", "unknown"]:
                if intent in content:
                    return intent

            return "unknown"

        except Exception as e:
            logger.warning(f"[LLM Fallback] 调用失败: {e}")
            return None

        # =====================================================
        # Level 3: LLM 决策（兜底）- 暂时返回通用意图
        # =====================================================
        if not detected_intent:
            logger.info("[Router] 未命中规则，返回通用意图")
            detected_intent = IntentType.GENERAL

        # 缓存意图（非红线意图）
        if session_id and detected_intent != IntentType.REDLINE:
            redis_manager.set_last_intent(session_id, detected_intent, ttl=INTENT_CACHE_TTL)

        # 高亮打印意图识别结果（使用 INNER 级别）
        logger.log("INNER", f"[意图识别] 买家原话: {query} => 识别意图: {detected_intent}")

        # 发射 AI 思考链路信号到前端
        try:
            from ui.signal_bus import global_signal_bus
            global_signal_bus.ai_thought_chain_signal.emit(
                session_id or "unknown",
                "意图识别",
                0.0,  # latency (毫秒级，意图识别几乎零延迟)
                f"买家: {query}",
                f"识别: {detected_intent}",
            )
        except Exception as e:
            logger.debug(f"发射意图信号失败: {e}")

        return {
            **state,
            "current_intent": detected_intent,
            "is_human_needed": False,
            "alert_level": AlertLevel.NONE,
        }

    def node_retriever(self, state: CustomerServiceState) -> CustomerServiceState:
        """
        知识检索节点（双轨定向检索）

        轨道 A：售前问题 → 结构化数据（MySQL/SQLite）
        轨道 B：售后/规则问题 → 向量检索（Qdrant）

        Args:
            state: 当前状态

        Returns:
            更新后的状态（设置 knowledge_context）
        """
        state = self._ensure_retrieval_policy(state)
        intent = state.get("current_intent", IntentType.UNKNOWN)
        sub_intent = state.get("sub_intent", SubIntentType.NONE)
        retrieval_policy = state.get("retrieval_policy", RetrievalPolicy.NONE)
        shop_id = state.get("shop_id")
        goods_id = state.get("locked_goods_id")
        query = state.get("user_query", "")
        session_id = state.get("session_id", "")

        logger.debug(
            f"[Retriever] 意图={intent}, sub_intent={sub_intent}, "
            f"policy={retrieval_policy}, shop_id={shop_id}, goods_id={goods_id}"
        )

        knowledge_context = ""

        try:
            if retrieval_policy == RetrievalPolicy.CURRENT_PRODUCT:
                if not goods_id:
                    knowledge_context = "【澄清提示】：用户在问当前商品属性，但当前没有明确商品上下文，请询问具体是哪款商品。"
                else:
                    # 从 ProductKnowledge 表查询真实商品数据
                    from database.db_manager import get_db_manager
                    from database.models import ProductKnowledge

                    db = get_db_manager()
                    with db.session_scope() as session:
                        db_shop_id = self._resolve_db_shop_id(session, shop_id)
                        product = session.query(ProductKnowledge).filter(
                            ProductKnowledge.shop_id == db_shop_id,
                            ProductKnowledge.goods_id == int(goods_id),
                        ).first()

                        if product:
                            knowledge_context = self._format_locked_product_context(
                                product=product,
                                session_id=session_id,
                                keywords=self._extract_query_keywords(query),
                            )
                            vector_context = self._search_current_product_vector_context(
                                shop_id=shop_id,
                                goods_id=goods_id,
                                sub_intent=sub_intent,
                                query=query,
                            )
                            if vector_context:
                                knowledge_context = f"{knowledge_context}\n\n【语义证据库】\n{vector_context}"
                            logger.info(
                                f"[Retriever-A] 当前商品知识检索成功: goods_id={goods_id}, "
                                f"sub_intent={sub_intent}"
                            )
                        else:
                            knowledge_context = f"未找到商品ID {goods_id} 的相关信息"
                            logger.warning(f"[Retriever-A] 商品未找到: goods_id={goods_id}")

            elif retrieval_policy == RetrievalPolicy.PRODUCT_CANDIDATES:
                knowledge_context = self._fetch_product_list_for_recommendation(shop_id, query, session_id)
                logger.log("INNER", f"[Retriever-A] 商品候选列表注入: 长度={len(knowledge_context)}")

            elif retrieval_policy == RetrievalPolicy.CLARIFY_PRODUCT:
                knowledge_context = "【澄清提示】：用户在问商品属性，但当前没有明确商品上下文。请询问用户具体是哪款商品。"
                logger.info(
                    f"[Retriever-A] 属性问题无商品上下文，进入澄清: sub_intent={sub_intent}, query='{query[:30]}'"
                )

            # =====================================================
            # 轨道 C：红线意图 → 转人工锁定 + 安抚话术
            # =====================================================
            elif intent == IntentType.REDLINE:
                # 安全获取 redis_manager 实例，设置人工锁
                from database.redis_manager import redis_manager
                session_id = state.get("session_id", "")

                if session_id:
                    redis_manager.set_human_lock(session_id)
                    logger.warning(f"[Retriever-C] 红线触发，人工锁定: session_id={session_id}")

                # 注入安抚话术
                knowledge_context = "【系统提示】：已触发转人工，请输出安抚话术，如'已经为您转交人工客服'。"

            # =====================================================
            # 轨道 D：物流意图 → 固定规则注入
            # =====================================================
            elif intent == IntentType.LOGISTICS:
                knowledge_context = "【物流规则】：本店正常48小时内发货，请勿承诺具体到达时间。"
                logger.info("[Retriever-D] 物流规则注入")

            # =====================================================
            # 轨道 E：通用意图 → 无需业务知识
            # =====================================================
            elif intent == IntentType.GENERAL:
                knowledge_context = "【上下文】：日常闲聊，无需业务知识。"
                logger.info("[Retriever-E] 通用上下文注入")

            # =====================================================
            # 轨道 B：售后问题 → 向量检索（Qdrant）
            # =====================================================
            elif intent == IntentType.AFTER_SALES:
                # Step 1: 向量检索（Qdrant）
                from database.qdrant_manager import qdrant_manager

                # 执行向量检索
                vector_results = qdrant_manager.search_knowledge(
                    shop_id=str(shop_id),
                    intent_domain="after_sales",
                    query=query,
                    top_k=3,
                )

                # Step 2: 如果向量检索有结果，格式化为上下文
                if vector_results:
                    context_parts = []
                    for i, result in enumerate(vector_results, 1):
                        question = result.get("question", "")
                        answer = result.get("answer", "")
                        score = result.get("score", 0)
                        context_parts.append(f"{i}. Q: {question}\n   A: {answer} (相关度: {score:.2f})")
                    knowledge_context = "\n".join(context_parts)
                    logger.info(
                        f"[Retriever-B] 向量检索完成: domain={intent_domain}, "
                        f"results={len(vector_results)}, top_score={vector_results[0]['score']:.3f}"
                    )
                else:
                    # Step 3: 向量检索无结果，回退到传统检索
                    logger.info("[Retriever-B] 向量检索无结果，回退到传统检索")
                    from Agent.CustomerAgent.tools.search_customer_service_knowledge import (
                        search_customer_service_knowledge,
                        SearchCustomerServiceKnowledgeParams,
                    )
                    params = SearchCustomerServiceKnowledgeParams(
                        query=query,
                        shop_id=shop_id or 0,
                    )
                    knowledge_context = search_customer_service_knowledge(params)
                    logger.info(f"[Retriever-B] 传统检索完成: {len(knowledge_context)} 字符")

        except Exception as e:
            logger.error(f"[Retriever] 知识检索失败: {e}")
            knowledge_context = ""

        return {
            **state,
            "knowledge_context": knowledge_context or "未找到相关知识",
        }

    async def node_generator(self, state: CustomerServiceState) -> CustomerServiceState:
        """
        SOP 回复生成节点（XML 防幻觉护栏）

        针对 7B 级别本地大模型优化，使用严苛的 XML 结构化 Prompt，
        防止幻觉和编造信息。
        """
        from database.redis_manager import redis_manager

        intent = state.get("current_intent", IntentType.UNKNOWN)
        knowledge = state.get("knowledge_context", "")
        query = state.get("user_query", "")
        goods_id = state.get("locked_goods_id")
        session_id = state.get("session_id", "")

        logger.debug(f"[Generator] 意图={intent}, 知识长度={len(knowledge)}")

        deterministic_reply = self._build_deterministic_product_reply(intent, query, knowledge)
        if deterministic_reply:
            logger.log("INNER", f"[Generator] 模板回复: {deterministic_reply[:50]}...")
            return {
                **state,
                "final_response": deterministic_reply,
            }

        # 检查 AI 苏醒状态（刚从人工接管转回）
        is_awakening = redis_manager.is_ai_awakening(session_id)
        if is_awakening:
            logger.info(f"[Generator] AI 苏醒状态检测: session_id={session_id}")

        # 构建 XML 结构化的 System Prompt
        system_prompt = self._build_xml_sop_prompt(
            intent=intent,
            knowledge=knowledge,
            goods_id=goods_id,
            is_awakening=is_awakening,
        )

        try:
            response = await self._llm_client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                tool_choice="none",
            )
            final_response = self._sanitize_generated_response(
                response.content or "抱歉，我暂时无法回复。",
                knowledge,
            )
        except Exception as e:
            logger.error(f"[Generator] LLM 生成失败: {e}")
            final_response = "抱歉，我现在无法回复，请稍后再试。"

        logger.log("INNER", f"[Generator] 生成回复: {final_response[:50]}...")

        return {
            **state,
            "final_response": final_response,
        }

    def _build_xml_sop_prompt(
        self,
        intent: str,
        knowledge: str,
        goods_id: Optional[str],
        is_awakening: bool = False,
    ) -> str:
        """
        构建 XML 结构化的 SOP Prompt（防幻觉护栏）

        针对 7B 级别本地大模型优化，结构极度清晰。

        Args:
            intent: 意图类型
            knowledge: 知识上下文
            goods_id: 锁定的商品ID
            is_awakening: 是否处于 AI 苏醒状态（刚从人工接管转回）

        Returns:
            XML 结构化的 System Prompt
        """
        # AI 苏醒指令（刚从人工接管转回时注入）
        awakening_note = ""
        if is_awakening:
            awakening_note = """

<system_note>你刚刚从真人客服手中接管了会话，请顺着用户的最新提问自然对答，绝对不要暴露自己是AI或提及人工已离线。</system_note>"""

        return f"""<system_role>你是某美妆香水品牌的资深售后与导购客服。你的回复必须亲切、专业，严禁生硬和机器感。</system_role>

<session_state>
- 当前会话意图: {intent}
- 锁定的商品ID: {goods_id or "未锁定"}
</session_state>

<knowledge_base>
{knowledge}
</knowledge_base>

<iron_rules priority="highest">
1. 【只用真实SKU】当买家要求推荐或意图为 recommend 时，必须从 <knowledge_base> 的“可推荐SKU/真实SKU”列表中挑选一个原文存在的 SKU。严禁编造容量、套装、版本、价格或功效。
2. 【禁止反问】如果 <knowledge_base> 已提供商品或锁定商品，必须直接推荐或回答当前商品问题。不要反问买家肤质、喜好、需求、预算。
3. 【直接行动】买家说"推荐"、"有什么"、"随便看看"时，第一句直接给出商品名 + 真实SKU，例如使用知识库中原样出现的 SKU 文本，不要寒暄客套。
4. 【字数控制】单次回复严格控制在 50 字以内，不要长篇大论。如果意图是 general，字数控制在 10 字以内！
</iron_rules>

<instructions>
1. 绝对忠于 <knowledge_base> 提供的信息，严禁编造任何退款、赔偿、包邮承诺或香水成分。
2. 若知识库要求客户提供照片凭证（如漏液、破损），你必须在回复中温柔地引导客户发送图片。
3. 如果意图是 logistics（物流），且没有具体物流信息，请回复固定安抚话术，字数严格控制在 30 字以内。
4. 严禁暴露你是 AI，如果上文有突兀的断层，请自然接话。
</instructions>{awakening_note}"""

    def node_human_fallback(self, state: CustomerServiceState) -> CustomerServiceState:
        """
        转人工执行节点

        执行转人工操作，设置人工静默锁，返回安抚话术

        Args:
            state: 当前状态

        Returns:
            更新后的状态（设置 final_response 和 is_human_needed）
        """
        from database.redis_manager import redis_manager

        shop_id = state.get("shop_id")
        from_uid = state.get("from_uid")
        session_id = state.get("session_id")
        user_id = state.get("user_id")  # V2.0 修复：从 state 获取 user_id
        query = state.get("user_query", "")

        logger.info(f"[HumanFallback] 触发转人工: shop_id={shop_id}, user_id={user_id}, from_uid={from_uid}")

        # 执行转人工
        transfer_success = False
        try:
            if shop_id and user_id and from_uid:
                from Channel.pinduoduo.utils.API.send_message import SendMessage

                # V2.0 修复：使用正确的 user_id 而非 "system"
                sender = SendMessage(str(shop_id), str(user_id))
                cs_list = sender.getAssignCsList()

                if cs_list and isinstance(cs_list, dict):
                    # 构造自己的客服 UID（不转接给自己）
                    my_cs_uid = f"cs_{shop_id}_{user_id}"

                    # 过滤掉自己，选择第一个可用客服
                    available_cs_uids = [uid for uid in cs_list.keys() if uid != my_cs_uid]

                    if available_cs_uids:
                        cs_uid = available_cs_uids[0]
                        cs_name = cs_list[cs_uid].get('name', '客服')

                        # 调用 move_conversation API
                        result = sender.move_conversation(from_uid, cs_uid)
                        transfer_success = result and result.get("success")

                        if transfer_success:
                            logger.info(f"[HumanFallback] 会话已转接给 {cs_name} ({cs_uid})")
                        else:
                            logger.error(f"[HumanFallback] 转接失败: {result}")
                    else:
                        logger.warning("[HumanFallback] 没有其他可用客服")
                else:
                    logger.warning("[HumanFallback] 客服列表为空")
            else:
                logger.warning(f"[HumanFallback] 参数缺失: shop_id={shop_id}, user_id={user_id}, from_uid={from_uid}")

        except Exception as e:
            logger.error(f"[HumanFallback] 转人工失败: {e}", exc_info=True)

        # =====================================================
        # 关键步骤：设置人工静默锁（4分钟）
        # =====================================================
        if session_id:
            # 设置人工锁（使用集中式配置）
            lock_success = redis_manager.set_human_lock(session_id, ttl=HUMAN_LOCK_TTL)
            if lock_success:
                logger.info(f"[HumanFallback] 人工静默锁已设置: session_id={session_id}, ttl={HUMAN_LOCK_TTL}s")
            else:
                logger.warning(f"[HumanFallback] 人工静默锁设置失败: session_id={session_id}")

        # 触发 UI 转人工提醒：弹窗 + 系统提示音。
        try:
            from core.di_container import container
            from core.notification import NotificationService

            notification_service = container.get(NotificationService)
            if notification_service:
                alert_level = state.get("alert_level") or "low"
                if alert_level == AlertLevel.HIGH:
                    alert_level = "high"
                else:
                    alert_level = "low"
                notification_service.alert_human_fallback(
                    shop_id=str(shop_id or "unknown"),
                    user_id=str(from_uid or user_id or "unknown"),
                    reason=f"转人工触发：{query[:40] or '未提供原因'}",
                    alert_level=str(alert_level),
                )
        except Exception as e:
            logger.warning(f"[HumanFallback] UI 转人工提醒触发失败: {e}")

        # 生成安抚话术
        if transfer_success:
            final_response = "您好，已为您转接人工客服，请稍候..."
        else:
            # 使用集中式常量的人工繁忙回复
            final_response = HUMAN_BUSY_REPLY

        return {
            **state,
            "final_response": final_response,
            "is_human_needed": True,
        }

    # =========================================================================
    # LangGraph 图构建
    # =========================================================================

    def _build_graph(self):
        """
        构建 LangGraph 工作流图

        流程：
        START → node_router → [node_human_fallback | node_retriever]
        node_retriever → node_generator → END
        node_human_fallback → END
        """
        if not LANGGRAPH_AVAILABLE:
            raise RuntimeError("LangGraph 未安装，请运行: pip install langgraph")

        # 创建状态图
        builder = StateGraph(CustomerServiceState)

        # 添加节点
        builder.add_node(NodeName.ROUTER, self.node_router)
        builder.add_node(NodeName.RETRIEVER, self.node_retriever)
        builder.add_node(NodeName.GENERATOR, self.node_generator)
        builder.add_node(NodeName.HUMAN_FALLBACK, self.node_human_fallback)

        # 设置入口点
        builder.set_entry_point(NodeName.ROUTER)

        # 添加条件边：路由节点根据意图分发
        builder.add_conditional_edges(
            NodeName.ROUTER,
            self._route_by_intent,
            {
                "human": NodeName.HUMAN_FALLBACK,
                "auto": NodeName.RETRIEVER,
            }
        )

        # 添加普通边
        builder.add_edge(NodeName.RETRIEVER, NodeName.GENERATOR)
        builder.add_edge(NodeName.GENERATOR, END)
        builder.add_edge(NodeName.HUMAN_FALLBACK, END)

        # 编译图
        graph = builder.compile(checkpointer=self._checkpointer)
        logger.info("LangGraph 图编译完成")

        return graph

    def _route_by_intent(self, state: CustomerServiceState) -> Literal["human", "auto"]:
        """
        路由条件函数

        根据状态决定下一步走向

        Args:
            state: 当前状态

        Returns:
            "human" - 转人工
            "auto" - 自动处理
        """
        is_human_needed = state.get("is_human_needed", False)
        intent = state.get("current_intent", IntentType.UNKNOWN)

        # 红线意图强制转人工
        if intent == IntentType.REDLINE or is_human_needed:
            logger.info(f"[Route] 路由到人工: intent={intent}")
            return "human"

        logger.info(f"[Route] 路由到自动处理: intent={intent}")
        return "auto"

    def _build_sop_prompt(self, intent: str, knowledge: str, query: str) -> str:
        """
        构建 SOP Prompt

        根据意图类型构建不同的 Prompt 模板

        Args:
            intent: 意图类型
            knowledge: 知识上下文
            query: 用户问题

        Returns:
            构建好的 Prompt
        """
        # SOP 模板
        sop_templates = {
            IntentType.PRE_SALE: """你是电商售前客服。请根据以下商品信息回答用户问题。

【商品信息】
{knowledge}

【回复要求】
- 简洁自然，像真人聊天
- 控制在30字以内
- 突出商品卖点
- 不要编造信息

用户问题：{query}""",

            IntentType.AFTER_SALES: """你是电商售后客服。请根据以下售后政策回答用户问题。

【售后政策】
{knowledge}

【回复要求】
- 态度诚恳，安抚用户情绪
- 简洁明了，给出解决方案
- 控制在30字以内
- 如需凭证，引导用户提供

用户问题：{query}""",

            IntentType.LOGISTICS: """你是电商物流客服。请回答用户关于物流的问题。

【物流信息】
{knowledge}

【回复要求】
- 准确告知物流状态
- 简洁自然
- 控制在30字以内

用户问题：{query}""",

            IntentType.GENERAL: """你是电商客服。请根据以下信息回答用户问题。

【相关信息】
{knowledge}

【回复要求】
- 简洁自然，像真人聊天
- 控制在30字以内
- 不确定的信息引导用户咨询人工

用户问题：{query}""",
        }

        template = sop_templates.get(intent, sop_templates[IntentType.GENERAL])
        return template.format(knowledge=knowledge, query=query)

    def _fetch_product_list_for_recommendation(self, shop_id: str, query: str = "", session_id: str = "") -> str:
        """
        获取店铺商品列表用于推荐场景

        当买家表达推荐意图但未指定具体商品时，
        获取该店铺的热销/在售商品列表，注入到知识上下文中。

        V2.0 重构：
        - 基于 Query 关键词过滤，避免语义断层
        - SKU 级精准下钻，组装规格树状结构

        Args:
            shop_id: 店铺ID（可能是原始ID或数据库ID）
            query: 买家的原始查询（用于关键词提取和过滤）

        Returns:
            格式化的商品+SKU树状字符串
        """
        from database.db_manager import get_db_manager
        from database.models import ProductKnowledge, ProductSearchTerm
        from sqlalchemy import or_

        try:
            db = get_db_manager()
            with db.session_scope() as session:
                # Step 1: 解析 shop_id（将原始ID转换为数据库ID）
                db_shop_id = self._resolve_db_shop_id(session, shop_id)
                logger.debug(f"[Retriever] 店铺ID解析: {shop_id} -> {db_shop_id}")

                clean_query = self._clean_user_query(query)
                sub_intent = self._classify_sub_intent(clean_query)
                if sub_intent in self.ATTRIBUTE_SUB_INTENTS:
                    logger.info(
                        f"[Retriever] 属性问题禁止商品列表召回: sub_intent={sub_intent}, query='{clean_query[:30]}'"
                    )
                    return "【澄清提示】：这是商品属性问题，不应召回商品列表。"

                product_memory = self._get_product_memory(session_id)
                if (
                    product_memory.get("candidates")
                    and not self._extract_route_product_terms(clean_query)
                    and (
                        self._is_relative_product_choice_query(clean_query)
                        or self._is_contextual_recommend_query(clean_query)
                    )
                ):
                    logger.info(
                        f"[Retriever] 使用上一轮候选集处理上下文推荐: query='{clean_query}', "
                        f"candidates={len(product_memory.get('candidates') or [])}"
                    )
                    return self._format_memory_candidates_context(product_memory, clean_query, session_id)

                known_terms = [
                    row[0] for row in session.query(ProductSearchTerm.term)
                    .filter(ProductSearchTerm.shop_id == db_shop_id)
                    .distinct()
                    .all()
                    if row and row[0]
                ]
                raw_keywords = self._extract_query_keywords(query, known_terms=known_terms)
                keywords = self._filter_product_candidate_keywords(raw_keywords)
                if raw_keywords != keywords:
                    logger.info(
                        f"[Retriever] 商品候选召回过滤属性/指代词: raw={raw_keywords}, filtered={keywords}"
                    )
                base_query = session.query(ProductKnowledge).filter(
                    ProductKnowledge.shop_id == db_shop_id,
                )

                if keywords:
                    term_rows = session.query(ProductSearchTerm).filter(
                        ProductSearchTerm.shop_id == db_shop_id,
                        ProductSearchTerm.term.in_(keywords),
                    ).all()

                    term_scores: Dict[int, Dict[str, Any]] = {}
                    for row in term_rows:
                        item = term_scores.setdefault(row.goods_id, {
                            "score": 0,
                            "matched_terms": [],
                            "term_types": [],
                        })
                        item["score"] += row.weight or 0
                        if row.term not in item["matched_terms"]:
                            item["matched_terms"].append(row.term)
                        if row.term_type not in item["term_types"]:
                            item["term_types"].append(row.term_type)

                    has_strong_term_hit = any(
                        any(term_type != "category" for term_type in item["term_types"])
                        for item in term_scores.values()
                    )

                    raw_products = []
                    if term_scores:
                        raw_products = base_query.filter(
                            ProductKnowledge.goods_id.in_(list(term_scores.keys()))
                        ).all()

                    if not raw_products:
                        filter_conditions = []
                        for kw in keywords:
                            pattern = f"%{kw}%"
                            filter_conditions.extend([
                                ProductKnowledge.goods_name.like(pattern),
                                ProductKnowledge.extracted_content.like(pattern),
                                ProductKnowledge.specifications.like(pattern),
                            ])
                        raw_products = (
                            base_query
                            .filter(or_(*filter_conditions))
                            .order_by(ProductKnowledge.sold_quantity.desc())
                            .limit(80)
                            .all()
                        )

                    scored_products = []
                    for product in raw_products:
                        if (
                            has_strong_term_hit
                            and product.goods_id in term_scores
                            and all(term_type == "category" for term_type in term_scores[product.goods_id]["term_types"])
                        ):
                            continue
                        parsed_specs = self._parse_product_specs(product.specifications)
                        score = self._score_product_candidate(product, keywords, parsed_specs)
                        if product.goods_id in term_scores:
                            score += term_scores[product.goods_id]["score"]
                        if score > 3:
                            scored_products.append((score, product.sold_quantity or 0, product))

                    scored_products.sort(key=lambda item: (item[0], item[1]), reverse=True)
                    products = [item[2] for item in scored_products[:3]]

                    if not products:
                        logger.info(
                            f"[Retriever] 关键词未命中有效商品，拒绝热销覆盖: keywords={keywords}"
                        )
                        return self._build_no_product_match_context(keywords)

                    logger.info(
                        f"[Retriever] 词典/关键词召回成功: keywords={keywords}, "
                        f"term_hits={len(term_scores)}, products={len(products)}"
                    )
                else:
                    products = (
                        base_query
                        .order_by(ProductKnowledge.sold_quantity.desc())
                        .limit(3)
                        .all()
                    )

                if not products:
                    logger.warning(f"[Retriever] 店铺无匹配商品: shop_id={shop_id}, query='{query}'")
                    return "【精准推荐库】：店铺暂无匹配商品，请引导客户关注店铺。"

                result = self._format_product_candidates_context(
                    products=products,
                    keywords=keywords,
                    session_id=session_id,
                )
                logger.info(
                    f"[Retriever] 商品列表获取成功: shop_id={shop_id}, 数量={len(products)}, "
                    f"关键词={keywords}"
                )
                return result

        except Exception as e:
            logger.error(f"[Retriever] 商品列表获取失败: {e}", exc_info=True)
            return "【精准推荐库】：店铺暂无匹配商品，请引导客户关注店铺。"

    # =========================================================================
    # Level -1 静态规则拦截器（零算力路由）
    # =========================================================================

    def _check_static_rules(self, query: str, shop_id: str) -> Optional[Reply]:
        """
        Level -1 静态规则拦截器

        在所有大模型和 RAG 检索之前，先检查静态规则匹配。
        实现零算力消耗的极速响应。

        Args:
            query: 用户查询
            shop_id: 店铺ID

        Returns:
            如果命中静态规则，返回 Reply 对象；否则返回 None
        """
        from database.redis_manager import redis_manager
        from ui.signal_bus import global_signal_bus
        import time

        try:
            # 从 Redis 获取静态规则
            rules = redis_manager.get_static_rules(shop_id)

            if not rules:
                return None

            # 遍历规则，查找匹配
            matched_keyword = None
            matched_reply = None
            max_length = 0

            for keyword, reply in rules.items():
                if keyword in query:
                    # 冲突处理：优先使用长度最长的关键词
                    if len(keyword) > max_length:
                        max_length = len(keyword)
                        matched_keyword = keyword
                        matched_reply = reply

            if matched_keyword and matched_reply:
                logger.info(f"[StaticRouter] 命中静态规则: keyword={matched_keyword}, shop_id={shop_id}")

                # 发射 AI 思考链路信号（降级展示）
                global_signal_bus.ai_thought_chain_signal.emit(
                    shop_id,  # session_id
                    "静态规则拦截",  # intent
                    0.001,  # latency (毫秒级)
                    f"触发词: {matched_keyword}",  # knowledge_source
                    matched_reply[:50]  # response_preview
                )

                return Reply(ReplyType.TEXT, matched_reply)

            return None

        except Exception as e:
            # 异常容灾：记录警告，平滑降级到 V2.0 正常路由
            logger.warning(f"[StaticRouter] 静态规则检查失败，降级到正常路由: {e}")
            return None

    # =========================================================================
    # 公共接口
    # =========================================================================

    async def async_reply(self, query: str, context: Context = None) -> Reply:
        """异步回复接口"""
        # 延迟初始化
        if not self._is_initialized:
            if not await self.initialize_async():
                return Reply(ReplyType.TEXT, "AI客服初始化失败，请检查配置。")

        # =====================================================
        # Level -1: 静态规则拦截器（零算力路由）
        # =====================================================
        if context and hasattr(context, 'kwargs'):
            shop_id = str(getattr(context.kwargs, 'shop_id', 'default'))
            static_reply = self._check_static_rules(query, shop_id)
            if static_reply:
                return static_reply

        # 统一交由 LangGraph 意图识别引擎处理
        return await self._graph_reply(query, context)

        # 知识库预检索
        knowledge_info = ""
        if context and hasattr(context, 'kwargs'):
            kwargs = context.kwargs
            shop_id = getattr(kwargs, 'shop_id', None)
            goods_id = getattr(kwargs, 'goods_id', None)

            if shop_id:
                try:
                    knowledge_info = await self._fetch_knowledge_for_local(query, shop_id, goods_id)
                except Exception as e:
                    logger.warning(f"本地模型知识库检索失败: {e}")

        if not knowledge_info:
            return await self._graph_reply(query, context)

        system_content = f"""你是专业的电商客服助手。请严格根据提供的【知识库信息】回答用户问题。
回复要求：
- 简短自然，像真人聊天
- 控制在30字以内
- 不要使用表情符号
- 直接回答，不要客套

【知识库信息】
{knowledge_info}

请基于以上知识库信息回答用户问题。"""

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": query},
        ]

        response = await self._local_llm_client.chat(messages)

        if response.success:
            return Reply(ReplyType.TEXT, response.content)
        else:
            return await self._graph_reply(query, context)

    async def _fetch_knowledge_for_local(self, query: str, shop_id: int, goods_id: str = None) -> str:
        """为本地模型预检索知识库"""
        from Agent.CustomerAgent.tools.get_product_knowledge import (
            get_product_knowledge,
            GetProductKnowledgeParams,
        )
        from Agent.CustomerAgent.tools.search_customer_service_knowledge import (
            search_customer_service_knowledge,
            SearchCustomerServiceKnowledgeParams,
        )

        if goods_id:
            try:
                params = GetProductKnowledgeParams(
                    goods_id=int(goods_id),
                    shop_id=shop_id,
                )
                result = get_product_knowledge(params)
                if result and "未找到" not in result and "错误" not in result:
                    return result
            except Exception as e:
                logger.debug(f"商品知识精确查询失败: {e}")

        product_keywords = ['成分', '功效', '用法', '规格', '价格', '多少钱', '什么材质', '保质期',
                          '怎么用', '怎么吃', '效果', '作用', '适合', '敏感肌', '孕妇']
        service_keywords = ['退货', '换货', '退款', '发货', '物流', '快递', '几天到',
                          '保修', '售后', '客服', '投诉', '发票']

        result = ""
        is_product_query = any(kw in query for kw in product_keywords)
        is_service_query = any(kw in query for kw in service_keywords)

        if is_product_query or is_service_query:
            try:
                params = SearchCustomerServiceKnowledgeParams(query=query, shop_id=shop_id)
                result = search_customer_service_knowledge(params)
                if result and "未找到" not in result:
                    return result
            except Exception as e:
                logger.debug(f"知识库检索失败: {e}")

        return result if result and "未找到" not in result else ""

    async def _graph_reply(self, query: str, context: Context = None) -> Reply:
        """
        使用 LangGraph 工作流生成回复

        Args:
            query: 用户问题
            context: 上下文对象

        Returns:
            Reply 对象
        """
        try:
            # 构建 session_id 和提取上下文信息
            if context and context.channel_type and hasattr(context.kwargs, "user_id"):
                session_id = f"{context.channel_type.value}{context.kwargs.user_id}"
                dependencies = self._message_builder.build_dependencies(context)
            else:
                session_id = f"fallback_{abs(hash(query)) % 100000}"
                dependencies = {}

            # 初始化状态
            initial_state: CustomerServiceState = {
                "session_id": session_id,
                "messages": [],
                "current_intent": IntentType.UNKNOWN,
                "sub_intent": SubIntentType.NONE,
                "sub_intent_confidence": 0.0,
                "sub_intent_terms": [],
                "retrieval_policy": RetrievalPolicy.NONE,
                "entity_scope": "unknown",
                "locked_goods_id": dependencies.get("goods_id"),
                "knowledge_context": "",
                "is_human_needed": False,
                "final_response": "",
                "error_message": None,
                "shop_id": dependencies.get("shop_id"),
                "from_uid": dependencies.get("from_uid"),
                "user_id": dependencies.get("user_id"),  # V2.0 修复：注入 user_id
                "user_query": query,
            }

            # 执行图工作流（Fail-Fast：graph 必须存在）
            if not self._graph:
                raise RuntimeError("LangGraph 工作流未初始化！V2.0 架构必须使用 LangGraph")

            config = {"configurable": {"thread_id": session_id}}
            result = await self._graph.ainvoke(initial_state, config)
            final_response = result.get("final_response", "抱歉，我暂时无法回复。")

            # 转人工节点会通过 NotificationService 触发 UI 提醒和系统提示音。
            is_human_needed = result.get("is_human_needed", False)
            if is_human_needed:
                logger.warning(
                    f"[GraphReply] 人工接管触发: shop_id={dependencies.get('shop_id')}, "
                    f"from_uid={dependencies.get('from_uid')}, intent={result.get('current_intent', 'unknown')}"
                )

            # 保存到历史
            self._session_manager.add_message(
                session_id=session_id,
                role="assistant",
                content=final_response,
            )

            return Reply(ReplyType.TEXT, final_response)

        except Exception as e:
            logger.error(f"LangGraph 回复失败: {e}")
            return Reply(ReplyType.TEXT, "抱歉，我现在无法回复，请稍后再试。")

    async def _run_legacy_agent_loop(
        self,
        query: str,
        dependencies: Dict[str, Any],
    ) -> str:
        """
        传统 ReAct 循环（降级方案）

        当 LangGraph 不可用时使用
        """
        # 构建消息
        messages = self._message_builder.build_messages(query, [], dependencies)

        loop_count = 0
        while loop_count < self._config.max_loops:
            try:
                response = await self._llm_client.chat(messages, tool_choice="auto")
            except Exception as e:
                logger.error(f"LLM 调用失败: {e}")
                return "抱歉，AI 服务暂时不可用。"

            if not response.has_tool_calls:
                return response.content or ""

            # 执行工具
            tool_results = await self._tool_executor.execute_parallel(
                response.tool_calls, dependencies
            )

            for result in tool_results:
                messages.append(result.to_dict())

            loop_count += 1

        return messages[-1].get("content", "抱歉，处理超时。")

    async def _compress_with_llm(
        self,
        session_id: str,
        history: List[Dict[str, Any]],
    ) -> None:
        """使用 LLM 生成摘要并压缩历史"""

        def summary_llm(messages: List[Dict[str, Any]]) -> str:
            summary_prompt = (
                "请简洁地总结以下对话的要点，保留关键信息和用户意图。\n\n"
                f"对话内容（共 {len(messages)} 条消息）：\n"
                + "\n".join(
                    f"[{msg.get('role', 'unknown')}]: {msg.get('content', '')[:200]}"
                    for msg in messages
                    if msg.get("content")
                )
            )

            try:
                response = asyncio.run(
                    self._llm_client.chat(
                        messages=[
                            {"role": "system", "content": "你是一个对话摘要助手。"},
                            {"role": "user", "content": summary_prompt},
                        ],
                        tool_choice="none",
                    )
                )
                return response.content or "[摘要生成失败]"
            except Exception:
                return "[摘要生成失败]"

        self._session_manager.compress_history(session_id, summary_llm)
