Task 002 审查未通过。只修改 Slice 1 相关文件，不改生产主链路。

必须修复：

1. 删除误生成的空文件 `50`。

2. `Agent/CustomerAgent/custom/prompt_builder.py`
- `PRODUCT_FIELDS` 必须加入 `price`，字段顺序与 `docs/sdd/02_prompt_contract.md` 一致：goods_id, goods_name, category, brand, price, sku_summary, sku_options...
- `build_product_json` 对 list 字段应包括：sku_options、effect、warnings、accessories。None 时返回 []，不是空字符串。
- System Prompt 必须强化字段映射：
  - 用户问“12岁/几岁/小孩/儿童能用吗”时，如果 `suitable_age` 非空，必须引用 `suitable_age`。
  - 用户问“喷一次/喷一下/一次能管多久/单次持续多久”时，如果 `usage_method` 非空，优先引用 `usage_method`。
  - 用户问“一瓶能用多久/一支能用多久/一瓶能撑多久”时，引用 `usage_duration`。
  - 用户问孕妇/哺乳期时，不要用 `suitable_age=12岁以上` 替代，除非字段明确写孕妇/哺乳期。
- Prompt 仍要保持轻量，不要变成复杂 slot 主链路，不要调用 Qdrant。

3. `scripts/v3_prompt_only_experiment.py`
- 确保 `TEST_PRODUCT` 的 `price` 由 PromptBuilder 正常注入，不要靠注释说“不在标准字段中”。
- 输出 summary 中可以标注人工预期 pass/fail，但不要写死虚假通过。

4. `tests/test_v3_prompt_builder.py`
- 增加测试：price 在 product_json 和 system prompt 中存在。
- 增加测试：warnings/accessories None 时是 []。
- 增加测试：system prompt 包含 12岁/suitable_age 规则、喷一次/usage_method 规则、一瓶/usage_duration 规则。

验证命令请使用可用 Python：`E:\develop\customer-agent-refactor\.venv\Scripts\python.exe`。
运行：
- py_compile
- pytest tests/test_v3_prompt_builder.py
- scripts/v3_prompt_only_experiment.py（Ollama 可用时）

最后输出修改文件清单、命令结果、实验结果摘要。不要提问，直接修。
