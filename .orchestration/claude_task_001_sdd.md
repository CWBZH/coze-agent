# Claude Code Task 001 - SDD 规格阶段，不改业务代码

你现在在 `E:\develop\customer-agent-refactor-v3`，这是 3.0 重构副本。原项目 2.0 在 `E:\develop\customer-agent-refactor`，不要修改原项目。

## 总目标
把现有客服助手重构为“轻量级本地客服助手 3.0”：不再依赖复杂 slot 主链路，采用当前商品 JSON 精准注入 + 强 Prompt 约束 + 低温度本地 LLM + 回复后校验的轻量架构。

## 本轮任务边界
本轮只做 SDD 规格和开发切片，不允许修改业务代码，不允许重构 Python 逻辑。
允许新增/修改 `docs/sdd/` 下的 Markdown 文档。

## 必须先阅读的上下文
1. `Agent/CustomerAgent/custom/customer_agent.py`
2. `Agent/CustomerAgent/custom/local_llm_client.py`
3. `database/product_sync.py`
4. `services/knowledge_sync_service.py`
5. `ui/Knowledge_ui.py`
6. `docs/eval/four_product_slot_qdrant_report.md` 如果存在
7. `temp/no_slot_prompt_test.py` 如果存在
8. `config.json`

## 已验证事实
- Ollama 可用，模型为 `customer-service:latest`。
- 当前模型实际信息：qwen2 family，约 3.1B，F16，不要在文档里写成 7B。
- Prompt-only 测试结果：强 Prompt + 商品 JSON + temperature=0.0，单轮 10/12，多轮 5/6。
- 已暴露风险：SKU 原文漂移、风险问题表达不稳定、字段缺失时容易从标题推断。

## 3.0 目标架构
1. Tenant/Session 层：多店铺隔离，Redis key 必须带 shop_id/platform/buyer_id。
2. Product Context 层：锁定当前 goods_id，只注入当前商品结构化 JSON，不做整店长上下文。
3. Prompt Builder 层：2K token 预算内构造 system prompt + product JSON + 最近短历史。
4. Bounded LLM 层：本地模型低温度生成，不能自由编事实。
5. Response Validator 层：发送前校验，至少拦截：不存在 SKU、字段为空却确定回答、医疗/绝对承诺、价格/优惠推断。
6. Fallback 层：校验失败后使用安全兜底模板或人工提示。
7. Evaluation 层：用四款重点商品做单轮/多轮回归测试。

## 需要产出的 SDD 文档
请创建 `docs/sdd/`，并输出以下文件：

1. `00_v3_scope.md`
   - 3.0 范围
   - 明确不做什么：不做复杂 slot 主链路、不做训练模型、不做多轮追问状态机、不让 Qdrant 决定事实
   - 成功标准

2. `01_runtime_architecture.md`
   - 轻量链路图
   - 每层职责
   - Redis 多店铺 key 设计
   - MySQL / Redis / Qdrant / LLM 的职责边界

3. `02_prompt_contract.md`
   - 商品 JSON 注入格式
   - System Prompt 合同
   - 低温参数建议
   - 禁止行为
   - 风险问题回答规则
   - SKU 原文保持规则

4. `03_response_validator_spec.md`
   - 回复后校验器的输入/输出
   - 校验规则清单
   - 校验失败的 fallback 策略
   - 不要写完整代码，但要写清楚伪代码和函数边界

5. `04_eval_plan.md`
   - 四款商品的回归测试范围
   - 单轮、多轮、风险、空字段、规格完整性测试
   - 指标：pass_rate、sku_exact_rate、empty_field_guard_rate、risk_safe_rate、latency

6. `05_implementation_slices.md`
   - 后续编码切片，每片必须小而清晰
   - 每片列出修改文件、预期测试、回滚方式
   - 第一片应只实现 Prompt-only 实验链路，不删除旧逻辑

## 文档要求
- 中文输出。
- 不要写空泛概念，要贴合当前项目文件。
- 不要承诺无法证明的性能指标，比如首字 100ms。
- 每个文档控制在 500 行以内。
- 最后在终端总结你新增的文件和关键判断。
