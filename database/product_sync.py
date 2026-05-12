"""
产品知识自动同步服务
=================

从拼多多API拉取商品列表，调用多模态LLM分析提取产品知识存入知识库。
"""
import asyncio
import threading
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass
import json
import re
import time

from openai import AsyncOpenAI
from config import get_config

from Channel.pinduoduo.utils.API.product_manager import ProductManager
from database.knowledge_service import KnowledgeService
from database.product_terms import extract_product_terms
from database.qdrant_manager import qdrant_manager
from utils.logger_loguru import get_logger

logger = get_logger("ProductSync")

PRODUCT_ATTRIBUTE_SCHEMA_VERSION = 1

DEFAULT_PRODUCT_ATTRIBUTES: Dict[str, Any] = {
    "category": "",
    "brand": "",
    "sku_options": [],
    "sku_summary": "",
    "ingredients": "",
    "usage_method": "",
    "usage_duration": "",
    "foaming": "",
    "suitable_age": "",
    "skin_type": "",
    "fragrance": "",
    "effect": [],
    "shelf_life": "",
    "warnings": [],
    "accessories": [],
}

PRODUCT_LLM_FIELDS = set(DEFAULT_PRODUCT_ATTRIBUTES.keys())


@dataclass
class SyncProgress:
    """同步进度"""
    total: int
    current: int
    success: int
    failed: int
    current_goods_name: str
    cancelled: bool = False
    phase: str = "fetching"  # "fetching": 抓取商品列表, "extracting": 提取知识


class ProductSyncService:
    """产品知识自动同步服务"""

    def __init__(
        self,
        knowledge_service: KnowledgeService,
        request_delay: float = 1.0,
    ):
        """
        初始化

        Args:
            knowledge_service: 知识库服务实例
            request_delay: API请求间隔（秒），避免限流
        """
        self.knowledge_service = knowledge_service
        self.request_delay = request_delay
        self._cancellation_event = threading.Event()
        logger.info("ProductSyncService 初始化成功")

    def cancel(self) -> None:
        """取消同步"""
        self._cancellation_event.set()
        logger.info("同步已取消")

    def is_cancelled(self) -> bool:
        """检查是否已取消"""
        return self._cancellation_event.is_set()

    def _reset_cancellation(self) -> None:
        """重置取消事件"""
        self._cancellation_event.clear()

    async def sync_shop(
        self,
        shop_id: int,
        shop_db_id: int,
        user_id: str,
        is_full_sync: bool = False,
        progress_callback: Optional[Callable[[SyncProgress], None]] = None,
    ) -> SyncProgress:
        """
        同步店铺产品知识（两阶段同步）

        第一阶段：快速抓取所有商品基本信息（商品ID、名称等）并保存到数据库
        第二阶段：批量异步识别每个商品的详细信息

        Args:
            shop_id: 店铺ID（拼多多的shop_id）
            shop_db_id: 店铺在数据库中的ID
            user_id: 用户ID（用于拼多多API认证）
            is_full_sync: True=全量同步，False=增量同步（仅同步本地不存在的商品）
            progress_callback: 进度回调，每次更新进度调用

        Returns:
            最终同步进度
        """
        self._reset_cancellation()
        pm = ProductManager(shop_id=str(shop_id), user_id=user_id)

        # ================== 第一阶段：快速抓取商品列表 ==================
        logger.info("=== 第一阶段：开始抓取商品列表 ===")

        # 第一页获取总数量
        first_page = pm.get_product_list(page=1, size=20)
        if not first_page["success"]:
            logger.error(f"获取商品列表失败: {first_page.get('error_msg')}")
            progress = SyncProgress(
                total=0, current=0, success=0, failed=0, current_goods_name="",
                phase="fetching"
            )
            progress.failed = 1
            return progress

        total = first_page["total"]
        logger.info(f"店铺共有 {total} 个商品，开始抓取商品列表...")

        progress = SyncProgress(
            total=total,
            current=0,
            success=0,
            failed=0,
            current_goods_name="",
            phase="fetching"
        )

        # 分页拉取所有商品
        current_page = 1
        all_products: List[Dict[str, Any]] = []

        while True:
            if self.is_cancelled():
                progress.cancelled = True
                logger.info("同步已被用户取消")
                break

            page_result = pm.get_product_list(page=current_page, size=50)
            if not page_result["success"]:
                logger.error(f"获取第 {current_page} 页失败: {page_result.get('error_msg')}")
                break

            products = page_result["products"]
            if not products:
                break

            all_products.extend(products)
            current_page += 1

            # 更新进度
            progress.current = len(all_products)
            if all_products:
                progress.current_goods_name = all_products[-1].get("goods_name", "")
            if progress_callback:
                progress_callback(progress)

            # 延迟避免限流
            await asyncio.sleep(self.request_delay)

        if self.is_cancelled():
            return progress

        logger.info(f"第一阶段完成：共获取 {len(all_products)} 个商品")

        # 增量同步筛选：只处理本地不存在的商品
        products_to_process: List[Dict[str, Any]] = []
        if not is_full_sync:
            original_count = len(all_products)
            filtered_products: List[Dict[str, Any]] = []
            for p in all_products:
                goods_id = p.get("goods_id")
                existing = self.knowledge_service.get_product_by_goods_id(shop_db_id, goods_id)
                if not existing:
                    filtered_products.append(p)
            logger.info(f"增量同步: 总商品 {original_count}，需要同步 {len(filtered_products)} 个（已存在跳过）")
            products_to_process = filtered_products
        else:
            products_to_process = all_products

        # ================== 第一阶段B：快速保存商品基本信息 ==================
        logger.info("=== 开始快速保存商品基本信息 ===")
        progress.phase = "saving_basic"
        progress.total = len(products_to_process)
        progress.current = 0
        progress.success = 0
        progress.failed = 0

        for idx, product in enumerate(products_to_process):
            if self.is_cancelled():
                progress.cancelled = True
                break

            goods_id = product.get("goods_id")
            goods_name = product.get("goods_name", f"goods_{goods_id}")
            progress.current = idx + 1
            progress.current_goods_name = goods_name

            try:
                # 先只保存基本信息，不调用LLM
                self.knowledge_service.add_or_update_product(
                    shop_id=shop_db_id,
                    goods_id=goods_id,
                    goods_name=goods_name,
                    price=product.get("price"),
                    price_min=product.get("price_min"),
                    price_max=product.get("price_max"),
                    sold_quantity=product.get("sold_quantity"),
                    thumb_url=product.get("thumb_url"),
                    specifications=None,
                    extracted_content=None,  # 留空，第二阶段填充
                )
                basic_terms = extract_product_terms(goods_name=goods_name)
                self.knowledge_service.replace_product_search_terms(
                    shop_id=shop_db_id,
                    goods_id=goods_id,
                    terms=basic_terms,
                )
                progress.success += 1
                logger.debug(f"商品基本信息已保存: {goods_name} (ID: {goods_id})")
            except Exception as e:
                logger.error(f"保存商品基本信息失败 {goods_id}: {e}")
                progress.failed += 1
                continue

            if progress_callback:
                progress_callback(progress)

        if self.is_cancelled():
            logger.info("同步已取消")
            return progress

        logger.info(f"商品基本信息保存完成: 成功 {progress.success}, 失败 {progress.failed}")

        # ================== 第二阶段：并发提取详细知识 ==================
        logger.info("=== 第二阶段：开始并发提取商品详细知识 ===")
        progress.phase = "extracting"
        progress.current = 0
        progress.success = 0
        progress.failed = 0

        # 使用线程安全的计数器
        from threading import Lock
        counter_lock = Lock()

        async def process_single_product(product: Dict[str, Any]):
            """处理单个商品的知识提取"""
            if self.is_cancelled():
                return

            goods_id = product.get("goods_id")
            goods_name = product.get("goods_name", f"goods_{goods_id}")

            # 更新当前处理商品名称
            with counter_lock:
                progress.current_goods_name = goods_name
                if progress_callback:
                    progress_callback(progress)

            logger.debug(f"正在提取知识: {goods_name} (ID: {goods_id})")

            try:
                # 获取商品详情
                detail = pm.get_product_detail(goods_id)
                await asyncio.sleep(self.request_delay)

                if not detail["success"]:
                    logger.error(f"获取商品详情失败: {goods_id}, {detail.get('error_msg')}")
                    with counter_lock:
                        progress.failed += 1
                        progress.current += 1
                        if progress_callback:
                            progress_callback(progress)
                    return

                product_info = dict(detail["product_info"])
                product_info["specifications"] = self._normalize_specifications(
                    product_info.get("specifications", [])
                )
                existing_product = self.knowledge_service.get_product_by_goods_id(shop_db_id, goods_id)
                if existing_product and existing_product.extracted_content:
                    product_info["extracted_content"] = existing_product.extracted_content

                extract_mode = get_config("product_extract_mode", "llm_first")
                if extract_mode == "llm_first":
                    attrs, sources = await self._extract_attributes_llm_first(product, product_info)
                else:
                    rule_attrs, rule_sources = self._extract_attributes_by_rules(product, product_info)
                    llm_attrs, llm_sources = await self._extract_attributes_by_llm(product, product_info, rule_attrs)
                    attrs, sources = self._merge_product_attributes(
                        rule_attrs=rule_attrs,
                        rule_sources=rule_sources,
                        llm_attrs=llm_attrs,
                        llm_sources=llm_sources,
                    )
                attrs, sources = self._preserve_manual_attributes(existing_product, attrs, sources)
                extracted = self._render_product_context(product, product_info, attrs)

                self.knowledge_service.update_product_knowledge_payload(
                    shop_id=shop_db_id,
                    goods_id=goods_id,
                    specifications=json.dumps(product_info.get("specifications", []), ensure_ascii=False),
                    extracted_content=extracted,
                    raw_detail_json=json.dumps(product_info, ensure_ascii=False),
                    attribute_json=json.dumps(attrs, ensure_ascii=False),
                    attribute_source_json=json.dumps(sources, ensure_ascii=False),
                    knowledge_status="extracted",
                    knowledge_version=PRODUCT_ATTRIBUTE_SCHEMA_VERSION,
                )
                self._upsert_product_attribute_vectors(shop_id, goods_id, attrs, sources)
                search_terms = extract_product_terms(
                    goods_name=goods_name,
                    specifications=product_info.get("specifications", []),
                    extracted_content=extracted,
                )
                self.knowledge_service.replace_product_search_terms(
                    shop_id=shop_db_id,
                    goods_id=goods_id,
                    terms=search_terms,
                )

                with counter_lock:
                    progress.success += 1
                    progress.current += 1
                    logger.info(f"商品知识提取成功: {goods_name} (ID: {goods_id})")
                    if progress_callback:
                        progress_callback(progress)

            except Exception as e:
                logger.error(f"提取商品知识失败 {goods_id}: {e}")
                with counter_lock:
                    progress.failed += 1
                    progress.current += 1
                    if progress_callback:
                        progress_callback(progress)

        # 并发处理，控制并发数量避免限流
        max_concurrent = 3  # 最多3个并发
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_semaphore(product: Dict[str, Any]):
            async with semaphore:
                if not self.is_cancelled():
                    await process_single_product(product)

        # 创建所有任务
        tasks = [process_with_semaphore(product) for product in products_to_process]

        # 运行所有任务
        await asyncio.gather(*tasks)

        logger.info(f"同步完成: 总计 {progress.total}, 成功 {progress.success}, 失败 {progress.failed}")
        return progress

    def _source(self, source: str, confidence: float, evidence: str = "") -> Dict[str, Any]:
        return {
            "source": source,
            "confidence": confidence,
            "evidence": str(evidence or "")[:300],
        }

    def _json_loads_dict(self, raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            data = json.loads(str(raw))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _preserve_manual_attributes(
        self,
        existing_product: Any,
        attrs: Dict[str, Any],
        sources: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Keep fields edited in the Qt product form from being overwritten by sync extraction."""
        if not existing_product:
            return attrs, sources

        existing_attrs = self._json_loads_dict(getattr(existing_product, "attribute_json", None))
        existing_sources = self._json_loads_dict(getattr(existing_product, "attribute_source_json", None))
        preserved: List[str] = []

        for key in DEFAULT_PRODUCT_ATTRIBUTES:
            value = existing_attrs.get(key)
            source_info = existing_sources.get(key) or {}
            if not isinstance(source_info, dict):
                continue
            if source_info.get("source") != "manual_ui":
                continue
            if value in (None, "", []):
                continue
            attrs[key] = value
            sources[key] = {
                **self._source(
                    "manual_ui",
                    float(source_info.get("confidence") or 1.0),
                    source_info.get("evidence") or value,
                ),
                "preserved_from_sync": True,
            }
            preserved.append(key)

        if preserved:
            logger.info(
                f"保留人工标注字段: goods_id={getattr(existing_product, 'goods_id', '')}, fields={preserved}"
            )
        return attrs, sources

    def _set_attr(
        self,
        attrs: Dict[str, Any],
        sources: Dict[str, Any],
        key: str,
        value: Any,
        source: str,
        confidence: float,
        evidence: str = "",
    ) -> None:
        if value in (None, "", []):
            return
        if attrs.get(key) not in (None, "", []):
            return
        attrs[key] = value
        sources[key] = self._source(source, confidence, evidence)

    def _normalize_specifications(self, specs_raw: Any) -> List[Dict[str, str]]:
        """Normalize product specifications to [{key: value}] for rules, prompts, and storage."""
        if not specs_raw:
            return []
        if isinstance(specs_raw, str):
            text = specs_raw.strip()
            if not text:
                return []
            try:
                specs_raw = json.loads(text)
            except json.JSONDecodeError:
                specs_raw = [line.strip("- \t") for line in text.splitlines() if line.strip()]
        if isinstance(specs_raw, dict):
            specs_raw = [specs_raw]
        if not isinstance(specs_raw, list):
            specs_raw = [specs_raw]

        normalized: List[Dict[str, str]] = []
        for item in specs_raw:
            if isinstance(item, dict):
                for key, value in item.items():
                    key_text = str(key).strip() or "信息"
                    value_text = str(value).strip()
                    if value_text:
                        normalized.append({key_text: value_text})
                continue

            item_text = str(item).strip().strip("-").strip()
            if not item_text:
                continue
            if "：" in item_text:
                key, value = item_text.split("：", 1)
            elif ":" in item_text:
                key, value = item_text.split(":", 1)
            else:
                key, value = "信息", item_text
            key_text = key.strip() or "信息"
            value_text = value.strip()
            if value_text:
                normalized.append({key_text: value_text})
        return normalized

    def _extract_attributes_by_rules(
        self,
        list_product: Dict[str, Any],
        detail_product: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """高确定性规则抽取，优先于 LLM。"""
        attrs = dict(DEFAULT_PRODUCT_ATTRIBUTES)
        sources: Dict[str, Any] = {}
        goods_name = str(list_product.get("goods_name") or "")
        specs = self._normalize_specifications(detail_product.get("specifications", []))
        extra_text = str(
            detail_product.get("raw_text")
            or detail_product.get("extra_text")
            or detail_product.get("extracted_content")
            or ""
        )
        spec_text = "\n".join(
            str(value)
            for spec in specs
            for value in spec.values()
            if str(value).strip()
        )
        text = f"{goods_name}\n{spec_text}\n{json.dumps(specs, ensure_ascii=False)}\n{extra_text}"

        category_text = ""
        for spec in specs:
            if isinstance(spec, dict):
                for key, value in spec.items():
                    if "商品分类" in str(key):
                        category_text = str(value)
                        break
            if category_text:
                break
        category_from_path = [
            ("防晒霜", ("防晒霜", "防晒")),
            ("素颜霜", ("素颜霜", "面部素颜霜")),
            ("湿敷棉", ("湿敷棉", "化妆棉", "棉片")),
            ("洗脸巾", ("洗脸巾", "棉柔巾", "柔纸巾")),
            ("卸妆水", ("卸妆水", "卸妆乳")),
            ("化妆刷", ("化妆刷",)),
            ("洗面奶", ("洗面奶", "洁面乳", "洁面")),
            ("香水", ("香水", "香氛")),
        ]
        for category, terms in category_from_path:
            category_leaf = category_text.split(">")[-1] if category_text else ""
            if any(term in category_leaf for term in terms) or (
                not category_leaf and any(term in category_text for term in terms)
            ):
                self._set_attr(attrs, sources, "category", category, "rule", 0.98, category_text)
                break

        category_rules = {
            "防晒霜": ("防晒霜", "防晒"),
            "素颜霜": ("素颜霜",),
            "湿敷棉": ("湿敷棉", "化妆棉", "棉片"),
            "洗脸巾": ("洗脸巾", "棉柔巾", "柔纸巾"),
            "卸妆水": ("卸妆水", "卸妆乳"),
            "化妆刷": ("化妆刷",),
            "洗面奶": ("洗面奶", "洁面", "洁面乳"),
            "香水": ("香水", "香氛", "喷雾"),
        }
        for category, terms in category_rules.items():
            if any(term in text for term in terms):
                self._set_attr(attrs, sources, "category", category, "rule", 0.95, goods_name)
                break

        quantity_match = re.search(r"\d+\s*(瓶|支|盒|包|片|抽|ml|mL|g|克)", text, flags=re.I)
        if quantity_match:
            self._set_attr(attrs, sources, "sku_summary", quantity_match.group(0), "rule", 0.9, quantity_match.group(0))

        sku_options: List[str] = []
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            for key, value in spec.items():
                if "款式" not in str(key) and "规格" not in str(key):
                    continue
                option = str(value).strip()
                if not option:
                    continue
                sku_options.append(option)
        if sku_options:
            self._set_attr(attrs, sources, "sku_options", sku_options, "rule", 0.9, "；".join(sku_options[:5]))

        fragrance_terms = ["茉莉", "栀子", "桂花", "玫瑰", "白茶", "原味", "薰衣草", "海盐"]
        fragrances = [term for term in fragrance_terms if term in text]
        if fragrances:
            self._set_attr(attrs, sources, "fragrance", "、".join(fragrances), "rule", 0.85, goods_name)

        age_match = re.search(r"(\d+\s*岁以上|儿童|婴儿|宝宝|成人|孕妇|敏感肌)", text)
        if age_match:
            self._set_attr(attrs, sources, "suitable_age", age_match.group(0), "rule", 0.85, age_match.group(0))

        effect_terms = ["清洁", "控油", "保湿", "补水", "美白", "祛斑", "卸妆", "留香", "止汗"]
        effects = [term for term in effect_terms if term in text]
        if effects:
            self._set_attr(attrs, sources, "effect", effects[:5], "rule", 0.75, goods_name)

        duration_match = re.search(
            r"((?:一|二|三|四|五|六|七|八|九|十|\d+)\s*瓶?[^。；;\n]{0,8}(?:用|可用|能用)[^。；;\n]{0,12}(?:天|周|个月|月))",
            text,
        )
        if duration_match:
            self._set_attr(attrs, sources, "usage_duration", duration_match.group(1), "rule", 0.9, duration_match.group(1))

        usage_match = re.search(r"((?:早晚|每天|每日|一天)[^。；;\n]{0,12}(?:用|使用)[^。；;\n]{0,8})", text)
        if usage_match:
            self._set_attr(attrs, sources, "usage_method", usage_match.group(1), "rule", 0.85, usage_match.group(1))

        foaming_terms = [
            "\u8d77\u6ce1", "\u6ce1\u6cab", "\u6ce1\u6ce1", "\u7ef5\u5bc6",
            "\u4e30\u5bcc\u6ce1\u6cab", "\u6613\u8d77\u6ce1", "\u4f4e\u6ce1", "\u65e0\u6ce1",
        ]
        matched_foaming = [term for term in foaming_terms if term in text]
        if matched_foaming:
            foaming_value = "\u9875\u9762\u63cf\u8ff0\u5305\u542b" + "\u3001".join(matched_foaming) + "\u7b49\u8d77\u6ce1\u76f8\u5173\u5356\u70b9"
            self._set_attr(attrs, sources, "foaming", foaming_value, "rule", 0.8, goods_name)

        return attrs, sources

    async def _extract_attributes_by_llm(
        self,
        list_product: Dict[str, Any],
        detail_product: Dict[str, Any],
        rule_attrs: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """LLM 只补结构化字段，不直接生成最终客服话术。"""
        model_name = get_config("llm.model_name", "gpt-4o")
        api_key = get_config("llm.api_key", "")
        api_base = get_config("llm.api_base", None)

        if not api_key:
            return {}, {}

        client = AsyncOpenAI(api_key=api_key, base_url=api_base, timeout=120.0)
        specifications = self._normalize_specifications(detail_product.get("specifications", []))

        system_prompt = """你是电商商品知识结构化抽取器。
只能根据输入的商品标题、价格、规格、详情和图片信息抽取字段，禁止编造。
没有明确依据的字段必须返回空字符串或空数组。
输出必须是 JSON 对象，字段为：
brand, ingredients, usage_method, usage_duration, foaming, skin_type, effect, shelf_life, warnings。
每个字段的格式：
{"value": "", "confidence": 0.0, "evidence": ""}
effect 和 warnings 的 value 可以是数组。"""

        user_content: List[Dict[str, Any]] = [{
            "type": "text",
            "text": f"""商品名称: {list_product.get('goods_name')}
商品价格: {list_product.get('price')}
已售数量: {list_product.get('sold_quantity')}
规格: {json.dumps(specifications, ensure_ascii=False)}
规则已抽取字段: {json.dumps(rule_attrs, ensure_ascii=False)}
""",
        }]
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            data = json.loads((response.choices[0].message.content or "{}").strip())
            attrs: Dict[str, Any] = {}
            sources: Dict[str, Any] = {}
            for key, item in data.items():
                if not isinstance(item, dict):
                    continue
                value = item.get("value")
                confidence = float(item.get("confidence") or 0)
                evidence = item.get("evidence") or ""
                if value not in (None, "", []) and confidence >= 0.55:
                    attrs[key] = value
                    sources[key] = self._source("llm", confidence, evidence)
            return attrs, sources
        except Exception as e:
            logger.warning(f"LLM结构化属性抽取失败，使用规则结果: {e}")
            return {}, {}

    def _build_product_extract_text(
        self,
        list_product: Dict[str, Any],
        detail_product: Dict[str, Any],
    ) -> str:
        """Build one normalized text block used by LLM extraction and evidence checks."""
        parts = [
            f"商品标题: {list_product.get('goods_name') or ''}",
            f"商品价格: {list_product.get('price') or ''}",
            f"已售数量: {list_product.get('sold_quantity') or ''}",
        ]
        for key in ("category", "goods_category", "cat_name", "desc", "description", "detail", "content"):
            value = detail_product.get(key)
            if value:
                parts.append(f"{key}: {value}")
        specs = self._normalize_specifications(detail_product.get("specifications", []))
        if specs:
            parts.append(f"规格列表: {json.dumps(specs, ensure_ascii=False)}")
        raw_text = detail_product.get("raw_text") or detail_product.get("extra_text") or detail_product.get("extracted_content")
        if raw_text:
            parts.append(f"详情文本: {raw_text}")
        return "\n".join(str(part) for part in parts if part)

    def _build_llm_first_extract_prompt(self, product_text: str) -> tuple[str, str]:
        system_prompt = """你是电商客服商品知识结构化抽取器。

你的任务是把商品信息抽取成客服系统可检索的结构化字段。

严格规则：
1. 只能根据输入文本抽取，禁止编造。
2. 每个非空字段都必须给出 evidence，evidence 必须是输入文本中的原文片段。
3. 没有明确证据的字段，value 必须为空字符串或空数组，confidence 必须为 0。
4. 主商品类目优先级：商品分类 > 商品标题主词 > 规格。
5. 商品分类如果是多级路径，优先抽取末级叶子类目。
6. sku_options 保留所有规格/款式；sku_summary 选择最常规的单件规格，例如 1瓶、90ML。
7. 输出必须是合法 JSON 对象，不要输出解释文字。

字段：
category 主商品类目；brand 品牌；sku_options 规格/款式数组；sku_summary 默认/核心规格；
ingredients 成分/材质；usage_method 使用方法；usage_duration 可使用时长；
foaming 起泡情况；suitable_age 适用年龄；skin_type 适用肤质；fragrance 香味；
effect 功效卖点数组；shelf_life 保质期；warnings 注意事项数组；accessories 赠品/附属品数组。

输出格式必须完全类似：
{
  "category": {"value": "", "confidence": 0.0, "evidence": ""},
  "brand": {"value": "", "confidence": 0.0, "evidence": ""},
  "sku_options": {"value": [], "confidence": 0.0, "evidence": ""},
  "sku_summary": {"value": "", "confidence": 0.0, "evidence": ""},
  "ingredients": {"value": "", "confidence": 0.0, "evidence": ""},
  "usage_method": {"value": "", "confidence": 0.0, "evidence": ""},
  "usage_duration": {"value": "", "confidence": 0.0, "evidence": ""},
  "foaming": {"value": "", "confidence": 0.0, "evidence": ""},
  "suitable_age": {"value": "", "confidence": 0.0, "evidence": ""},
  "skin_type": {"value": "", "confidence": 0.0, "evidence": ""},
  "fragrance": {"value": "", "confidence": 0.0, "evidence": ""},
  "effect": {"value": [], "confidence": 0.0, "evidence": ""},
  "shelf_life": {"value": "", "confidence": 0.0, "evidence": ""},
  "warnings": {"value": [], "confidence": 0.0, "evidence": ""},
  "accessories": {"value": [], "confidence": 0.0, "evidence": ""}
}"""
        user_prompt = f"请抽取以下商品信息：\n\n{product_text}"
        return system_prompt, user_prompt

    def _json_from_llm_content(self, content: str) -> Dict[str, Any]:
        text = (content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.S)
            if not match:
                raise
            return json.loads(match.group(0))

    def _evidence_in_text(self, evidence: Any, product_text: str) -> bool:
        if not evidence:
            return False
        evidence_text = str(evidence).strip()
        if not evidence_text:
            return False
        if evidence_text in product_text:
            return True
        compact_product = re.sub(r"\s+", "", product_text)
        compact_evidence = re.sub(r"\s+", "", evidence_text)
        return bool(compact_evidence and compact_evidence in compact_product)

    def _coerce_attr_value(self, key: str, value: Any) -> Any:
        list_fields = {"effect", "warnings", "sku_options", "accessories"}
        if key in list_fields:
            if isinstance(value, list):
                cleaned: List[str] = []
                for item in value:
                    if isinstance(item, dict):
                        item_value = (
                            item.get("款式")
                            or item.get("规格")
                            or item.get("value")
                            or item.get("name")
                            or ""
                        )
                    else:
                        item_value = item
                    item_text = str(item_value).strip()
                    if item_text:
                        cleaned.append(item_text)
                return cleaned
            if value in (None, ""):
                return []
            return [str(value).strip()]
        if isinstance(value, list):
            return "、".join(str(item).strip() for item in value if str(item).strip())
        return "" if value is None else str(value).strip()

    def _validate_llm_attribute_payload(
        self,
        data: Dict[str, Any],
        product_text: str,
    ) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        attrs: Dict[str, Any] = {}
        sources: Dict[str, Any] = {}
        rejected: Dict[str, Any] = {}
        for key, item in data.items():
            if key not in PRODUCT_LLM_FIELDS or not isinstance(item, dict):
                continue
            value = self._coerce_attr_value(key, item.get("value"))
            confidence = float(item.get("confidence") or 0)
            evidence = str(item.get("evidence") or "").strip()
            if value in (None, "", []) or confidence < 0.55:
                continue
            value_evidence_ok = False
            if isinstance(value, list):
                value_evidence_ok = any(str(item).strip() and str(item).strip() in product_text for item in value)
            else:
                value_evidence_ok = bool(str(value).strip() and str(value).strip() in product_text)
            if not self._evidence_in_text(evidence, product_text) and not value_evidence_ok:
                rejected[key] = {
                    "value": value,
                    "confidence": confidence,
                    "evidence": evidence,
                    "reason": "evidence_not_found",
                }
                continue
            attrs[key] = value
            sources[key] = self._source("llm", confidence, evidence)
        return attrs, sources, rejected

    def _merge_llm_first_attributes(
        self,
        llm_attrs: Dict[str, Any],
        llm_sources: Dict[str, Any],
        rule_attrs: Dict[str, Any],
        rule_sources: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        attrs = dict(DEFAULT_PRODUCT_ATTRIBUTES)
        sources: Dict[str, Any] = {}
        for key in attrs:
            llm_value = llm_attrs.get(key)
            rule_value = rule_attrs.get(key)
            llm_conf = (llm_sources.get(key) or {}).get("confidence", 0)
            rule_conf = (rule_sources.get(key) or {}).get("confidence", 0)
            if key in {"category", "sku_options", "sku_summary"} and rule_value not in (None, "", []) and rule_conf >= 0.75:
                attrs[key] = rule_value
                sources[key] = rule_sources[key]
            elif llm_value not in (None, "", []) and llm_conf >= 0.55:
                attrs[key] = llm_value
                sources[key] = llm_sources[key]
            elif rule_value not in (None, "", []) and rule_conf >= 0.75:
                attrs[key] = rule_value
                sources[key] = rule_sources[key]
            else:
                sources[key] = self._source("missing", 0.0, "")
        self._normalize_final_attributes(attrs, sources)
        return attrs, sources

    def _normalize_final_attributes(self, attrs: Dict[str, Any], sources: Dict[str, Any]) -> None:
        category = str(attrs.get("category") or "")
        category_aliases = [
            ("防晒霜", ("防晒霜", "防晒")),
            ("素颜霜", ("素颜霜", "面部素颜霜")),
            ("湿敷棉", ("湿敷棉", "化妆棉", "棉片")),
            ("洗脸巾", ("洗脸巾", "棉柔巾", "柔纸巾")),
            ("卸妆水", ("卸妆水", "卸妆乳")),
            ("化妆刷", ("化妆刷",)),
            ("洗面奶", ("洗面奶", "洁面乳", "洁面")),
            ("香水", ("香水", "香氛")),
        ]
        for normalized, terms in category_aliases:
            if any(term in category for term in terms):
                if category != normalized:
                    attrs["category"] = normalized
                    old_source = sources.get("category") or self._source("normalizer", 0.8, category)
                    sources["category"] = {
                        **old_source,
                        "normalized_from": category,
                    }
                break

    async def _extract_attributes_llm_first(
        self,
        list_product: Dict[str, Any],
        detail_product: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """LLM-first extraction with evidence validation and rule fallback."""
        rule_attrs, rule_sources = self._extract_attributes_by_rules(list_product, detail_product)
        model_name = get_config("llm.model_name", "gpt-4o")
        api_key = get_config("llm.api_key", "")
        api_base = get_config("llm.api_base", None)
        if not api_key:
            return self._merge_product_attributes(rule_attrs, rule_sources, {}, {})

        product_text = self._build_product_extract_text(list_product, detail_product)
        system_prompt, user_prompt = self._build_llm_first_extract_prompt(product_text)
        client = AsyncOpenAI(api_key=api_key, base_url=api_base, timeout=120.0)
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            raw_content = response.choices[0].message.content or "{}"
            data = self._json_from_llm_content(raw_content)
            llm_attrs, llm_sources, rejected = self._validate_llm_attribute_payload(data, product_text)
            if rejected:
                logger.info(
                    f"LLM商品字段证据校验丢弃: goods_id={list_product.get('goods_id')}, fields={list(rejected.keys())}"
                )
            return self._merge_llm_first_attributes(llm_attrs, llm_sources, rule_attrs, rule_sources)
        except Exception as e:
            logger.warning(f"LLM-first商品结构化抽取失败，回退规则链路: {e}")
            return self._merge_product_attributes(rule_attrs, rule_sources, {}, {})

    async def debug_extract_product_attributes(
        self,
        list_product: Dict[str, Any],
        detail_product: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run the extraction chain without writing MySQL or Qdrant."""
        product_text = self._build_product_extract_text(list_product, detail_product)
        rule_attrs, rule_sources = self._extract_attributes_by_rules(list_product, detail_product)
        model_name = get_config("llm.model_name", "gpt-4o")
        api_key = get_config("llm.api_key", "")
        api_base = get_config("llm.api_base", None)
        raw_llm_content = ""
        llm_attrs: Dict[str, Any] = {}
        llm_sources: Dict[str, Any] = {}
        rejected: Dict[str, Any] = {}
        if api_key:
            system_prompt, user_prompt = self._build_llm_first_extract_prompt(product_text)
            client = AsyncOpenAI(api_key=api_key, base_url=api_base, timeout=120.0)
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            raw_llm_content = response.choices[0].message.content or "{}"
            data = self._json_from_llm_content(raw_llm_content)
            llm_attrs, llm_sources, rejected = self._validate_llm_attribute_payload(data, product_text)
        attrs, sources = self._merge_llm_first_attributes(llm_attrs, llm_sources, rule_attrs, rule_sources)
        return {
            "input_text": product_text,
            "rule_attrs": rule_attrs,
            "rule_sources": rule_sources,
            "raw_llm_content": raw_llm_content,
            "validated_llm_attrs": llm_attrs,
            "validated_llm_sources": llm_sources,
            "rejected_llm_fields": rejected,
            "final_attrs": attrs,
            "final_sources": sources,
            "rendered_context": self._render_product_context(list_product, detail_product, attrs),
        }

    def _merge_product_attributes(
        self,
        rule_attrs: Dict[str, Any],
        rule_sources: Dict[str, Any],
        llm_attrs: Dict[str, Any],
        llm_sources: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        attrs = dict(DEFAULT_PRODUCT_ATTRIBUTES)
        sources: Dict[str, Any] = {}
        for key in attrs:
            rule_value = rule_attrs.get(key)
            llm_value = llm_attrs.get(key)
            rule_conf = (rule_sources.get(key) or {}).get("confidence", 0)
            llm_conf = (llm_sources.get(key) or {}).get("confidence", 0)
            if rule_value not in (None, "", []) and rule_conf >= 0.75:
                attrs[key] = rule_value
                sources[key] = rule_sources[key]
            elif llm_value not in (None, "", []) and llm_conf >= 0.55:
                attrs[key] = llm_value
                sources[key] = llm_sources[key]
            else:
                sources[key] = self._source("missing", 0.0, "")
        self._normalize_final_attributes(attrs, sources)
        return attrs, sources

    def _render_product_context(
        self,
        list_product: Dict[str, Any],
        detail_product: Dict[str, Any],
        attrs: Dict[str, Any],
    ) -> str:
        """从结构化属性渲染 LLM 兜底上下文。"""
        lines = [f"# {list_product.get('goods_name')}"]
        field_labels = [
            ("价格", list_product.get("price")),
            ("类目", attrs.get("category")),
            ("规格", attrs.get("sku_summary")),
            ("品牌", attrs.get("brand")),
            ("成分/材质", attrs.get("ingredients")),
            ("使用方法", attrs.get("usage_method")),
            ("使用时长", attrs.get("usage_duration")),
            ("起泡情况", attrs.get("foaming")),
            ("适用年龄", attrs.get("suitable_age")),
            ("适用肤质", attrs.get("skin_type")),
            ("香味", attrs.get("fragrance")),
            ("保质期", attrs.get("shelf_life")),
        ]
        for label, value in field_labels:
            if value:
                lines.append(f"{label}: {value}")
        if attrs.get("effect"):
            lines.append(f"功效: {'、'.join(attrs.get('effect') if isinstance(attrs.get('effect'), list) else [str(attrs.get('effect'))])}")
        if attrs.get("warnings"):
            lines.append(f"注意事项: {'、'.join(attrs.get('warnings') if isinstance(attrs.get('warnings'), list) else [str(attrs.get('warnings'))])}")
        if attrs.get("sku_options"):
            value = attrs.get("sku_options")
            lines.append(f"可选规格: {'、'.join(value if isinstance(value, list) else [str(value)])}")
        if attrs.get("accessories"):
            value = attrs.get("accessories")
            lines.append(f"赠品/附属品: {'、'.join(value if isinstance(value, list) else [str(value)])}")
        specs = self._normalize_specifications(detail_product.get("specifications", []))
        if specs:
            lines.append(f"原始规格: {json.dumps(specs, ensure_ascii=False)[:500]}")
        return "\n".join(lines)

    def _upsert_product_attribute_vectors(
        self,
        shop_id: int,
        goods_id: int,
        attrs: Dict[str, Any],
        sources: Dict[str, Any],
    ) -> None:
        """把非空属性字段写入 Qdrant 当前商品语义片段。"""
        field_to_sub_intent = {
            "usage_duration": "usage_duration",
            "usage_method": "usage_method",
            "foaming": "foaming",
            "ingredients": "ingredient",
            "suitable_age": "age_safety",
            "sku_summary": "sku_spec",
            "sku_options": "sku_spec",
            "fragrance": "fragrance",
            "effect": "product_attribute",
            "warnings": "product_attribute",
            "skin_type": "product_attribute",
            "accessories": "product_attribute",
        }
        for field_name, sub_intent in field_to_sub_intent.items():
            value = attrs.get(field_name)
            if value in (None, "", []):
                continue
            content = "、".join(value) if isinstance(value, list) else str(value)
            source = (sources.get(field_name) or {}).get("source", "product_sync")
            qdrant_manager.upsert_product_attribute_chunk(
                shop_id=str(shop_id),
                goods_id=str(goods_id),
                field_name=field_name,
                sub_intent=sub_intent,
                content=content,
                source=source,
                knowledge_version=PRODUCT_ATTRIBUTE_SCHEMA_VERSION,
            )

    async def _extract_product_knowledge(
        self,
        list_product: Dict[str, Any],
        detail_product: Dict[str, Any],
    ) -> str:
        """
        调用LLM提取产品知识

        Args:
            list_product: 商品列表中的商品信息
            detail_product: 商品详情信息

        Returns:
            LLM提取的产品知识文本
        """
        # 读取LLM配置
        model_name = get_config("llm.model_name", "gpt-4o")
        api_key = get_config("llm.api_key", "")
        api_base = get_config("llm.api_base", None)

        if not api_key:
            logger.warning("LLM API key not configured, returning basic info only")
            return self._format_basic_info(list_product, detail_product)

        # 创建客户端
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=120.0,
        )

        # 构建prompt
        specifications = self._normalize_specifications(detail_product.get("specifications", []))

        system_prompt = """你是一个电商产品信息提取助手。请根据提供的商品信息和商品图片，提取详细的产品知识，方便客服回答顾客问题。

请务必先从商品名称和描述中提取以下独立字段，然后再生成其他内容：

请输出 JSON 格式，包含以下字段：
{
  "brand": "品牌（从商品名称或描述中提取，如"葵花"、"同仁堂"等）",
  "origin": "产地（从描述中提取，如"中国广东"、"日本"等）",
  "ingredients": "产品成分/材料/主要原料（从描述中提取，如"草本成分"、"植物精油"等）",
  "spec_quantity": "规格/数量/包装规格（从描述中提取，如"1盒8贴"、"50g/瓶"等）",
  "suitable_age": "适用年龄（从描述中提取，如"儿童成人通用"、"3岁以上"等）",
  "shelf_life": "保质期/有效期（从描述中提取，如"24个月"、"3年"等）",
  "description": "商品整体描述，包含卖点、特点、材质、用途等信息",
  "key_points": ["卖点1", "卖点2", ...],
  "usage": "使用方法或注意事项（如果有）",
  "faq": [{"question": "常见问题", "answer": "答案"}, ...]
}

重要提示：
1. 请优先从商品名称和描述文本中提取品牌、成分、规格、适用年龄等信息
2. 如果某个信息已经在描述中提到，请务必提取到对应的独立字段中
3. 如果无法分析图片，只基于文本信息提取即可
4. 如果某个信息确实无法提取，对应字段留空字符串"""

        user_content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": f"""商品名称: {list_product.get('goods_name')}
商品价格: {list_product.get('price')}
已售数量: {list_product.get('sold_quantity')}
规格: {json.dumps(specifications, ensure_ascii=False)}
"""
            }
        ]

        # 如果有图片URL，添加图片
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content.strip()
            logger.debug(f"LLM输出: {content}")

            # 尝试解析JSON
            try:
                data = json.loads(content)
                # 记录提取到的规格信息
                logger.debug(f"提取到的规格字段 - brand: {data.get('brand')}, origin: {data.get('origin')}, ingredients: {data.get('ingredients')}, spec_quantity: {data.get('spec_quantity')}, suitable_age: {data.get('suitable_age')}, shelf_life: {data.get('shelf_life')}")

                # 格式化输出
                output_parts = [f"# {list_product.get('goods_name')}"]
                output_parts.append("")
                # 产品规格信息
                spec_info = []
                if data.get("brand") and data["brand"].strip():
                    spec_info.append(f"- **品牌**: {data['brand']}")
                if data.get("origin") and data["origin"].strip():
                    spec_info.append(f"- **产地**: {data['origin']}")
                if data.get("ingredients") and data["ingredients"].strip():
                    spec_info.append(f"- **产品成分**: {data['ingredients']}")
                if data.get("spec_quantity") and data["spec_quantity"].strip():
                    spec_info.append(f"- **规格/数量**: {data['spec_quantity']}")
                if data.get("suitable_age") and data["suitable_age"].strip():
                    spec_info.append(f"- **适用年龄**: {data['suitable_age']}")
                if data.get("shelf_life") and data["shelf_life"].strip():
                    spec_info.append(f"- **保质期**: {data['shelf_life']}")
                if spec_info:
                    output_parts.append("## 产品规格")
                    output_parts.extend(spec_info)
                    output_parts.append("")
                if data.get("description"):
                    output_parts.append("## 产品描述")
                    output_parts.append(data["description"])
                    output_parts.append("")
                if data.get("key_points") and isinstance(data["key_points"], list):
                    output_parts.append("## 产品卖点")
                    for i, point in enumerate(data["key_points"], 1):
                        output_parts.append(f"{i}. {point}")
                    output_parts.append("")
                if data.get("usage"):
                    output_parts.append("## 使用说明")
                    output_parts.append(data["usage"])
                    output_parts.append("")
                if data.get("faq") and isinstance(data["faq"], list):
                    output_parts.append("## 常见问题")
                    for faq in data["faq"]:
                        output_parts.append(f"**Q:** {faq.get('question')}")
                        output_parts.append(f"**A:** {faq.get('answer')}")
                        output_parts.append("")

                result = "\n".join(output_parts).strip()
                return result

            except json.JSONDecodeError:
                # 如果解析失败，返回原始内容
                logger.warning(f"LLM输出不是合法JSON，返回原始内容: {content[:100]}...")
                return content

        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            # 降级返回基本信息
            return self._format_basic_info(list_product, detail_product)

    def _format_basic_info(
        self,
        list_product: Dict[str, Any],
        detail_product: Dict[str, Any],
    ) -> str:
        """LLM调用失败时，格式化基本信息"""
        output = [f"# {list_product.get('goods_name')}"]
        output.append("")
        if list_product.get("price"):
            output.append(f"**价格**: {list_product.get('price')}")
        if list_product.get("sold_quantity"):
            output.append(f"**已售**: {list_product.get('sold_quantity')} 件")
        specs = self._normalize_specifications(detail_product.get("specifications", []))
        if specs:
            output.append("")
            output.append("**规格信息**:")
            for spec in specs:
                output.append(f"- {spec}")
        return "\n".join(output).strip()
