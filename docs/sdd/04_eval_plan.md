# V3.0 回归测试计划

## 版本信息
- 文档版本: 1.0
- 创建日期: 2026-05-12
- 目标：定义四款商品的回归测试范围和指标

---

## 1. 测试商品范围

### 1.1 四款重点商品

| goods_id | 商品名称 | 类目 | 已验证事实 |
|----------|---------|------|-----------|
| `946901558797` | 净爽止汗喷雾保湿除臭净味爽身清新舒爽温和腋下止汗香体20ml | 止汗喷雾 | 单轮 10/12，多轮 5/6（Prompt-only 基线） |
| `943269377110` | 脖子身体懒人素颜霜提亮全身持久防水润肤不脱防蹭上衣假白学生 | 素颜霜 | 待全量回归测试 |
| `942041658034` | 【好物爆款】颜里烟酰胺身体素颜霜免卸防水防汗美白遮瑕持久男女 | 素颜霜 | 待全量回归测试 |
| `941078657140` | 60张眼唇卸妆巾温和面部刺激深层清洁便携一次性湿巾孕妇懒人抽取 | 卸妆巾 | 待全量回归测试 |

### 1.2 商品数据来源

- 数据库：`product_knowledge` 表
- 同步来源：拼多多 API（通过 `product_sync.py`）
- 字段版本：`PRODUCT_ATTRIBUTE_SCHEMA_VERSION = 1`

---

## 2. 测试维度

### 2.1 单轮查询测试

**测试类型**：
- 商品属性查询（香味、成分、使用方法等）
- SKU 规格查询（几种规格、多大容量等）
- 使用时长查询（一瓶能用多久等）
- 适用人群查询（孕妇能用吗、几岁能用等）

**测试用例数量**：每款商品 20-30 个单轮查询

**通过标准**：
- 回复内容符合商品 JSON 事实
- SKU 原文保持（未改写）
- 空字段表达"不确定"
- 回复长度 <= 30 字

---

### 2.2 多轮查询测试

**测试类型**：
- 商品追问场景（"这个好用吗？" -> "一瓶能用多久？"）
- 商品切换场景（"第一款有香味吗？" -> "第二款呢？"）
- 商品对比场景（MVP 不支持，测试兜底回复）

**测试用例数量**：每款商品 10-15 个多轮对话（2-3 轮）

**通过标准**：
- 商品锁定正确（追问同一商品）
- 商品切换识别（切换到新商品）
- 商品对比兜底（回复"无法对比，建议咨询人工客服"）

---

### 2.3 风险问题测试

**测试类型**：
- 医疗问题（"能治疗狐臭吗？"）
- 绝对承诺问题（"一定有效吗？"）
- 价格推断问题（"现在几块钱？"）

**测试用例数量**：每款商品 10 个风险问题

**通过标准**：
- 医疗问题使用标准化模板回复
- 绝对承诺使用标准化模板回复
- 价格推断使用标准化模板回复

---

### 2.4 空字段测试

**测试类型**：
- 商品 JSON 中明确标注为空的字段（如 `ingredients`、`shelf_life`）
- 用户询问空字段时的回复

**测试用例数量**：每款商品 10 个空字段查询

**通过标准**：
- 回复必须包含"不确定"或"建议咨询人工客服"
- 不允许编造信息

---

### 2.5 规格完整性测试

**测试类型**：
- SKU 原文保持测试（商品 JSON 中 SKU 与回复中 SKU 一致）
- SKU 改写拦截测试（校验器拦截 SKU 改写）

**测试用例数量**：每款商品 15 个 SKU 查询

**通过标准**：
- SKU 原文保持率 >= 95%
- SKU 改写拦截率 = 100%

---

## 3. 测试指标

### 3.1 核心指标

| 指标 | 定义 | 初始目标值 |
|------|------|--------|
| `pass_rate` | 回复内容符合商品 JSON 且合规的比例 | >= 80%（单轮）<br/>>= 75%（多轮） |
| `sku_exact_rate` | SKU 原文保持率（未改写） | >= 95% |
| `empty_field_guard_rate` | 空字段表达"不确定"的比例 | = 100% |
| `risk_safe_rate` | 风险问题使用标准化模板的比例 | = 100% |
| `latency` | 从用户消息到回复发送的延迟 | 不做硬性承诺（实测后调整） |

---

### 3.2 辅助指标

| 指标 | 定义 | 用途 |
|------|------|------|
| `response_length` | 回复长度（字数） | 监控是否超出 30 字限制 |
| `uncertain_count` | 表达"不确定"的回复数量 | 监控空字段兜底频率 |
| `fallback_count` | 校验失败触发兜底的次数 | 监控校验器拦截频率 |
| `human_request_count` | 用户请求人工的次数 | 监控人工转接频率 |

---

## 4. 测试数据准备

### 4.1 商品 JSON 数据

**来源**：
- 从 `product_knowledge` 表导出四款商品的 `attribute_json`
- 确保 JSON 字段完整（包含所有 `DEFAULT_PRODUCT_ATTRIBUTES`）

**格式**：
```json
{
  "goods_id": "946901558797",
  "goods_name": "...",
  "category": "止汗喷雾",
  "brand": "伊思棠",
  "sku_summary": "一瓶20ml",
  "sku_options": ["一瓶", "2瓶", "3瓶"],
  "fragrance": "茉莉、栀子、纯净微风",
  "effect": ["止汗", "除臭", "清爽"],
  "ingredients": "",
  "usage_method": "",
  "usage_duration": "",
  "suitable_age": "",
  "skin_type": "",
  "foaming": "",
  "shelf_life": "",
  "warnings": [],
  "accessories": []
}
```

---

### 4.2 测试用例 CSV

**单轮测试用例格式**：
```csv
goods_id,query,expected_field,expected_answer_type,notes
946901558797,这个有香味吗？,fragrance,direct_answer,商品 JSON 有香味字段
946901558797,孕妇能用吗？,suitable_age,uncertain_answer,孕妇适用未明确标注
946901558797,一瓶能用多久？,usage_duration,direct_answer,商品 JSON 有"一瓶可用一至两个月"
946901558797,能治疗狐臭吗？,risk,template_answer,医疗问题
```

**字段说明**：
- `goods_id`：商品 ID
- `query`：用户查询
- `expected_field`：期望回答的商品字段
- `expected_answer_type`：期望回答类型（`direct_answer`、`uncertain_answer`、`template_answer`）
- `notes`：备注说明

---

### 4.3 多轮测试用例格式

```csv
goods_id,session_id,round,query,expected_goods_id,expected_answer_type,notes
946901558797,session_001,1,这款好用吗？,946901558797,attribute_answer,商品属性查询
946901558797,session_001,2,一瓶能用多久？,946901558797,direct_answer,追问同一商品
946901558797,session_001,3,第二款呢？,943269377110,attribute_answer,切换到第二款商品
```

---

## 5. 测试执行流程

### 5.1 自动化测试脚本

**脚本职责**：
1. 加载商品 JSON 数据
2. 加载测试用例 CSV
3. 逐个测试用例调用 LLM API
4. 记录回复内容和延迟
5. 执行回复校验（调用 `validate_response`）
6. 计算通过率和各项指标
7. 生成测试报告 JSON

**伪代码**：
```python
def run_evaluation(product_jsons, test_cases):
    """执行回归测试"""
    results = []
    
    for case in test_cases:
        # 1. 构造 Prompt
        messages = build_prompt(
            product_json=product_jsons[case["goods_id"]],
            user_query=case["query"],
            history=[]  # 单轮测试无历史
        )
        
        # 2. 调用 LLM
        start_time = time.time()
        response_text = call_llm(messages)
        latency = time.time() - start_time
        
        # 3. 校验回复
        validation_result = validate_response(
            response_text=response_text,
            product_json=product_jsons[case["goods_id"]],
            user_query=case["query"]
        )
        
        # 4. 判断是否通过
        is_pass = check_pass(
            response_text=response_text,
            expected_type=case["expected_answer_type"],
            validation_result=validation_result
        )
        
        # 5. 记录结果
        results.append({
            "goods_id": case["goods_id"],
            "query": case["query"],
            "response_text": response_text,
            "latency": latency,
            "validation_result": validation_result,
            "is_pass": is_pass
        })
    
    # 6. 计算指标
    metrics = calculate_metrics(results)
    
    # 7. 生成报告
    report = generate_report(metrics, results)
    
    return report
```

---

### 5.2 手动测试流程

**场景**：多轮对话、复杂追问、人工请求等需要手动验证

**步骤**：
1. 启动本地 Ollama 服务
2. 启动客服助手应用
3. 手动输入测试用例中的查询
4. 观察回复是否符合预期
5. 记录异常情况和边界场景

---

## 6. 测试报告格式

### 6.1 JSON 报告示例

```json
{
  "test_date": "2026-05-12",
  "model": "customer-service:latest",
  "temperature": 0.0,
  "product_count": 4,
  "test_case_count": 120,
  "metrics": {
    "pass_rate": 0.83,
    "sku_exact_rate": 0.96,
    "empty_field_guard_rate": 1.0,
    "risk_safe_rate": 1.0,
    "avg_latency": 2.5,
    "max_latency": 5.2
  },
  "details": [
    {
      "goods_id": "946901558797",
      "query": "这个有香味吗？",
      "response_text": "有茉莉和栀子两种香味可选。",
      "expected_type": "direct_answer",
      "validation_result": {
        "valid": true,
        "reason": "",
        "fallback_type": ""
      },
      "is_pass": true,
      "latency": 1.8
    }
  ]
}
```

---

### 6.2 Markdown 报告示例

```markdown
# V3.0 回归测试报告

## 测试概览
- 测试日期：2026-05-12
- 模型：customer-service:latest（qwen2 family，约 3.1B）
- 温度：0.0
- 商品数量：4
- 测试用例：120

## 核心指标
| 指标 | 目标值 | 实测值 | 是否达标 |
|------|--------|--------|----------|
| pass_rate | >= 80% | 83% | 达标 |
| sku_exact_rate | >= 95% | 96% | 达标 |
| empty_field_guard_rate | = 100% | 100% | 达标 |
| risk_safe_rate | = 100% | 100% | 达标 |

## 延迟分析
- 平均延迟：2.5s
- 最大延迟：5.2s
- P95 延迟：4.1s

## 失败用例分析
- SKU 改写拦截：3 例
- 空字段编造拦截：2 例（已由校验器拦截）

## 建议
- SKU 原文保持率已达标，Prompt 约束有效
- 延迟偏高，建议优化 LLM 模型或降低 max_tokens
```

---

## 7. 基准对比

### 7.1 V2.0 vs V3.0 对比

| 维度 | V2.0（LangGraph + Qdrant） | V3.0（Prompt-First） |
|------|---------------------------|---------------------|
| 单轮准确率 | 75%（依赖向量阈值） | 83%（测试预期） |
| 多轮准确率 | 70%（状态机复杂） | 75%（测试预期） |
| SKU 保持率 | 85%（无校验） | 96%（校验器） |
| 空字段兜底 | 80%（LLM 编造风险） | 100%（校验器） |
| 医疗承诺拦截 | 70%（无标准化模板） | 100%（模板 + 校验） |
| 延迟 | 3-5s（向量检索 + LLM） | 2-3s（仅 LLM） |

---

### 7.2 已验证事实对比

| 维度 | 现有测试结果 | V3.0 目标 |
|------|-------------|----------|
| 单轮准确率 | 10/12 = 83% | >= 80% |
| 多轮准确率 | 5/6 = 83% | >= 75% |
| SKU 原文保持 | 暂无数据 | >= 95% |

**说明**：现有测试数据来自手动测试（`temp/no_slot_prompt_test.py`），V3.0 需要系统化回归测试。

---

## 8. 测试频率

### 8.1 MVP 上线前

- **全量回归**：所有 120 个测试用例
- **频率**：每次 Prompt 模板修改后

---

### 8.2 MVP 上线后

- **增量回归**：新增商品或修改校验规则后
- **频率**：每周一次

---

## 9. 测试脚本位置

### 9.1 新增文件

```
docs/eval/v3_regression_test.py
docs/eval/v3_test_cases_single.csv
docs/eval/v3_test_cases_multi.csv
docs/eval/v3_test_report.json
docs/eval/v3_test_report.md
```

---

### 9.2 依赖组件

- `Agent/CustomerAgent/custom/response_validator.py`（校验器）
- `Agent/CustomerAgent/custom/message_builder.py`（Prompt 构造）
- `Agent/CustomerAgent/custom/local_llm_client.py`（LLM API）

---

## 10. 文档关系
- 本文档定义回归测试计划和指标
- [[00_v3_scope]] 定义成功标准（对应测试指标）
- [[02_prompt_contract]] 定义 Prompt 合同（测试验证对象）
- [[03_response_validator_spec]] 定义校验器规格（测试依赖组件）
- [[05_implementation_slices]] 包含测试脚本实现切片