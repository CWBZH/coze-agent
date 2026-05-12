# Claude Code Task 003 - 实现切片 2：Response Validator

你在 `E:\develop\customer-agent-refactor-v3` 工作。用户已批准继续开发，不要停下来询问或只输出设计。

## 目标
按照 `docs/sdd/03_response_validator_spec.md` 实现 V3.0 回复后校验器。该切片只做校验器和实验链路接入，不接管生产主链路。

## 严格边界
- 不删除 V2.0 逻辑。
- 不修改生产客服主路径 `customer_agent.py`。
- 不改数据库结构。
- 不改 UI。
- 不引入 Qdrant 主链路。
- 不实现复杂 slot 主链路。

## 必须实现
1. 新增 `Agent/CustomerAgent/custom/response_validator.py`
   - 提供 `ValidationResult`，可以用 dataclass 或 dict，但要稳定。
   - 提供 `validate_response(response_text: str, product_json: dict, user_query: str) -> ValidationResult`。
   - 提供 `handle_fallback(fallback_type: str, product_json: dict | None = None, user_query: str | None = None) -> str`。
   - 规则至少包括：
     a. SKU 原文保持：用户问规格/款式/几瓶时，回复必须包含 `sku_options` 中的原文；如果出现同义改写但没有原文，失败。
        示例：product_json sku_options=["一瓶", "2瓶"]，回复“有1瓶、2瓶”应失败。
     b. 空字段编造：用户询问保质期/脸部/孕妇/香味/成分/使用方法等字段时，如果对应字段为空或不覆盖该人群/用途，回复不能确定回答。
        注意：`suitable_age=12岁以上能使用` 不能覆盖“孕妇能用吗”。
     c. 医疗承诺：`可以治疗/能治/根治/治愈` 等确定医疗承诺失败；“不具备治疗功能/不能治疗/没有治疗承诺”应通过。
     d. 价格推断：如果 product_json.price 为空，回复中出现具体价格/优惠失败；如果 price 非空，只能引用原文价格，不得说“最划算/优惠”。
     e. 人工请求：用户问人工/转人工时，返回 template_human；这只是最后防线，文档中已说明 L1 才是主入口。
   - Fallback 模板要短、客服口吻，且不要编造事实。

2. 修改 `scripts/v3_prompt_only_experiment.py`
   - 接入 response_validator：每条 LLM 回复后校验。
   - 输出 raw_reply、valid、reason、final_reply。
   - 如果校验失败，final_reply 使用 fallback。
   - 不改变 Ollama 调用参数。

3. 新增 `tests/test_v3_response_validator.py`
   - 不调用 Ollama。
   - 覆盖：SKU 改写失败、SKU 原文通过、12岁通过、孕妇未标注失败/兜底、保质期空字段失败、医疗承诺失败、医疗否定通过、价格空字段失败、价格原文通过、人工请求。

## 验证命令
使用 `D:\anaconda\python.exe` 运行：
- `D:\anaconda\python.exe -m py_compile Agent\CustomerAgent\custom\response_validator.py scripts\v3_prompt_only_experiment.py tests\test_v3_response_validator.py`
- `D:\anaconda\python.exe -m pytest tests\test_v3_prompt_builder.py tests\test_v3_response_validator.py -q`
- `D:\anaconda\python.exe scripts\v3_prompt_only_experiment.py`

## 输出要求
最后输出：
- 修改文件清单
- 命令结果
- 实验摘要：raw_reply 与 final_reply 是否一致，有没有 fallback
- 风险点

直接实现，不要提问。
