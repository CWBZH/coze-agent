# Claude Code Task 004 - 独立 V3 Lightweight Service Shell

你在 `E:\develop\customer-agent-refactor-v3` 工作。继续 SDD 开发，用户已批准，不要提问。

## 目标
把 Slice 1/2 的 PromptBuilder + ResponseValidator 串成一个可复用的 V3 轻量客服服务壳，但仍不接管生产主链路。

## 严格边界
- 不修改 `customer_agent.py` 生产主路径。
- 不删除 V2.0 逻辑。
- 不改数据库结构。
- 不改 UI。
- 不引入 Qdrant 主链路。
- 不做复杂 slot。

## 必须实现
1. 新增 `Agent/CustomerAgent/custom/v3_lightweight_agent.py`
   - 提供 `V3ReplyResult` dataclass，至少包含：
     - raw_reply: str
     - final_reply: str
     - valid: bool
     - reason: str
     - fallback_type: str
     - latency_ms: float
     - error: str | None
   - 提供 `V3LightweightAgent` 类。
   - 构造函数支持依赖注入：`llm_client=None, prompt_builder=None, temperature=0.0, max_tokens=90`。
   - 方法：`generate_reply(product: dict, user_query: str, history: list | None = None) -> V3ReplyResult`。
   - 流程：
     1. PromptBuilder.build_product_json
     2. PromptBuilder.build_messages
     3. 调用 llm_client.chat_sync(messages, max_tokens=..., temperature=...)
     4. 调用 validate_response
     5. 校验失败则 handle_fallback
     6. 返回 V3ReplyResult
   - 如果 LLM 调用失败，final_reply 使用安全兜底，不抛异常到上层。
   - 不直接依赖 MySQL/Redis/Qdrant。

2. 修改 `scripts/v3_prompt_only_experiment.py`
   - 改为复用 `V3LightweightAgent`。
   - 保留当前输出 raw_reply/final_reply/valid/reason/latency。
   - 保持 8 个测试问题。

3. 新增 `tests/test_v3_lightweight_agent.py`
   - 不调用 Ollama。
   - 使用 FakeLLMClient。
   - 测试：
     - 正常回复 valid=True 时 raw_reply == final_reply。
     - 校验失败时 final_reply 为 fallback。
     - LLM success=False 时返回兜底和 error。
     - history 会传入 PromptBuilder 生成 messages。
     - temperature/max_tokens 会传给 chat_sync。

## 验证命令
使用 `D:\anaconda\python.exe`：
- `D:\anaconda\python.exe -m py_compile Agent\CustomerAgent\custom\v3_lightweight_agent.py scripts\v3_prompt_only_experiment.py tests\test_v3_lightweight_agent.py`
- `D:\anaconda\python.exe -m pytest tests\test_v3_prompt_builder.py tests\test_v3_response_validator.py tests\test_v3_lightweight_agent.py -q`
- `D:\anaconda\python.exe scripts\v3_prompt_only_experiment.py`

## 输出要求
最后输出修改文件清单、命令结果、实验摘要、风险点。不要提问，直接实现。
