"""
LangGraph 状态定义模块

定义客服 Agent 的状态字典结构，用于图工作流的状态传递。
"""
from __future__ import annotations

from typing import TypedDict, List, Optional, Annotated, Literal
from operator import add


# 意图类型常量
class IntentType:
    """意图类型常量"""
    PRE_SALE = "pre_sale"           # 售前导购
    AFTER_SALES = "after_sales"     # 售后纠纷
    RECOMMEND = "recommend"         # 商品推荐（V2.0 新增）
    REDLINE = "redline"             # 高危红线
    LOGISTICS = "logistics"         # 订单物流
    GENERAL = "general"             # 通用店规
    UNKNOWN = "unknown"             # 未知意图


# 警报级别常量
class SubIntentType:
    NONE = "none"
    USAGE_METHOD = "usage_method"
    USAGE_DURATION = "usage_duration"
    AGE_SAFETY = "age_safety"
    SKU_SPEC = "sku_spec"
    FRAGRANCE = "fragrance"
    PRICE = "price"
    INGREDIENT = "ingredient"
    LOGISTICS_DELIVERY = "logistics_delivery"
    FOAMING = "foaming"
    PRODUCT_ATTRIBUTE = "product_attribute"
    PRODUCT_DISCOVERY = "product_discovery"


class RetrievalPolicy:
    """知识检索策略常量。意图只判断业务域，策略决定查什么数据。"""
    NONE = "none"
    CURRENT_PRODUCT = "current_product"
    PRODUCT_CANDIDATES = "product_candidates"
    CLARIFY_PRODUCT = "clarify_product"
    SHOP_KNOWLEDGE = "shop_knowledge"


class AlertLevel:
    """警报级别常量"""
    HIGH = "high"     # 高危警报（红线关键词：315、过敏、假货等）
    LOW = "low"       # 低危警报（普通转人工：图片、主动请求等）
    NONE = "none"     # 无警报


# 节点名称常量
class NodeName:
    """LangGraph 节点名称常量"""
    ROUTER = "node_router"
    RETRIEVER = "node_retriever"
    GENERATOR = "node_generator"
    HUMAN_FALLBACK = "node_human_fallback"


# 关键词集合（用于意图路由）- V2.0 大幅扩充版

# 红线关键词（最高优先级，命中即返回 redline）
REDLINE_KEYWORDS = frozenset({
    # 投诉举报类
    "投诉", "举报", "工商局", "12315", "报警", "律师", "曝光",
    "欺诈", "骗子", "骗人", "黑店",

    # 假货质量类
    "假货", "假", "仿品", "山寨", "质量问题",

    # 身体伤害类
    "过敏", "烂脸", "红肿", "疹子", "呼吸困难", "副作用",
    "中毒", "不适", "刺激",

    # 极端情绪类
    "垃圾", "差评", "退钱", "赔偿", "十倍",
    "不解决", "不退款", "不赔偿", "等着", "走着瞧",

    # 媒体曝光类
    "朋友圈", "小红书", "媒体", "记者", "直播"
})

# 主动请求人工关键词（普通转人工，低危提醒）
HUMAN_REQUEST_KEYWORDS = frozenset({
    "转人工", "人工客服", "人工", "真人客服", "真人", "找客服", "找人工",
    "客服呢", "人工呢", "有人处理", "有人管", "转售后", "转售后客服",
    "我要人工", "我要客服", "联系人工", "联系店家", "联系商家",
})

# 售后关键词（优先级高于售前）
AFTER_SALES_KEYWORDS = frozenset({
    # 退换货类
    "退货", "换货", "退款", "退", "换",

    # 质量问题类
    "漏液", "破损", "坏了", "坏", "破", "漏",
    "按不出", "喷不出", "堵住", "堵了",
    "变质", "异味", "发霉",

    # 物流问题类
    "没收到", "丢件", "发错", "少发", "错发",
    "签收", "快递问题",

    # 价格问题类
    "降价", "差价", "补差价",

    # 使用问题类
    "不喜欢", "不合适", "不满意",
    "没效果", "没有效果", "没用", "没有用", "没味道", "没有味道",
    "不持久", "留香短", "留香太短", "几分钟就没", "一会儿就没",
    "效果差", "没什么效果",
})

# 售前关键词
PRE_SALE_KEYWORDS = frozenset({
    # 价格活动类
    "多少钱", "价格", "优惠", "打折", "活动", "赠品",
    "会员", "折扣",

    # 物流咨询类
    "发什么快递", "快递", "发货", "包邮", "顺丰",
    "多久能到", "几天能到", "几天发货",

    # 产品咨询类
    "留香", "前调", "中调", "后调", "香调",
    "成分", "容量", "规格", "保质期",
    "适合", "孕妇", "敏感肌",

    # 使用咨询类
    "怎么用", "怎么喷", "喷哪里",

    # V2.0 新增：推荐意图关键词
    "推荐", "有什么", "好物", "随便", "看看",
    "哪个好", "选一个", "挑一个", "有好",
    "介绍一下", "介绍下", "想买", "想看",
})

# 售前负向关键词（出现这些词则不是售前）
NEGATIVE_PRE_SALE = frozenset({
    "退", "换", "坏", "破", "漏", "丢", "错"
})

# 推荐关键词（V2.0 新增）
RECOMMEND_KEYWORDS = frozenset({
    "推荐", "有什么", "好物", "随便", "看看",
    "哪个好", "选一个", "挑一个", "有好",
    "介绍一下", "介绍下", "想买", "想看",
})

# 物流关键词（V2.0 新增）
LOGISTICS_KEYWORDS = frozenset({
    "发货", "快递", "物流", "到哪了", "催",
    "几天能到", "什么时候发货", "发货了吗",
})

# 物流关键词（已合并到售前和售后）
LOGISTICS_KEYWORDS = frozenset({
    "发货", "物流", "快递", "几天能到", "几天发货", "到货", "催发货"
})


# 状态类型定义
class CustomerServiceState(TypedDict, total=False):
    """
    客服服务状态字典

    用于 LangGraph 图工作流的状态传递。

    字段说明：
    - session_id: 会话唯一标识
    - messages: 消息历史（支持累加）
    - current_intent: 当前意图
    - locked_goods_id: 锁定的商品ID
    - knowledge_context: 知识上下文
    - is_human_needed: 是否需要转人工
    - alert_level: 警报级别（high/low/none）
    - final_response: 最终回复
    - error_message: 错误信息
    - shop_id: 店铺ID
    - from_uid: 用户UID
    - user_query: 用户查询
    """
    session_id: str
    messages: Annotated[List[dict], add]
    current_intent: str
    sub_intent: str
    sub_intent_confidence: float
    sub_intent_terms: List[str]
    retrieval_policy: str
    entity_scope: str
    locked_goods_id: Optional[str]
    knowledge_context: str
    is_human_needed: bool
    alert_level: str  # "high" | "low" | "none"
    final_response: str
    error_message: Optional[str]
    shop_id: Optional[int]
    from_uid: Optional[str]
    user_query: str
