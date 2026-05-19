"""
配置管理中心 - UI 与底层配置的解耦层

职责：
- 封装 .env 文件读写（通过 python-dotenv）
- 封装 SQLite 提示词配置读写
- 提供统一的配置访问接口给 UI 层
- 实现 UI 与底层配置存储的物理隔离

V2.0 架构重构：斩断 P0 技术债
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv, set_key, find_dotenv

from core import settings
from utils.logger_loguru import get_logger

logger = get_logger("ConfigManager")


class ConfigManager:
    """
    配置管理器（单例模式）

    统一管理所有配置的读写，UI 层只能通过此类访问配置。
    """

    _instance: Optional['ConfigManager'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return

        # 项目根目录
        self._base_dir = Path(__file__).resolve().parent.parent
        self._env_file = self._base_dir / ".env"

        # 确保 .env 文件存在
        if not self._env_file.exists():
            self._env_file.touch()
            logger.info(f"已创建 .env 文件: {self._env_file}")

        # 加载环境变量
        load_dotenv(str(self._env_file), override=False)

        self._initialized = True
        logger.info("ConfigManager 初始化完成")

    # =========================================================================
    # .env 文件读写
    # =========================================================================

    def get_env(self, key: str, default: str = "") -> str:
        """
        获取环境变量

        Args:
            key: 环境变量名
            default: 默认值

        Returns:
            环境变量值
        """
        return os.getenv(key, default)

    def set_env(self, key: str, value: str) -> bool:
        """
        设置环境变量并写入 .env 文件

        Args:
            key: 环境变量名
            value: 环境变量值

        Returns:
            是否设置成功
        """
        try:
            # 写入 .env 文件
            set_key(str(self._env_file), key, str(value))

            # 更新内存中的环境变量
            os.environ[key] = str(value)

            logger.debug(f"环境变量已设置: {key}={value}")
            return True
        except Exception as e:
            logger.error(f"设置环境变量失败: {e}")
            return False

    def get_int(self, key: str, default: int = 0) -> int:
        """获取整数类型环境变量"""
        try:
            value = os.getenv(key)
            if value is None or value == "":
                return default
            return int(value)
        except (ValueError, TypeError):
            logger.warning(f"环境变量 {key} 不是有效的整数，使用默认值 {default}")
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔类型环境变量"""
        value = os.getenv(key, "").lower()
        if value in ("true", "1", "yes", "on"):
            return True
        elif value in ("false", "0", "no", "off", ""):
            return default
        return default

    # =========================================================================
    # LLM 配置
    # =========================================================================

    def get_llm_config(self) -> Dict[str, str]:
        """
        获取 LLM 配置

        Returns:
            包含 api_base, api_key, model_name 的字典
        """
        return {
            "api_base": self.get_env("LLM_API_BASE", settings.llm_api_base()),
            "api_key": self.get_env("LLM_API_KEY", settings.llm_api_key()),
            "model_name": self.get_env("LLM_MODEL_NAME", "doubao-seed-1-6-flash-250828"),
        }

    def set_llm_config(self, api_base: str, api_key: str, model_name: str) -> bool:
        """
        设置 LLM 配置

        Args:
            api_base: API 地址
            api_key: API 密钥
            model_name: 模型名称

        Returns:
            是否设置成功
        """
        success = True
        success &= self.set_env("LLM_API_BASE", api_base)
        success &= self.set_env("LLM_API_KEY", api_key)
        success &= self.set_env("LLM_MODEL_NAME", model_name)

        if success:
            logger.info("LLM 配置已更新")
        return success

    # =========================================================================
    # 本地模型配置
    # =========================================================================

    def get_local_model_config(self) -> Dict[str, Any]:
        """获取本地模型配置"""
        return {
            "enabled": self.get_bool("LOCAL_MODEL_ENABLED", True),
            "base_url": self.get_env("LOCAL_MODEL_BASE_URL", settings.local_model_base_url()),
            "model_name": self.get_env("LOCAL_MODEL_NAME", "customer-service"),
            "max_tokens": self.get_int("LOCAL_MODEL_MAX_TOKENS", 50),
            "temperature": float(self.get_env("LOCAL_MODEL_TEMPERATURE", "0.3")),
            "timeout": self.get_int("LOCAL_MODEL_TIMEOUT", 60),
        }

    def set_local_model_config(
        self,
        enabled: bool,
        base_url: str,
        model_name: str,
        max_tokens: int,
        temperature: float,
        timeout: int
    ) -> bool:
        """设置本地模型配置"""
        success = True
        success &= self.set_env("LOCAL_MODEL_ENABLED", "true" if enabled else "false")
        success &= self.set_env("LOCAL_MODEL_BASE_URL", base_url)
        success &= self.set_env("LOCAL_MODEL_NAME", model_name)
        success &= self.set_env("LOCAL_MODEL_MAX_TOKENS", str(max_tokens))
        success &= self.set_env("LOCAL_MODEL_TEMPERATURE", str(temperature))
        success &= self.set_env("LOCAL_MODEL_TIMEOUT", str(timeout))

        if success:
            logger.info("本地模型配置已更新")
        return success

    # =========================================================================
    # TTL 时间配置
    # =========================================================================

    def get_ttl_config(self) -> Dict[str, int]:
        """获取 TTL 时间配置"""
        return {
            "human_lock_ttl": self.get_int("HUMAN_LOCK_TTL", 240),
            "inference_lock_ttl": self.get_int("INFERENCE_LOCK_TTL", 10),
            "intent_cache_ttl": self.get_int("INTENT_CACHE_TTL", 600),
            "alert_cooldown_ttl": self.get_int("ALERT_COOLDOWN_TTL", 60),
            "ai_awakening_ttl": self.get_int("AI_AWAKENING_TTL", 30),
        }

    def set_ttl_config(
        self,
        human_lock_ttl: int,
        inference_lock_ttl: int,
        intent_cache_ttl: int,
        alert_cooldown_ttl: int,
        ai_awakening_ttl: int
    ) -> bool:
        """设置 TTL 时间配置"""
        success = True
        success &= self.set_env("HUMAN_LOCK_TTL", str(human_lock_ttl))
        success &= self.set_env("INFERENCE_LOCK_TTL", str(inference_lock_ttl))
        success &= self.set_env("INTENT_CACHE_TTL", str(intent_cache_ttl))
        success &= self.set_env("ALERT_COOLDOWN_TTL", str(alert_cooldown_ttl))
        success &= self.set_env("AI_AWAKENING_TTL", str(ai_awakening_ttl))

        if success:
            logger.info("TTL 配置已更新")
        return success

    # =========================================================================
    # 阈值配置
    # =========================================================================

    def get_threshold_config(self) -> Dict[str, Any]:
        """获取阈值配置"""
        return {
            "short_sentence_threshold": self.get_int("SHORT_SENTENCE_THRESHOLD", 5),
            "routing_local_max_length": self.get_int("ROUTING_LOCAL_MAX_LENGTH", 15),
            "routing_fallback_on_error": self.get_bool("ROUTING_FALLBACK_ON_ERROR", True),
        }

    def set_threshold_config(
        self,
        short_sentence_threshold: int,
        routing_local_max_length: int,
        routing_fallback_on_error: bool
    ) -> bool:
        """设置阈值配置"""
        success = True
        success &= self.set_env("SHORT_SENTENCE_THRESHOLD", str(short_sentence_threshold))
        success &= self.set_env("ROUTING_LOCAL_MAX_LENGTH", str(routing_local_max_length))
        success &= self.set_env("ROUTING_FALLBACK_ON_ERROR", "true" if routing_fallback_on_error else "false")

        if success:
            logger.info("阈值配置已更新")
        return success

    # =========================================================================
    # 业务时间配置
    # =========================================================================

    def get_business_hours(self) -> Dict[str, str]:
        """获取业务时间配置"""
        return {
            "start": self.get_env("BUSINESS_HOURS_START", "08:00"),
            "end": self.get_env("BUSINESS_HOURS_END", "23:00"),
        }

    def set_business_hours(self, start: str, end: str) -> bool:
        """设置业务时间配置"""
        success = True
        success &= self.set_env("BUSINESS_HOURS_START", start)
        success &= self.set_env("BUSINESS_HOURS_END", end)

        if success:
            logger.info("业务时间配置已更新")
        return success

    # =========================================================================
    # 提示词配置（存储在 SQLite）
    # =========================================================================

    def get_prompt_instructions(self, shop_id: str = "default") -> list:
        """
        获取店铺的提示词指令

        Args:
            shop_id: 店铺ID

        Returns:
            指令列表
        """
        try:
            from database.db_manager import db_manager

            key = f"shop:{shop_id}:prompt_instructions"
            row = db_manager.get_config(key)

            if row:
                instructions = json.loads(row["config_value"])
                logger.debug(f"从 SQLite 加载提示词指令: shop_id={shop_id}, count={len(instructions)}")
                return instructions

            return self._get_default_instructions()
        except Exception as e:
            logger.warning(f"获取提示词指令失败: {e}")
            return self._get_default_instructions()

    def set_prompt_instructions(self, instructions: list, shop_id: str = "default") -> bool:
        """
        设置店铺的提示词指令

        Args:
            instructions: 指令列表
            shop_id: 店铺ID

        Returns:
            是否设置成功
        """
        try:
            from database.db_manager import db_manager

            key = f"shop:{shop_id}:prompt_instructions"
            db_manager.set_config(key, json.dumps(instructions, ensure_ascii=False))

            logger.info(f"提示词指令已保存: shop_id={shop_id}, count={len(instructions)}")
            return True
        except Exception as e:
            logger.error(f"保存提示词指令失败: {e}")
            return False

    def _get_default_instructions(self) -> list:
        """获取默认提示词指令"""
        return [
            "1. 请用中文回复客户问题",
            "2. 当用户询问特定商品的信息、成分、使用方法、价格、规格等问题时，请优先使用 get_product_knowledge 工具获取商品详细知识",
            "3. 当用户询问售后政策、物流信息、退换货规则等非产品特定问题时，请使用 search_customer_service_knowledge 工具搜索客服知识",
            "4. 如果知识库中有相关信息，请根据知识库内容回答用户问题",
            "5. 如果知识库中没有相关信息，再根据已有知识回答或建议用户联系人工客服"
        ]

    # =========================================================================
    # 一级拦截与固定话术配置（存储在 SQLite）
    # =========================================================================

    def get_agent_reply_rules(self, shop_id: str = "default") -> Dict[str, Any]:
        """获取一级拦截层和模板回复规则。"""
        defaults = self._get_default_agent_reply_rules()
        try:
            from database.db_manager import db_manager

            key = f"shop:{shop_id}:agent_reply_rules"
            row = db_manager.get_config(key)
            if not row:
                return defaults

            saved = json.loads(row["config_value"])
            if not isinstance(saved, dict):
                return defaults
            return self._normalize_agent_reply_rules({**defaults, **saved})
        except Exception as e:
            logger.warning(f"获取一级拦截话术配置失败: {e}")
            return defaults

    def set_agent_reply_rules(self, rules: Dict[str, Any], shop_id: str = "default") -> bool:
        """保存一级拦截层和模板回复规则。"""
        try:
            from database.db_manager import db_manager

            key = f"shop:{shop_id}:agent_reply_rules"
            normalized = self._normalize_agent_reply_rules({
                **self._get_default_agent_reply_rules(),
                **(rules or {}),
            })
            db_manager.set_config(key, json.dumps(normalized, ensure_ascii=False))
            logger.info(f"一级拦截话术配置已保存: shop_id={shop_id}")
            return True
        except Exception as e:
            logger.error(f"保存一级拦截话术配置失败: {e}")
            return False

    def _normalize_agent_reply_rules(self, rules: Dict[str, Any]) -> Dict[str, Any]:
        """清洗 UI 传入的配置，避免空值覆盖可用默认值。"""
        defaults = self._get_default_agent_reply_rules()
        normalized = dict(defaults)

        for key, default_value in defaults.items():
            value = (rules or {}).get(key, default_value)
            if isinstance(default_value, list):
                normalized[key] = self._normalize_text_list(value)
            else:
                text = str(value or "").strip()
                normalized[key] = text or default_value
        return normalized

    def _normalize_text_list(self, value: Any) -> list:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            parts = value.replace("，", ",").split(",")
            lines = []
            for part in parts:
                lines.extend(part.splitlines())
            return [line.strip() for line in lines if line.strip()]
        return []

    def _get_default_agent_reply_rules(self) -> Dict[str, Any]:
        """一级拦截和确定性模板的默认配置。"""
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
                "儿童", "孕妇", "能用", "可以用",
            ],
        }

    # =========================================================================
    # 路由关键词配置（存储在 SQLite）
    # =========================================================================

    def get_route_keywords(self, shop_id: str = "default") -> Dict[str, list]:
        """获取路由关键词配置。"""
        defaults = self._get_default_route_keywords()
        try:
            from database.db_manager import db_manager

            key = f"shop:{shop_id}:route_keywords"
            row = db_manager.get_config(key)
            if not row:
                return defaults

            saved = json.loads(row["config_value"])
            if not isinstance(saved, dict):
                return defaults
            return self._normalize_route_keywords({**defaults, **saved})
        except Exception as e:
            logger.warning(f"获取路由关键词配置失败: {e}")
            return defaults

    def set_route_keywords(self, keywords: Dict[str, Any], shop_id: str = "default") -> bool:
        """保存路由关键词配置。"""
        try:
            from database.db_manager import db_manager

            normalized = self._normalize_route_keywords({
                **self._get_default_route_keywords(),
                **(keywords or {}),
            })
            key = f"shop:{shop_id}:route_keywords"
            db_manager.set_config(key, json.dumps(normalized, ensure_ascii=False))
            logger.info(f"路由关键词配置已保存: shop_id={shop_id}")
            return True
        except Exception as e:
            logger.error(f"保存路由关键词配置失败: {e}")
            return False

    def _normalize_route_keywords(self, keywords: Dict[str, Any]) -> Dict[str, list]:
        defaults = self._get_default_route_keywords()
        return {
            key: self._normalize_text_list((keywords or {}).get(key, value)) or value
            for key, value in defaults.items()
        }

    def _get_default_route_keywords(self) -> Dict[str, list]:
        """路由关键词默认值。"""
        return {
            "redline": [
                "投诉", "举报", "工商局", "12315", "报警", "律师", "曝光",
                "欺诈", "骗子", "骗人", "黑店", "假货", "假", "仿品", "山寨",
                "质量问题", "过敏", "烂脸", "红肿", "疹子", "呼吸困难", "副作用",
                "中毒", "不适", "刺激", "垃圾", "差评", "退钱", "赔偿", "十倍",
                "不解决", "不退款", "不赔偿", "等着", "走着瞧", "朋友圈",
                "小红书", "媒体", "记者", "直播",
            ],
            "human_request": [
                "转人工", "人工客服", "人工", "真人客服", "真人", "找客服", "找人工",
                "客服呢", "人工呢", "有人处理", "有人管", "转售后", "转售后客服",
                "我要人工", "我要客服", "联系人工", "联系店家", "联系商家",
            ],
            "after_sales": [
                "退货", "换货", "退款", "退", "换", "漏液", "破损", "坏了", "坏",
                "破", "漏", "按不出", "喷不出", "堵住", "堵了", "变质", "异味",
                "发霉", "没收到", "丢件", "发错", "少发", "错发", "签收",
                "快递问题", "降价", "差价", "补差价", "不喜欢", "不合适",
                "不满意", "没效果", "没有效果", "没用", "没有用", "没味道",
                "没有味道", "不持久", "留香短", "留香太短", "几分钟就没",
                "一会儿就没", "效果差", "没什么效果",
            ],
            "pre_sale": [
                "多少钱", "价格", "优惠", "打折", "活动", "赠品", "会员", "折扣",
                "发什么快递", "快递", "发货", "包邮", "顺丰", "多久能到",
                "几天能到", "几天发货", "留香", "前调", "中调", "后调", "香调",
                "成分", "容量", "规格", "保质期", "适合", "孕妇", "敏感肌",
                "怎么用", "怎么喷", "喷哪里", "介绍一下", "介绍下",
            ],
            "recommend": [
                "推荐", "有什么", "好物", "随便", "看看", "哪个好", "选一个",
                "挑一个", "有好", "想买", "想看",
            ],
            "logistics": ["发货", "物流", "快递", "几天能到", "几天发货", "到货", "催发货"],
        }

    # =========================================================================
    # 统一配置更新接口
    # =========================================================================

    def update_config(self, config_data: Dict[str, Any]) -> bool:
        """
        统一配置更新接口

        Args:
            config_data: 配置数据字典，支持以下键：
                - llm: LLM 配置
                - local_model: 本地模型配置
                - ttl: TTL 配置
                - threshold: 阈值配置
                - business_hours: 业务时间配置
                - prompt: 提示词配置（需要 shop_id）
                - agent_reply_rules: 一级拦截和模板话术配置（需要 shop_id）

        Returns:
            是否更新成功
        """
        success = True

        # LLM 配置
        if "llm" in config_data:
            llm = config_data["llm"]
            success &= self.set_llm_config(
                api_base=llm.get("api_base", ""),
                api_key=llm.get("api_key", ""),
                model_name=llm.get("model_name", ""),
            )

        # 本地模型配置
        if "local_model" in config_data:
            lm = config_data["local_model"]
            success &= self.set_local_model_config(
                enabled=lm.get("enabled", True),
                base_url=lm.get("base_url", settings.local_model_base_url()),
                model_name=lm.get("model_name", "customer-service"),
                max_tokens=lm.get("max_tokens", 50),
                temperature=lm.get("temperature", 0.3),
                timeout=lm.get("timeout", 30),
            )

        # TTL 配置
        if "ttl" in config_data:
            ttl = config_data["ttl"]
            success &= self.set_ttl_config(
                human_lock_ttl=ttl.get("human_lock_ttl", 240),
                inference_lock_ttl=ttl.get("inference_lock_ttl", 10),
                intent_cache_ttl=ttl.get("intent_cache_ttl", 600),
                alert_cooldown_ttl=ttl.get("alert_cooldown_ttl", 60),
                ai_awakening_ttl=ttl.get("ai_awakening_ttl", 30),
            )

        # 阈值配置
        if "threshold" in config_data:
            threshold = config_data["threshold"]
            success &= self.set_threshold_config(
                short_sentence_threshold=threshold.get("short_sentence_threshold", 5),
                routing_local_max_length=threshold.get("routing_local_max_length", 15),
                routing_fallback_on_error=threshold.get("routing_fallback_on_error", True),
            )

        # 业务时间配置
        if "business_hours" in config_data:
            bh = config_data["business_hours"]
            success &= self.set_business_hours(
                start=bh.get("start", "08:00"),
                end=bh.get("end", "23:00"),
            )

        # 提示词配置
        if "prompt" in config_data:
            prompt = config_data["prompt"]
            shop_id = config_data.get("shop_id", "default")
            instructions = prompt.get("instructions", [])
            success &= self.set_prompt_instructions(instructions, shop_id)

        # 一级拦截和固定话术配置
        if "agent_reply_rules" in config_data:
            shop_id = config_data.get("shop_id", "default")
            success &= self.set_agent_reply_rules(config_data["agent_reply_rules"], shop_id)

        # 路由关键词配置
        if "route_keywords" in config_data:
            shop_id = config_data.get("shop_id", "default")
            success &= self.set_route_keywords(config_data["route_keywords"], shop_id)

        return success

    def get_all_config(self, shop_id: str = "default") -> Dict[str, Any]:
        """
        获取所有配置

        Args:
            shop_id: 店铺ID（用于获取提示词）

        Returns:
            完整配置字典
        """
        return {
            "llm": self.get_llm_config(),
            "local_model": self.get_local_model_config(),
            "ttl": self.get_ttl_config(),
            "threshold": self.get_threshold_config(),
            "business_hours": self.get_business_hours(),
            "prompt": {
                "instructions": self.get_prompt_instructions(shop_id)
            },
            "agent_reply_rules": self.get_agent_reply_rules(shop_id),
            "route_keywords": self.get_route_keywords(shop_id),
        }

# 全局单例
config_manager = ConfigManager()
