# Claude Code Task 002 - 实现切片 1：Prompt-only 实验链路

你在 `E:\develop\customer-agent-refactor-v3` 工作。这是 3.0 副本，不要修改原项目。

## 目标
按照 `docs/sdd/02_prompt_contract.md` 和 `docs/sdd/05_implementation_slices.md` 实现 V3.0 Prompt-only 实验链路。

## 严格边界
- 允许写代码，但只做切片 1。
- 不要删除 V2.0 旧逻辑。
- 不要改主客服生产回复路径，不要让 V3.0 默认接管线上回复。
- 不要引入复杂 slot 主链路。
- 不要把 Qdrant 放回主链路。
- 不要改数据库结构。
- 不要改 UI。

## 必须实现
1. 新增 `Agent/CustomerAgent/custom/prompt_builder.py`
   - 提供 `PromptBuilder` 类。
   - 提供方法：
     - `build_product_json(product: dict) -> dict` 或等价方法，保证字段顺序和空字段规范。
     - `build_messages(product_json: dict, user_query: str, history: list | None = None) -> list[dict]`。
   - System Prompt 必须体现：
     - 商品 JSON 是唯一事实来源。
     - SKU 必须按 JSON 原文回复，不能同义改写。
     - 空字段必须兜底不确定。
     - 医疗/治疗/绝对承诺禁止。
     - 价格只能引用 JSON 的 price，不能推断优惠。
     - 回复简短自然。

2. 新增实验脚本 `scripts/v3_prompt_only_experiment.py`
   - 不依赖 MySQL，内置一个测试商品 JSON：`946901558797`，字段使用当前已知真实数据：
     - name: 净爽止汗喷雾保湿除臭净味爽身清新舒爽温和腋下止汗香体20ml
     - price: 4.80-12.00
     - brand: 伊思棠
     - sku_options: ["一瓶", "2瓶", "3瓶"]
     - sku_summary: 20ml
     - usage_method: 出门喷可以持续两至三个小时
     - usage_duration: 一瓶可用一至两个月
     - suitable_age: 12岁以上能使用
     - skin_type: 所有肤质均可
     - fragrance: 清香
     - effect: ["保湿", "止汗", "清香"]
     - ingredients: 酒精、香精
   - 调用本地 Ollama `customer-service:latest`。
   - temperature=0.0，max_tokens=90。
   - 跑至少 8 个问题：规格、使用时长、喷一次持续、12岁、孕妇、治狐臭、脸部、保质期。
   - 输出每条 query/reply/latency。
   - 输出 summary。

3. 新增轻量测试 `tests/test_v3_prompt_builder.py` 或项目现有测试目录等价位置。
   - 不调用 Ollama。
   - 验证 Prompt 中包含商品 JSON。
   - 验证 SKU 原文规则包含“一瓶”和“1瓶”的动态说明。
   - 验证 build_messages 返回 OpenAI/Ollama chat 兼容格式。

## 验证要求
完成后请运行：
- `python -m py_compile Agent/CustomerAgent/custom/prompt_builder.py scripts/v3_prompt_only_experiment.py`
- 如果可行，运行测试文件。
- 如果 Ollama 可用，运行 `scripts/v3_prompt_only_experiment.py`。

## 输出要求
最后输出：
- 修改文件清单
- 运行过的命令和结果
- 实验结果摘要
- 未完成或风险点

不要提问，直接实现。
