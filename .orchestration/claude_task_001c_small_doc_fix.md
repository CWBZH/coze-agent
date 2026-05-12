只修改 docs/sdd/02_prompt_contract.md、docs/sdd/03_response_validator_spec.md、docs/sdd/04_eval_plan.md。不要改代码，不要新增文件，不要提问。

精确修正：

1. docs/sdd/02_prompt_contract.md
- 把“SKU 规格必须原文复述”那条改成：SKU 规格必须按商品 JSON 原文复述，禁止任何同义改写；例如商品 JSON 是 `一瓶` 就必须回复 `一瓶`，商品 JSON 是 `1瓶` 才能回复 `1瓶`。
- 禁止行为表中不要写“商品 JSON 只有 1瓶”，改成“商品 JSON 只有某个 SKU 原文”。
- SKU 原文保持规则表不要只列 `1瓶`。改成两组示例：`一瓶` 禁止改写为 `1瓶/单瓶`；`1瓶` 禁止改写为 `一瓶/单瓶`。

2. docs/sdd/03_response_validator_spec.md
- 删除或改写所有会让人误解 `1瓶` 是标准答案的表述。
- 底部测试表改成：`有一瓶、2瓶可选` + `{"sku_options":["一瓶","2瓶"]}` 通过；`有1瓶、2瓶可选` + 同 JSON 失败。
- 伪代码继续保持配置化，不写死 `sku_rewrite_map`。

3. docs/sdd/04_eval_plan.md
- 商品 JSON 示例里把 `sku_summary` 改为 `20ml` 或 `一瓶20ml`，`sku_options` 改为 `["一瓶", "2瓶", "3瓶"]`。
- 多轮测试样例中 `一瓶能用多久？` 的 expected_answer_type 改为 `direct_answer`，不要写 uncertain_answer。

完成后只输出修改摘要。
