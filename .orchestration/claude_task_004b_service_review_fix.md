Task 004 审查小修。只修改 V3 服务壳相关文件。

必须修复：

1. 删除误生成的空文件：`0`、`3`。

2. `Agent/CustomerAgent/custom/v3_lightweight_agent.py`
- 当前只支持 llm_client.chat_sync 返回 dict 或 tuple。
- 必须兼容项目现有 `LocalLLMClient.chat_sync()` 返回的对象格式：
  - `.success: bool`
  - `.content: str`
  - `.error: str | None`
- 也兼容对象有 `.reply` 字段的情况。
- 建议抽一个私有方法 `_normalize_llm_result(llm_result) -> tuple[bool, str, str | None]`。

3. `Agent/CustomerAgent/custom/response_validator.py`
- 给 `FALLBACK_TEMPLATES` 增加 `llm_failure` 和 `pipeline_error`，都返回安全兜底，不要依赖默认分支。

4. `tests/test_v3_lightweight_agent.py`
- 增加测试：FakeLocalLLMResponse(success=True, content="...", error=None) 可以被正确处理。
- 增加测试：FakeLocalLLMResponse(success=False, content="", error="timeout") 返回 llm_failure fallback。
- 保留现有 dict FakeLLMClient 测试。

运行：
- `D:\anaconda\python.exe -m py_compile Agent\CustomerAgent\custom\v3_lightweight_agent.py Agent\CustomerAgent\custom\response_validator.py tests\test_v3_lightweight_agent.py`
- `D:\anaconda\python.exe -m pytest tests\test_v3_prompt_builder.py tests\test_v3_response_validator.py tests\test_v3_lightweight_agent.py -q`
- `D:\anaconda\python.exe scripts\v3_prompt_only_experiment.py`

输出修改摘要和验证结果。不要提问。
