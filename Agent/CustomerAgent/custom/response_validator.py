"""
V3.0 Response Validator

Validates LLM responses before sending to users.
Implements rules for SKU preservation, empty field handling, medical claims, price inference, and human requests.
"""
import re
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of response validation."""
    valid: bool
    reason: str
    fallback_type: str


# SKU synonym mapping for detecting rewrites
SKU_SYNONYM_MAP = {
    "一瓶": ["1瓶", "单瓶"],
    "1瓶": ["一瓶", "单瓶"],
    "2瓶": ["两瓶", "二瓶"],
    "3瓶": ["三瓶"],
}

# Field keyword mapping for empty field validation
FIELD_KEYWORDS_MAP = {
    ("香味", "味道", "香型"): "fragrance",
    ("成分", "材质", "原料"): "ingredients",
    ("使用方法", "怎么用", "如何用"): "usage_method",
    ("能用多久", "使用时长", "一瓶用多久", "一瓶能用多久"): "usage_duration",
    ("适用人群", "适合年龄", "小孩", "儿童", "12岁", "几岁"): "suitable_age",
    ("保质期", "有效期"): "shelf_life",
    ("起泡", "泡沫"): "foaming",
    ("孕妇", "怀孕"): "suitable_age",  # Special handling needed
}

# Medical claim keywords
MEDICAL_KEYWORDS = [
    "治疗", "治愈", "根治", "药效", "疗效",
    "能治", "可以治疗", "疗效显著", "根治不复发"
]

# Human request keywords
HUMAN_KEYWORDS = [
    "人工客服", "转人工", "人工服务",
    "接人工", "找人工", "人工"
]

# Price query keywords
PRICE_KEYWORDS = ["多少钱", "价格", "几块", "几元", "优惠", "便宜", "划算", "实惠", "性价比"]

# Face/face use keywords
FACE_KEYWORDS = ["脸", "脸部", "面部", "喷脸", "涂脸", "用在脸上"]

# Comparison claims that should always fail
COMPARISON_CLAIMS = ["最划算", "最优惠", "最便宜", "性价比最高", "最实惠"]

# Uncertain expressions for empty field handling
UNCERTAIN_EXPRESSIONS = [
    "不确定", "不清楚", "不知道",
    "建议咨询人工客服", "请咨询人工客服",
    "建议咨询人工", "请咨询人工",
    "暂未标注", "未标注",
    "页面未标注", "页面暂未标注"
]

# Fallback templates
FALLBACK_TEMPLATES = {
    "template_uncertain": "这个信息我不确定,建议您咨询人工客服。",
    "template_risk_medical": "这个商品不是药品,不能替代医疗治疗,如有健康问题请咨询医生。",
    "template_risk_commitment": "商品效果因人而异,无法做绝对承诺。",
    "template_price": "请以商品页面实际价格为准。",
    "template_human": "正在为您转接人工客服,请稍候...",
}


def validate_response(response_text: str, product_json: dict, user_query: str) -> ValidationResult:
    """
    Main validation function that checks all rules.

    Args:
        response_text: LLM generated response
        product_json: Product structured JSON
        user_query: User's original query

    Returns:
        ValidationResult with valid, reason, and fallback_type
    """
    # Add query to product_json for reference in validation
    product_json_with_query = {**product_json, "_query": user_query}

    # 1. Human request detection (highest priority)
    result = detect_human_request(user_query)
    if not result.valid:
        return result

    # 2. SKU original text validation
    result = validate_sku_original_text(response_text, product_json_with_query)
    if not result.valid:
        return result

    # 3. Empty field fabrication validation
    result = validate_empty_field(response_text, product_json, user_query)
    if not result.valid:
        return result

    # 4. Face use validation
    result = validate_face_use(response_text, product_json, user_query)
    if not result.valid:
        return result

    # 5. Medical claim validation
    result = validate_medical_claim(response_text)
    if not result.valid:
        return result

    # 6. Price inference validation
    result = validate_price_inference(response_text, product_json, user_query)
    if not result.valid:
        return result

    # All validations passed
    return ValidationResult(valid=True, reason="", fallback_type="")


def detect_human_request(user_query: str) -> ValidationResult:
    """Detect human customer service request."""
    for keyword in HUMAN_KEYWORDS:
        if keyword in user_query:
            return ValidationResult(
                valid=False,
                reason="用户请求人工客服",
                fallback_type="template_human"
            )
    return ValidationResult(valid=True, reason="", fallback_type="")


def validate_sku_original_text(response_text: str, product_json: dict) -> ValidationResult:
    """Validate SKU text preservation."""
    # Extract SKU originals
    sku_list = []
    if product_json.get("sku_summary"):
        sku_list.append(product_json["sku_summary"])
    if product_json.get("sku_options"):
        sku_list.extend(product_json["sku_options"])

    if not sku_list:
        return ValidationResult(valid=True, reason="", fallback_type="")

    # Check each SKU option for rewrite violations
    for sku_original in sku_list:
        # Check if response contains this SKU's synonym but not the original
        synonyms = SKU_SYNONYM_MAP.get(sku_original, [])
        for synonym in synonyms:
            if synonym in response_text and sku_original not in response_text:
                return ValidationResult(
                    valid=False,
                    reason=f"SKU改写:回复包含'{synonym}'但未包含原文'{sku_original}'",
                    fallback_type="template_uncertain"
                )

    # For specification queries, check if all SKU options are present
    # This ensures responses like "有一瓶、两瓶可选" fail when missing "2瓶" original
    user_query = product_json.get("_query", "")
    spec_keywords = ["规格", "款式", "几瓶", "有哪些规格", "有什么规格", "规格有哪些"]
    is_spec_query = any(kw in user_query for kw in spec_keywords)

    if is_spec_query and product_json.get("sku_options"):
        for sku_original in product_json["sku_options"]:
            if sku_original not in response_text:
                # For spec queries, missing any SKU original should fail
                return ValidationResult(
                    valid=False,
                    reason=f"SKU原文缺失:回复缺少原文'{sku_original}'",
                    fallback_type="template_uncertain"
                )

    return ValidationResult(valid=True, reason="", fallback_type="")


def validate_empty_field(response_text: str, product_json: dict, user_query: str) -> ValidationResult:
    """Validate empty field not fabricated."""
    # Identify which field the user is asking about
    target_field = None
    is_pregnancy_query = False

    for keywords, field in FIELD_KEYWORDS_MAP.items():
        if any(kw in user_query for kw in keywords):
            target_field = field
            # Special check for pregnancy queries
            if any(kw in keywords for kw in ["孕妇", "怀孕"]):
                is_pregnancy_query = True
            break

    if not target_field:
        return ValidationResult(valid=True, reason="", fallback_type="")

    # Special handling for pregnancy queries
    if is_pregnancy_query:
        # Check if suitable_age mentions pregnancy
        suitable_age = product_json.get("suitable_age", "")
        if suitable_age and ("孕妇" in suitable_age or "怀孕" in suitable_age):
            # Field covers pregnancy, allow response
            return ValidationResult(valid=True, reason="", fallback_type="")
        else:
            # Field doesn't cover pregnancy, must express uncertainty
            has_uncertain = any(expr in response_text for expr in UNCERTAIN_EXPRESSIONS)
            if not has_uncertain:
                return ValidationResult(
                    valid=False,
                    reason=f"空字段编造:'孕妇'信息未标注但回复确定回答",
                    fallback_type="template_uncertain"
                )
            return ValidationResult(valid=True, reason="", fallback_type="")

    # Check if field is empty
    field_value = product_json.get(target_field, "")
    is_empty = (
        field_value == "" or
        field_value == [] or
        field_value is None
    )

    if not is_empty:
        return ValidationResult(valid=True, reason="", fallback_type="")

    # Field is empty, check if response expresses uncertainty
    has_uncertain = any(expr in response_text for expr in UNCERTAIN_EXPRESSIONS)

    if not has_uncertain:
        return ValidationResult(
            valid=False,
            reason=f"空字段编造:'{target_field}'为空但回复未表达不确定",
            fallback_type="template_uncertain"
        )

    return ValidationResult(valid=True, reason="", fallback_type="")


def validate_face_use(response_text: str, product_json: dict, user_query: str) -> ValidationResult:
    """Validate face/face use queries."""
    # Check if user is asking about face use
    is_face_query = any(kw in user_query for kw in FACE_KEYWORDS)
    if not is_face_query:
        return ValidationResult(valid=True, reason="", fallback_type="")

    # Check if usage_method or warnings explicitly mentions face
    usage_method = product_json.get("usage_method", "")
    warnings = product_json.get("warnings", [])
    if isinstance(warnings, list):
        warnings_text = " ".join(warnings)
    else:
        warnings_text = str(warnings) if warnings else ""

    face_covered = (
        "脸" in usage_method or "面部" in usage_method or "脸部" in usage_method or
        "脸" in warnings_text or "面部" in warnings_text or "脸部" in warnings_text
    )

    if face_covered:
        # Field explicitly covers face use, allow response
        return ValidationResult(valid=True, reason="", fallback_type="")
    else:
        # Field doesn't cover face use, must express uncertainty
        has_uncertain = any(expr in response_text for expr in UNCERTAIN_EXPRESSIONS)
        if not has_uncertain:
            return ValidationResult(
                valid=False,
                reason=f"脸部使用未标注:回复确定回答脸部使用但商品信息未标注",
                fallback_type="template_uncertain"
            )
        return ValidationResult(valid=True, reason="", fallback_type="")


def validate_medical_claim(response_text: str) -> ValidationResult:
    """Validate no medical claims."""
    for keyword in MEDICAL_KEYWORDS:
        if keyword in response_text:
            # Check for negation (e.g., "不能治疗", "无法治疗")
            negation_words = ["不能", "无法", "不是", "没有", "不具备", "不可"]
            is_negation = any(neg in response_text for neg in negation_words)

            if not is_negation:
                return ValidationResult(
                    valid=False,
                    reason=f"医疗承诺:回复包含'{keyword}'",
                    fallback_type="template_risk_medical"
                )

    return ValidationResult(valid=True, reason="", fallback_type="")


def validate_price_inference(response_text: str, product_json: dict, user_query: str) -> ValidationResult:
    """Validate no price inference."""
    # First, check for comparison claims that should always fail
    for claim in COMPARISON_CLAIMS:
        if claim in response_text:
            return ValidationResult(
                valid=False,
                reason=f"价格比较承诺:回复包含'{claim}'",
                fallback_type="template_price"
            )

    # Check if user is asking about price
    is_price_query = any(kw in user_query for kw in PRICE_KEYWORDS)
    if not is_price_query:
        return ValidationResult(valid=True, reason="", fallback_type="")

    # Check if product has price info
    product_price = product_json.get("price", "")

    # If no price, check if response infers price
    if not product_price:
        price_patterns = [
            r"\d+元", r"\d+块", r"优惠\d+元",
            r"原价\d+", r"现价\d+", r"价格\d+",
        ]
        for pattern in price_patterns:
            if re.search(pattern, response_text):
                return ValidationResult(
                    valid=False,
                    reason="价格推断:商品无价格信息但回复包含价格",
                    fallback_type="template_price"
                )

    # If price exists, check if response quotes original price correctly
    if product_price:
        # Allow exact quotation of original price
        if product_price in response_text:
            return ValidationResult(valid=True, reason="", fallback_type="")

        # Check if response contains fabricated price not matching original
        price_patterns = [r"\d+\.?\d*元", r"\d+\.?\d*块"]
        for pattern in price_patterns:
            match = re.search(pattern, response_text)
            if match:
                extracted_price = match.group()
                # If extracted price doesn't match original, it's fabrication
                if extracted_price not in product_price and product_price not in extracted_price:
                    return ValidationResult(
                        valid=False,
                        reason=f"价格编造:回复价格'{extracted_price}'与原文'{product_price}'不符",
                        fallback_type="template_price"
                    )

    return ValidationResult(valid=True, reason="", fallback_type="")


def handle_fallback(fallback_type: str, product_json: dict | None = None, user_query: str | None = None) -> str:
    """
    Return fallback response based on validation failure type.

    Args:
        fallback_type: Type of fallback template
        product_json: Optional product context (not used in basic templates)
        user_query: Optional user query (not used in basic templates)

    Returns:
        Fallback response text
    """
    return FALLBACK_TEMPLATES.get(fallback_type, FALLBACK_TEMPLATES["template_uncertain"])