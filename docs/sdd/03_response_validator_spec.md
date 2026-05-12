# V3.0 回复校验器规格

## 版本信息
- 文档版本: 1.0
- 创建日期: 2026-05-12
- 目标：定义回复发送前的校验规则和兜底策略

---

## 1. 输入/输出定义

### 1.1 输入

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `response_text` | string | 是 | LLM 生成的回复文本 |
| `product_json` | dict | 是 | 当前商品的结构化 JSON（包含所有字段） |
| `user_query` | string | 是 | 用户原始查询（用于判断问题类型） |

### 1.2 输出

```python
{
    "valid": bool,  # 校验是否通过
    "reason": str,  # 失败原因（如"SKU改写"、"空字段编造"）
    "fallback_type": str  # 兜底类型（如"template_uncertain"、"template_risk"）
}
```

**字段说明**：
- `valid`：校验通过返回 `True`，失败返回 `False`
- `reason`：校验失败的具体原因，用于日志记录和调试
- `fallback_type`：推荐的兜底模板类型（校验失败时）

---

## 2. 校验规则清单

### 2.1 SKU 原文保持校验

**规则 ID**：`SKU_ORIGINAL_TEXT`

**目的**：防止 LLM 改写 SKU 规格原文

**校验逻辑**：
1. 从 `product_json` 中提取所有 SKU 原文：
   - `sku_summary`（默认规格）
   - `sku_options`（可选规格列表）
2. 在 `response_text` 中搜索 SKU 关键词
3. 如果发现 SKU 改写（如"1瓶"写成"一瓶"），返回校验失败

**示例**（以商品 JSON 实际值为准）：
```python
# 商品 JSON 示例1
{
    "sku_summary": "一瓶20ml",
    "sku_options": ["一瓶", "2瓶", "3瓶"]
}

# 合规回复
response_text = "有一瓶、2瓶、3瓶三种规格可选。"
# 校验通过（回复包含商品 JSON 原文）

# 违规回复
response_text = "有1瓶、两瓶、三瓶三种规格。"
# 校验失败：SKU 改写（"一瓶"原文被改写为"1瓶"）

# 商品 JSON 示例2
{
    "sku_summary": "1瓶20ml",
    "sku_options": ["1瓶", "2瓶", "3瓶"]
}

# 合规回复
response_text = "有1瓶、2瓶、3瓶三种规格可选。"
# 校验通过（回复包含商品 JSON 原文）
```

**伪代码**：
```python
def validate_sku_original_text(response_text, product_json):
    """校验 SKU 原文保持"""
    # 提取 SKU 原文列表
    sku_list = []
    if product_json.get("sku_summary"):
        sku_list.append(product_json["sku_summary"])
    if product_json.get("sku_options"):
        sku_list.extend(product_json["sku_options"])
    
    # 同义改写风险映射（示例，实际来自配置）
    # 用于检测：回复中出现同义表达但未包含原文
    # 示例配置：{"一瓶": ["1瓶", "单瓶"], "1瓶": ["一瓶", "单瓶"]}
    sku_synonym_map = load_sku_synonym_map_from_config()
    
    # 检查回复中是否包含 SKU 原文
    for sku_original in sku_list:
        if sku_original in response_text:
            # 回复包含原文，校验通过
            return {"valid": True, "reason": "", "fallback_type": ""}
    
    # 检查回复中是否只有同义改写但无原文
    for sku_original in sku_list:
        synonyms = sku_synonym_map.get(sku_original, [])
        for synonym in synonyms:
            if synonym in response_text and sku_original not in response_text:
                return {
                    "valid": False,
                    "reason": f"SKU改写：回复包含'{synonym}'但未包含原文'{sku_original}'",
                    "fallback_type": "template_uncertain"
                }
    
    return {"valid": True, "reason": "", "fallback_type": ""}
```

---

### 2.2 空字段编造校验

**规则 ID**：`EMPTY_FIELD_FORBIDDEN`

**目的**：防止 LLM 在商品字段为空时确定回答

**校验逻辑**：
1. 识别用户查询询问的字段（如"香味"、"成分"、"使用方法"）
2. 检查 `product_json` 中该字段是否为空/空数组
3. 如果字段为空，但回复中没有"不确定"/"建议咨询人工"等表达，返回校验失败

**示例**：
```python
# 商品 JSON
{
    "fragrance": "",  # 香味字段为空
    "ingredients": ""  # 成分字段为空
}

# 用户查询："这个有香味吗？"
# 合规回复
response_text = "这个信息我不确定，建议您咨询人工客服。"
# 校验通过

# 违规回复
response_text = "这款商品有茉莉香味。"
# 校验失败：空字段编造（香味字段为空却确定回答）
```

**伪代码**：
```python
def validate_empty_field(response_text, product_json, user_query):
    """校验空字段未编造"""
    # 字段映射：查询关键词 -> 商品 JSON 字段
    field_keywords_map = {
        ("香味", "味道", "香型"): "fragrance",
        ("成分", "材质", "原料"): "ingredients",
        ("使用方法", "怎么用", "如何用"): "usage_method",
        ("能用多久", "使用时长", "一瓶用多久"): "usage_duration",
        ("适用人群", "适合年龄", "孕妇能用"): "suitable_age",
        ("保质期", "有效期"): "shelf_life",
        ("起泡", "泡沫"): "foaming",
    }
    
    # 识别用户查询的字段
    target_field = None
    for keywords, field in field_keywords_map.items():
        if any(kw in user_query for kw in keywords):
            target_field = field
            break
    
    if not target_field:
        return {"valid": True, "reason": "", "fallback_type": ""}
    
    # 检查字段是否为空
    field_value = product_json.get(target_field, "")
    is_empty = (field_value == "" or 
                field_value == [] or 
                field_value is None)
    
    if not is_empty:
        return {"valid": True, "reason": "", "fallback_type": ""}
    
    # 检查回复是否包含"不确定"表达
    uncertain_expressions = [
        "不确定", "不清楚", "不知道", 
        "建议咨询人工客服", "请咨询人工客服"
    ]
    has_uncertain = any(expr in response_text for expr in uncertain_expressions)
    
    if not has_uncertain:
        return {
            "valid": False,
            "reason": f"空字段编造：'{target_field}'为空但回复未表达不确定",
            "fallback_type": "template_uncertain"
        }
    
    return {"valid": True, "reason": "", "fallback_type": ""}
```

---

### 2.3 医疗承诺校验

**规则 ID**：`MEDICAL_CLAIM_FORBIDDEN`

**目的**：防止出现医疗、治疗、治愈等绝对承诺

**校验逻辑**：
1. 定义医疗承诺关键词黑名单
2. 在 `response_text` 中搜索黑名单关键词
3. 如果发现医疗承诺，返回校验失败

**关键词黑名单**：
```python
MEDICAL_KEYWORDS = [
    "治疗", "治愈", "根治", "药效", "疗效",
    "能治", "可以治疗", "疗效显著", "根治不复发"
]
```

**示例**：
```python
# 合规回复
response_text = "这是止汗喷雾，不能替代医疗治疗。"
# 校验通过（包含"治疗"但用于否定，属于合规）

# 违规回复
response_text = "这款喷雾可以治疗狐臭。"
# 校验失败：医疗承诺（"可以治疗"）
```

**伪代码**：
```python
def validate_medical_claim(response_text):
    """校验医疗承诺"""
    # 医疗承诺关键词
    medical_keywords = [
        "治疗", "治愈", "根治", "药效", "疗效",
        "能治", "可以治疗", "疗效显著"
    ]
    
    # 检查回复中是否包含医疗承诺
    for keyword in medical_keywords:
        if keyword in response_text:
            # 特例：否定表达（"不能治疗"、"无法治疗"）是合规的
            negation_words = ["不能", "无法", "不是", "没有"]
            is_negation = any(neg in response_text for neg in negation_words)
            
            if not is_negation:
                return {
                    "valid": False,
                    "reason": f"医疗承诺：回复包含'{keyword}'",
                    "fallback_type": "template_risk_medical"
                }
    
    return {"valid": True, "reason": "", "fallback_type": ""}
```

---

### 2.4 价格推断校验

**规则 ID**：`PRICE_INFERENCE_FORBIDDEN`

**目的**：防止 LLM 推断价格、优惠力度

**校验逻辑**：
1. 识别用户是否询问价格/优惠
2. 检查 `product_json` 中是否包含价格信息
3. 如果商品 JSON 中无价格，但回复中给出价格/优惠，返回校验失败

**示例**：
```python
# 商品 JSON（假设价格字段为空或未注入）
{
    "price": ""  # 价格字段为空
}

# 用户查询："这个多少钱？"
# 合规回复
response_text = "请以商品页面实际价格为准。"
# 校验通过

# 违规回复
response_text = "这个商品大概19.9元，现在优惠15元。"
# 校验失败：价格推断
```

**伪代码**：
```python
def validate_price_inference(response_text, product_json, user_query):
    """校验价格推断"""
    # 价格相关查询关键词
    price_keywords = ["多少钱", "价格", "几块", "几元", "优惠", "便宜"]
    
    # 检查用户是否询问价格
    is_price_query = any(kw in user_query for kw in price_keywords)
    if not is_price_query:
        return {"valid": True, "reason": "", "fallback_type": ""}
    
    # 检查商品 JSON 中是否有价格信息
    product_price = product_json.get("price", "")
    
    # 如果商品无价格，检查回复是否推断价格
    if not product_price:
        price_patterns = [
            r"\d+元", r"\d+块", r"优惠\d+元", 
            r"原价\d+", r"现价\d+"
        ]
        for pattern in price_patterns:
            if re.search(pattern, response_text):
                return {
                    "valid": False,
                    "reason": "价格推断：商品无价格信息但回复包含价格",
                    "fallback_type": "template_price"
                }
    
    return {"valid": True, "reason": "", "fallback_type": ""}
```

---

### 2.5 人工请求识别

**规则 ID**：`HUMAN_REQUEST_DETECTION`

**重要说明**：此规则是 Response Validator 的"最后一道防线"，人工/售后/图片请求应在 L1 Gatekeeper 前置拦截。Response Validator 仅作为兜底校验。

**校验逻辑**：
1. 定义人工请求关键词
2. 在 `user_query` 中搜索关键词
3. 如果发现人工请求，返回特殊兜底类型

**关键词列表**：
```python
HUMAN_KEYWORDS = [
    "人工客服", "转人工", "人工服务",
    "接人工", "找人工", "人工"
]
```

**伪代码**：
```python
def detect_human_request(user_query):
    """识别人工请求（最后一道防线）"""
    human_keywords = [
        "人工客服", "转人工", "人工服务",
        "接人工", "找人工", "人工"
    ]
    
    for keyword in human_keywords:
        if keyword in user_query:
            return {
                "valid": False,
                "reason": "用户请求人工客服",
                "fallback_type": "template_human"
            }
    
    return {"valid": True, "reason": "", "fallback_type": ""}
```

**说明**：人工请求的主要拦截点应在 L1 Gatekeeper（意图分类层），Response Validator 仅作为补充防线。

---

## 3. 校验失败后的 Fallback 策略

### 3.1 Fallback 类型

| Fallback 类型 | 触发场景 | 兜底模板 |
|--------------|---------|----------|
| `template_uncertain` | 空字段编造、SKU 改写 | "这个信息我不确定，建议您咨询人工客服。" |
| `template_risk_medical` | 医疗承诺 | "这个商品不是药品，不能替代医疗治疗，如有健康问题请咨询医生。" |
| `template_risk_commitment` | 绝对承诺 | "商品效果因人而异，无法做绝对承诺。" |
| `template_price` | 价格推断 | "请以商品页面实际价格为准。" |
| `template_human` | 人工请求 | "正在为您转接人工客服，请稍候..." |

---

### 3.2 Fallback 处理流程

```python
def handle_fallback(fallback_type, context=None):
    """根据校验失败类型返回兜底回复"""
    templates = {
        "template_uncertain": "这个信息我不确定，建议您咨询人工客服。",
        "template_risk_medical": "这个商品不是药品，不能替代医疗治疗，如有健康问题请咨询医生。",
        "template_risk_commitment": "商品效果因人而异，无法做绝对承诺。",
        "template_price": "请以商品页面实际价格为准。",
        "template_human": "正在为您转接人工客服，请稍候..."
    }
    return templates.get(fallback_type, templates["template_uncertain"])
```

---

## 4. 校验器主函数

### 4.1 伪代码

```python
def validate_response(response_text, product_json, user_query):
    """
    回复校验器主函数
    
    Args:
        response_text: LLM 生成的回复文本
        product_json: 当前商品的结构化 JSON
        user_query: 用户原始查询
    
    Returns:
        {
            "valid": bool,
            "reason": str,
            "fallback_type": str
        }
    """
    # 1. 人工请求识别（优先级最高）
    result = detect_human_request(user_query)
    if not result["valid"]:
        return result
    
    # 2. SKU 原文保持校验
    result = validate_sku_original_text(response_text, product_json)
    if not result["valid"]:
        return result
    
    # 3. 空字段编造校验
    result = validate_empty_field(response_text, product_json, user_query)
    if not result["valid"]:
        return result
    
    # 4. 医疗承诺校验
    result = validate_medical_claim(response_text)
    if not result["valid"]:
        return result
    
    # 5. 价格推断校验
    result = validate_price_inference(response_text, product_json, user_query)
    if not result["valid"]:
        return result
    
    # 所有校验通过
    return {"valid": True, "reason": "", "fallback_type": ""}
```

---

## 5. 扩展性设计

### 5.1 规则注册机制

```python
# 规则注册表
VALIDATION_RULES = [
    detect_human_request,
    validate_sku_original_text,
    validate_empty_field,
    validate_medical_claim,
    validate_price_inference,
]

def validate_response(response_text, product_json, user_query):
    """支持动态扩展的校验器"""
    for rule_func in VALIDATION_RULES:
        result = rule_func(response_text, product_json, user_query)
        if not result["valid"]:
            return result
    return {"valid": True, "reason": "", "fallback_type": ""}
```

### 5.2 新增规则步骤

1. 在 `VALIDATION_RULES` 中注册新规则函数
2. 实现规则函数（输入/输出符合规范）
3. 在 `templates` 中添加对应的兜底模板

---

## 6. 实现位置

### 6.1 新增文件

```
Agent/CustomerAgent/custom/response_validator.py
```

**职责**：
- 实现所有校验规则
- 提供 `validate_response` 主函数
- 提供 `handle_fallback` 兜底函数

### 6.2 集成位置

在 `customer_agent.py` 的回复生成后调用：

```python
# LLM 生成回复
response_text = await self._llm_client.chat(messages)

# 校验回复
validation_result = validate_response(
    response_text=response_text,
    product_json=current_product_json,
    user_query=user_query
)

if not validation_result["valid"]:
    # 使用兜底回复
    response_text = handle_fallback(validation_result["fallback_type"])
    logger.warning(f"回复校验失败: {validation_result['reason']}")
```

---

## 7. 测试用例

### 7.1 SKU 原文校验测试

| 输入回复 | 商品 JSON | 预期结果 |
|---------|-----------|----------|
| "有一瓶、2瓶可选" | `{"sku_options": ["一瓶", "2瓶"]}` | 通过 |
| "有1瓶、2瓶可选" | `{"sku_options": ["一瓶", "2瓶"]}` | 失败（SKU改写："一瓶"原文被改写为"1瓶"） |

### 7.2 空字段校验测试

| 用户查询 | 商品 JSON | 回复 | 预期结果 |
|---------|-----------|------|----------|
| "有香味吗？" | `{"fragrance": ""}` | "有茉莉香味" | 失败（空字段编造） |
| "有香味吗？" | `{"fragrance": ""}` | "不确定香味信息" | 通过 |

### 7.3 医疗承诺测试

| 回复 | 预期结果 |
|------|----------|
| "可以治疗狐臭" | 失败（医疗承诺） |
| "不能替代医疗治疗" | 通过（否定表达） |

---

## 8. 文档关系
- 本文档定义回复校验器规格
- [[02_prompt_contract]] 定义 Prompt 合同（包含禁止行为）
- [[01_runtime_architecture]] 描述运行时架构（包含 Response Validator 层）
- [[05_implementation_slices]] 包含校验器实现切片
