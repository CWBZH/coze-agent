Task 003 审查未通过。只修改 Slice 2 相关文件，不改生产主链路。

必须修复：

1. 删除误生成文件/目录：
- 空文件 `50`
- 空文件 `Price`
- `memory/` 目录如果只包含本任务临时记忆文件，也删除。

2. 修复 `Agent/CustomerAgent/custom/response_validator.py`

A. SKU 校验不完整：
当前 `validate_sku_original_text` 只要回复里包含任意一个原文 SKU 就直接通过，会放过：
- product sku_options=["一瓶", "2瓶"]
- response="有一瓶、两瓶可选"
这应该失败，因为 `2瓶` 被改写成 `两瓶`。

要求：
- 先检查所有 sku_options 的同义改写风险：只要回复出现某 SKU 的同义词，且没有出现该 SKU 原文，就失败。
- 如果用户问规格/款式/几瓶/有哪些规格，回复应尽量包含全部 sku_options 原文；缺少原文时返回失败或至少风险失败。
- 不要因为命中了一个 SKU 原文就放过其他 SKU 的改写。

B. 脸部/面部使用校验缺失：
当前 user_query="可以喷脸吗?"，product usage_method="出门喷可以持续两至三个小时"，response="可以喷脸上" 会通过，这是错误。
要求：
- 如果用户问脸/脸部/面部，只有 usage_method 或 warnings 明确包含脸/面部/脸部时才允许确定回答。
- 否则回复必须包含“不确定/暂未标注/建议咨询人工”等兜底表达。

C. 价格比较校验缺失：
当前 user_query="几瓶划算?"，response="这个最划算" 会通过，这是错误。
要求：
- PRICE_KEYWORDS 增加：划算、实惠、性价比。
- “最划算/最优惠/最便宜/性价比最高”等比较承诺，不管 price 是否存在，都应失败。
- 如果 price 存在，允许引用原文价格，例如 response="价格是4.80-12.00" 通过；不允许编造非原文价格。

3. 增加 tests/test_v3_response_validator.py 测试：
- sku_options=["一瓶","2瓶"] + response="有一瓶、两瓶可选" 应失败。
- sku_options=["一瓶","2瓶","3瓶"] + response="有一瓶、2瓶可选" + query="规格有哪些" 应失败，因为缺少3瓶。
- user_query="可以喷脸吗" + usage_method 不含脸 + response="可以喷脸上" 应失败。
- user_query="可以喷脸吗" + response="页面暂未标注脸部是否适用" 应通过。
- user_query="几瓶划算" + response="这个最划算" 应失败。
- price="4.80-12.00" + response="价格是4.80-12.00" 应通过。
- price="4.80-12.00" + response="价格是9.9元" 应失败。

4. 运行：
- `D:\anaconda\python.exe -m py_compile Agent\CustomerAgent\custom\response_validator.py tests\test_v3_response_validator.py scripts\v3_prompt_only_experiment.py`
- `D:\anaconda\python.exe -m pytest tests\test_v3_prompt_builder.py tests\test_v3_response_validator.py -q`
- `D:\anaconda\python.exe scripts\v3_prompt_only_experiment.py`

最后输出修改摘要和验证结果。不要提问，直接修。
