# TASKS.md

## 任务规则

1. 每次只执行一个任务。
2. 执行前先说明计划。
3. 执行后必须说明修改文件、验证方式、风险和回滚方案。
4. 未经用户确认，不允许跳到后续阶段。
5. 不允许一次性执行多个阶段。

---

# 阶段 0：WebSocket / Consumer 稳定性

## T000：P0 consumer setup 幂等化

状态：已完成。

范围：

- `Message/core/consumer.py`
- `Message/__init__.py`
- `Channel/pinduoduo/core/pdd_message_handler.py`

验收：

- 同一个 `queue_name` 重复 setup 不重复创建 consumer。
- 不重复 add handler。
- 不无条件 recreate queue。
- `python -m py_compile` 通过。
- 内联异步幂等测试通过。

## T001：MessageConsumer 固定 worker pool

状态：已完成。

目标：

把当前每条消息创建一个 `_process_message` task 的模型，改为固定 worker pool。

修改文件：

- `Message/core/consumer.py`

已完成内容：

- `MessageConsumer.start()` 按 `max_concurrent` 固定创建 worker task。
- 新增 `_worker_tasks` 记录 worker task 集合。
- 新增 `_worker_loop(worker_id)`，每个 worker 循环从 queue 读取消息并调用原 `_process_message()`。
- 不再在每条消息到来时无限 `create_task(_process_message)`。
- `MessageConsumer.stop()` 会 cancel worker tasks，并通过 `asyncio.gather(..., return_exceptions=True)` + timeout 等待退出。
- `diagnostic_state()` 增加 `worker_count` 和 `worker_task_ids`。
- 保持 handler 执行逻辑不变。
- 保持 add handler 去重逻辑不变。
- 保持 `MessageConsumerManager.create_consumer()` / `stop_consumer(timeout=5.0)` 兼容。

验证：

- `python -m py_compile Message/core/consumer.py Message/__init__.py` 通过。
- `max_concurrent=3` 时 `worker_count == 3`。
- 连续 put 12 条测试消息时 worker task id 保持不变。
- `consumer._tasks == 0`。
- `stop_consumer(timeout=5.0)` 后 `running=False` 且 `worker_count == 0`。

## T002：reconnect lifecycle lock + generation

状态：已完成。

目标：

防止重复 reconnect task 和旧 task 误伤新连接。

修改文件：

- `Channel/pinduoduo/core/pdd_lifecycle.py`
- `Channel/pinduoduo/core/pdd_connection.py`
- `Channel/pinduoduo/pdd_channel.py`

已完成内容：

- `start_account()` 使用 per-connection lifecycle lock，按 `connection_key` 串行化启动/替换流程。
- 已有 reconnect task 在替换前会先 `cancel()`，再 `await asyncio.wait_for(old_task, timeout=5.0)`。
- 每次新连接流程都会让 generation 自增。
- generation 已传递到 connect / init / cleanup / heartbeat 相关路径。
- stale generation 不会执行 `_cleanup_resources()`。
- stale generation 不会清理当前 `ws`。
- 最大重试失败分支的 `stop_event.set()` 已增加 generation guard。
- 保持 `queue_name = pdd_{shop_id}` 不变。
- 未修改业务消息处理逻辑。

验证：

- `python -m py_compile Channel/pinduoduo/core/pdd_lifecycle.py Channel/pinduoduo/core/pdd_connection.py Channel/pinduoduo/pdd_channel.py` 通过。
- `python -m py_compile Channel/pinduoduo/core/pdd_connection.py` 通过。
- 连续两次 `start_account()` 时 generation 从 1 到 2。
- 旧 reconnect task 被 cancel，并 await 到 done。
- stale generation 调用 cleanup 不清理当前 `ws`。

## T003：graceful shutdown

状态：已完成。

目标：

停止账号 / 退出程序时，先清理资源，再关闭 event loop。

要求：

1. set stop_event。
2. cancel reconnect/heartbeat/message tasks。
3. await gather with timeout。
4. close websocket。
5. wait_closed。
6. stop consumer。
7. clear processing tasks。
8. 最后 stop event loop。

### T003-A：_safe_close_websocket close + wait_closed + timeout

状态：已完成。

修改文件：

- `Channel/pinduoduo/core/pdd_connection.py`

已完成内容：

- `_safe_close_websocket()` 增加空 `ws` 直接返回。
- `close()` 返回 coroutine 时使用 `asyncio.wait_for(..., timeout=5.0)`。
- `wait_closed()` 返回 coroutine 时使用 `asyncio.wait_for(..., timeout=5.0)`。
- `close()` 和 `wait_closed()` 各自只 await 一次。
- 未修改调用方。
- 未修改业务逻辑。
- 未修改 `queue_name`。

验证：

- `python -m py_compile Channel/pinduoduo/core/pdd_connection.py` 通过。
- fake websocket 测试通过。
- `close_called == True`。
- `wait_closed_called == True`。
- 未出现 `RuntimeError: cannot reuse already awaited coroutine`。

### T003-B：LifecycleMixin.stop_account / stop_all_connections 统一 await 清理

状态：已完成。

修改文件：

- `Channel/pinduoduo/core/pdd_lifecycle.py`
- `Channel/pinduoduo/pdd_channel.py`

已完成内容：

- `stop_account()` 统一为 set stop_event -> cancel reconnect / heartbeat / message / stop-wait task -> await with timeout -> close websocket -> cleanup resources -> update DISCONNECTED -> clear maps。
- `stop_all_connections()` 统一为 set all stop_event -> cancel all task maps -> await with timeout -> close websocket -> per-connection cleanup -> clear maps -> `self.ws = None`。
- 新增 `_connection_queue_names` 显式记录 `connection_key -> queue_name`，继续使用 `queue_name = pdd_{shop_id}`。
- 新增 `_message_tasks`、`_stop_wait_tasks` 映射，便于 shutdown 阶段追踪和清理。
- `cleanup_processing_tasks()` 增加 timeout，避免无限等待。
- `_cleanup_resources()` 保留 generation guard，并记录 consumer cleanup result。
- 未修改 UI。
- 未修改业务逻辑。
- 未修改 `queue_name`。

验证：

- `python -m py_compile Channel/pinduoduo/core/pdd_lifecycle.py Channel/pinduoduo/pdd_channel.py` 通过。
- fake task 测试通过。
- cancel 后正常完成的 task 会被 await 到 done。
- `processing_tasks` 会被清空。
- 重复 stop / cleanup 不抛异常。

### T003-B 小补丁：_cancel_mapped_task timeout 后保留未完成 task 引用

状态：已完成。

修改文件：

- `Channel/pinduoduo/core/pdd_lifecycle.py`

已完成内容：

- `_cancel_mapped_task()` 在 cancel timeout 后，如果 task 仍未 done，不再无条件从 task map 中 pop。
- pop 前确认 `current is task`，避免误删已替换的新 task。
- 使用 `asyncio.shield(task)` 等待取消完成，避免 `wait_for` 超时后二次取消并改变仍运行 task 的状态。
- timeout 后仍未完成的 task 会保留引用，便于后续 `stop_all_connections()` 或诊断继续追踪。

验证：

- `python -m py_compile Channel/pinduoduo/core/pdd_lifecycle.py` 通过。
- fake task 测试通过。
- 已完成 task 会被 pop。
- cancel 后正常完成的 task 会被 pop。
- cancel 后超时且仍未 done 的 task 不会被 pop。
- map 中已被新 task 替换时不会误删新 task。

### T003-C：AutoReplyThread.stop graceful shutdown

状态：已完成。

修改文件：

- `ui/auto_reply/threads.py`

已完成内容：

- `AutoReplyThread.stop()` 不再直接 `asyncio.all_tasks(self.loop)` 全量 cancel。
- `stop()` 使用 `asyncio.run_coroutine_threadsafe(self._shutdown_async(), self.loop)` 提交 shutdown coroutine。
- `_shutdown_async()` 先 `await self.channel.stop_all_connections()`。
- pending tasks 使用 `asyncio.gather(..., return_exceptions=True)` + `asyncio.wait_for(..., timeout=5.0)` 清理。
- `run()` finally 在 `_shutdown_complete=True` 时不重复 cleanup。
- `stop()` 最多等待 5 秒；外层 `thread.wait(5000)` 存在最坏接近 10 秒 UI 阻塞风险，后续根据实测优化。

验证：

- `python -m py_compile ui/auto_reply/threads.py` 通过。
- T003-C 只修改 `ui/auto_reply/threads.py`。

## T004：诊断日志增强

状态：已完成。

目标：

补齐诊断字段。

修改文件：

- `ui/auto_reply/threads.py`
- `Channel/pinduoduo/core/pdd_lifecycle.py`
- `Channel/pinduoduo/core/pdd_connection.py`
- `Channel/pinduoduo/core/pdd_message_handler.py`
- `Message/core/consumer.py`

日志字段：

- connection_key
- queue_name
- loop_id
- queue_id
- consumer_id
- task_id
- websocket_id
- generation
- processing_tasks_count
- worker_count
- reconnect_attempt

已完成内容：

- `AutoReplyThread.run()` 增加 loop / channel / start_task / run_forever / loop close 诊断日志。
- `AutoReplyThread.stop()` 增加 shutdown_started / future timeout / fallback loop.stop / shutdown_complete 诊断日志。
- `LifecycleMixin.start_account()` 增加 lifecycle lock、generation、reconnect task 创建日志。
- `LifecycleMixin.stop_account()` 和 `stop_all_connections()` 增加 shutdown 阶段、task cancel、websocket close、consumer cleanup 日志。
- `MessageConsumer.start()` / `stop()` 增加 worker_count、loop_id、consumer_id、handler_count 日志。
- `_setup_message_consumer()` 增加 existing consumer reused / replaced / rejected 诊断日志。

验证：

- `python -m py_compile ui/auto_reply/threads.py Channel/pinduoduo/core/pdd_lifecycle.py Channel/pinduoduo/core/pdd_connection.py Channel/pinduoduo/core/pdd_message_handler.py Message/core/consumer.py` 通过。

## T005-A：message trace_id 生成与基础透传

状态：已完成。

目标：

建立单条买家消息的 `trace_id`，并绑定拼多多原始 `msg_id` 与 `MessageWrapper.message_id`，用于后续排查消息是否成功回复或失败。

修改文件：

- `Channel/pinduoduo/core/pdd_message_handler.py`
- `Channel/pinduoduo/pdd_message.py`
- `bridge/context.py`
- `Message/models/queue_models.py`
- `Message/core/consumer.py`

已完成内容：

- WebSocket 原始消息解析后生成 `trace_id`。
- 有 PDD 原始 `msg_id` 时使用 `pdd:{shop_id}:{msg_id}`。
- 无 `msg_id` 时使用 12 位短 uuid。
- 保留 `source_message_id`，对应 PDD 原始 `msg_id`。
- 将 `trace_id` / `source_message_id` 写入 `Context.kwargs`。
- `MessageWrapper` 保留 `trace_id`、`source_message_id`、`queue_message_id`、`shop_id`、`user_id`、`from_uid`、`to_uid`、`queue_name`、`message_type`、`content_length`、`content_hash`。
- `MessageWrapper.to_metadata()` 输出上述 trace 字段。
- `MessageConsumer._process_message()` 日志携带 `trace_id` / `source_message_id` / `queue_message_id`。
- 新增事件日志：`pdd.message.received`、`pdd.context.created`、`pdd.message.queued`、`pdd.consumer.dequeued`、`pdd.handler.selected`、`pdd.handler.completed`、`pdd.handler.failed`、`pdd.message.skipped`。
- 新增日志只记录 `content_length` 和截断 `content_hash`，不记录完整买家消息内容。

### T005-A.1：trace_id 规范和日志级别小补丁

状态：已完成。

已完成内容：

- `shop_id` 为空时 `trace_id` 使用 `unknown`，避免生成 `pdd:None:<id>`。
- 所有 ID 统一转为字符串。
- 高频 trace 事件降为 debug：`pdd.message.received`、`pdd.context.created`、`pdd.message.queued`、`pdd.consumer.dequeued`、`pdd.handler.selected`、`pdd.handler.completed`。
- `pdd.message.skipped` 保持 info。
- `pdd.handler.failed` 保持 warning/error。

验证：

- `py_compile` 通过。
- fake trace metadata test 通过。
- trace id rule test 通过。
- 新增日志未记录完整 `content` / `token` / `cookie`。

下一步：

- `T005-B：AI / Pipeline reply outcome observability`。

## T005-B：AI / Pipeline reply outcome observability

状态：已完成。

目标：

让 `AIReplyHandler` / `MessagePipeline` 能关联 `trace_id`，并记录 pipeline、AI、静态规则、人工锁、转人工 outcome。

修改文件：

- `Message/handlers/ai_handler.py`
- `Message/core/pipeline.py`

已完成内容：

- `AIReplyHandler` 从 `metadata` / `context.kwargs` 读取 `trace_id`、`source_message_id`、`queue_message_id`、`shop_id`、`user_id`、`from_uid/customer_uid`、`session_id`。
- `MessagePipeline.process()` 增加向后兼容可选参数：`trace_id=None`、`source_message_id=None`、`queue_message_id=None`。
- `AIReplyHandler._get_ai_reply()` 调用 `pipeline.process(...)` 时透传 trace 字段。
- 新增 outcome 事件：`pdd.pipeline.started`、`pdd.pipeline.completed`、`pdd.pipeline.failed`、`pdd.ai.request.started`、`pdd.ai.request.succeeded`、`pdd.ai.request.failed`、`pdd.human_lock.skipped`、`pdd.static_rule.matched`、`pdd.transfer_human.triggered`、`pdd.message.skipped`。
- 保持 FastGPT 请求参数、Pipeline 返回结构和业务分支不变。

### T005-B.1：AI / Pipeline outcome 日志语义修正

状态：已完成。

已完成内容：

- `AIReplyHandler` 中包裹 `pipeline.process()` 的事件改为 `pdd.pipeline.started` / `pdd.pipeline.completed` / `pdd.pipeline.failed`。
- 只有 `MessagePipeline` 内真正 `_call_fastgpt_async(...)` 的边界保留 `pdd.ai.request.started` / `pdd.ai.request.succeeded` / `pdd.ai.request.failed`。
- Pipeline outcome 阶段不再记录 `pdd.message.completed`。
- 静态规则生成回复只记录 `pdd.reply.generated`，不记录 `pdd.message.completed`。
- `pdd.message.completed` 留给 SendMessage 发送结果明确后记录。

验证：

- `python -m py_compile Message/handlers/ai_handler.py Message/core/pipeline.py` 通过。
- fake reply / transfer_human / skip 测试通过。
- grep 确认 T005-B 文件中不存在误导性 `event=pdd.message.completed`。
- grep 确认 `pdd.ai.request.*` 只出现在真实 FastGPT 调用边界。
- 新增日志未记录完整 `content` / `reply` / `token` / `cookie`。

## T005-C：SendMessage reply send outcome observability

状态：已完成。

目标：

补齐 SendMessage 发送结果追踪，并在发送结果明确后记录最终 `pdd.message.completed`。

修改文件：

- `Message/handlers/ai_handler.py`

已完成内容：

- `_send_reply()` 生成本地 `send_request_id` 用于关联发送调用。
- 发送前记录 `event=pdd.reply.send.started`。
- PDD 明确返回 `result.result == "ok"` 时记录 `event=pdd.reply.send.succeeded`。
- 调用无异常但无法确认投递时记录 `event=pdd.reply.send.call_succeeded status=unknown_delivery`。
- 非 ok、None、异常、缺少发送字段时记录 `event=pdd.reply.send.failed`。
- 发送结果明确后记录 `event=pdd.message.completed`。
- 未修改 `SendMessage.send_text()` 请求参数。
- 未修改发送逻辑和业务策略。

### T005-C.1：unknown_delivery final_status 语义修正

状态：已完成。

final_status 语义：

- `reply_sent`：PDD 明确返回 ok。
- `reply_send_failed`：非 ok / None / 异常 / 缺少发送字段。
- `reply_delivery_unknown`：调用成功但无明确 ok。

已完成内容：

- unknown delivery 分支保持 `event=pdd.reply.send.call_succeeded status=unknown_delivery`。
- unknown delivery 分支的 `event=pdd.message.completed final_status` 改为 `reply_delivery_unknown`。
- `_send_reply()` 返回值仍保持 `False`，业务行为不变。

完整 message trace 链路：

- WebSocket -> Context -> Queue -> Consumer -> Handler -> Pipeline -> AI -> SendMessage。

主要事件：

- `pdd.message.received`
- `pdd.message.queued`
- `pdd.consumer.dequeued`
- `pdd.pipeline.started`
- `pdd.ai.request.started`
- `pdd.ai.request.succeeded`
- `pdd.reply.send.started`
- `pdd.reply.send.succeeded`
- `pdd.reply.send.failed`
- `pdd.reply.send.call_succeeded status=unknown_delivery`
- `pdd.message.completed final_status=...`

隐私原则：

- 不记录完整用户消息。
- 不记录完整 AI 回复。
- 只记录 `content_length` / `content_hash` / `reply_length` / `reply_hash`。

验证：

- `python -m py_compile Message/handlers/ai_handler.py Channel/pinduoduo/utils/API/send_message.py` 通过。
- fake ok 测试：`final_status=reply_sent`。
- fake non-ok / exception 测试：`final_status=reply_send_failed`。
- fake unknown_delivery 测试：`final_status=reply_delivery_unknown`，且 `_send_reply()` 返回 `False`。
- grep 确认 `pdd.message.completed` 只在 `_send_reply()` 最终发送结果边界出现。
- 新增日志未记录完整 `reply` / `content` / `token` / `cookie`。

## T006：历史隐私债日志清理

状态：已完成。

目标：

清理历史日志中的完整或截断正文输出，例如旧的 `log_message(... 回复: ...)`、静态规则命中正文、SendMessage 原始 result 直出等，统一改为 length/hash 和安全摘要。

修改范围：

- Message handlers。
- PDD API request / response logs。
- FastGPT handler logs。
- `Reply.__str__()`。

清理原则：

- 不记录完整用户消息。
- 不记录完整 AI 回复。
- 不记录 token / cookie / access_token / authorization。
- 不记录完整 `response.text` / `resp.text` / `result`。
- 统一使用 `length` / `hash` / `type` / `status_code` / `error_type` / `request_id` / `trace_id`。

已知取舍：

- 调试日志可读性下降。
- 需要通过 `trace_id` 和数据库 / PDD 后台定位完整会话。

验证：

- `python -m py_compile` 本轮修改文件通过。
- grep 检查新增 diff 中未发现完整 `content` / `reply` / `response.text` / `resp.text` / `result` 输出。
- grep 检查未发现 token / cookie / access_token / authorization 值输出。

---

# 阶段 1：Linux 兼容盘点

## T010：扫描 Windows 路径和硬编码配置

状态：待执行。

目标：

扫描两个项目中的 Windows 路径、localhost、127.0.0.1、硬编码端口、绝对路径、bat/ps1 依赖、密钥/token/cookie 风险。

只输出报告，不改代码。

## T011：梳理服务依赖图

状态：待执行。

目标：

列出 FastGPT、MongoDB、PostgreSQL、Redis、MinIO、Ollama、proxy、FastAPI、PyQt、WebSocket worker 的依赖图和启动顺序。

## T012：梳理配置来源

状态：待执行。

目标：

梳理当前配置来自 `config.py`、`config.json`、`.env`、数据库、UI 输入或硬编码代码，并输出配置迁移建议。

---

# 阶段 2：Linux 配置化

## T020：增加 `.env.example`

状态：待执行。

## T021：统一配置加载

状态：待执行。

## T022：移除硬编码 Windows 路径

状态：待执行。

## T023：增加 Linux 日志目录配置

状态：待执行。

---

# 阶段 3：容器化

## T030：为后端 API 增加 Dockerfile

状态：待执行。

## T031：为 proxy 增加 Dockerfile

状态：待执行。

## T032：编写 docker-compose.private.yml

状态：待执行。

## T033：增加 healthcheck 和 restart policy

状态：待执行。

---

# 阶段 4：部署脚本

## T040：增加 deploy/linux/install.sh

状态：待执行。

## T041：增加 deploy/linux/start.sh

状态：待执行。

## T042：增加 deploy/linux/stop.sh

状态：待执行。

## T043：增加 deploy/linux/status.sh

状态：待执行。

## T044：增加 deploy/linux/backup.sh

状态：待执行。

## T045：增加 deploy/linux/diagnose.sh

状态：待执行。

---

# 阶段 5：验收

## T050：增加 smoke test

状态：待执行。

## T051：增加部署文档

状态：待执行。

## T052：增加回滚文档

状态：待执行。

---

## 下一步

下一步建议执行：`T010：Windows 路径和硬编码配置扫描`。

---

## T021-A: 统一配置加载前置审计

状态：已完成。

输出文件：

- `docs/config/T021_CONFIG_LOADING_AUDIT.md`

完成内容：

- 梳理当前配置来源：环境变量、`.env`、`core/config.py`、`core/config_manager.py`、旧 `config.py/config.json`、数据库 `AppConfig`、UI 输入、脚本参数、硬编码默认值。
- 扫描 customer-agent-refactor-v3 与可访问的 customer-agent-coze。
- 识别服务 URL、密钥、路径、Redis、Playwright、日志、DB 路径等配置分散点。
- 拆分后续最小改造任务：T021-B 到 T021-F。

## T021-B: 服务 URL 和密钥统一读取

状态：已完成。

修改文件：

- `core/settings.py`
- `app.py`
- `Message/handlers/fastgpt_handler.py`
- `core/config.py`
- `core/config_manager.py`
- `docs/config/ENVIRONMENT_VARIABLES.md`

完成内容：

- 新增轻量 `core/settings.py`，统一加载 `.env`，`override=False`。
- 提供 `get_str()`、`get_int()`、`get_bool()`。
- 统一读取 `FASTGPT_BASE_URL`、`FASTGPT_API_KEY`、`SESSION_COMPRESS_BASE_URL`、`SESSION_COMPRESS_API_KEY`、`LLM_API_BASE`、`LLM_API_KEY`、`LOCAL_MODEL_BASE_URL`。
- `APP_ENV=local` 时默认使用 `localhost` / `127.0.0.1`。
- `APP_ENV=linux` 或 `APP_ENV=production` 时默认使用 Docker service name。
- `app.py` 的 FastGPT API key / base URL 改为从 settings 获取，并保留 DB 历史兼容 fallback。
- `FastGPTHandler` 默认 URL 不再写死在构造函数参数中，显式传入 URL 仍优先生效。
- `SESSION_COMPRESS_BASE_URL` / `SESSION_COMPRESS_API_KEY` 改为从 settings helper 获取。
- `ConfigManager` 的 LLM / local model 默认 URL 复用 settings。

验证：

- `python -m py_compile core/settings.py app.py Message/handlers/fastgpt_handler.py core/config.py core/config_manager.py` 通过。
- `APP_ENV=local` 默认 FastGPT 为 `http://localhost:3000/api`。
- `APP_ENV=linux` 默认 FastGPT 为 `http://fastgpt:3000/api`。
- 显式 `FASTGPT_BASE_URL` 优先生效。
- 显式 `LOCAL_MODEL_BASE_URL` 优先生效。
- 未修改 `.env`。
- 未修改 customer-agent-coze。

已知限制：

- `core/settings.py` 是 import-time / startup 配置，UI 修改 `.env` 后不承诺当前进程热更新。
- `ConfigManager` 使用 `override=False` 后，外部环境变量优先于 `.env`。

未改范围：

- Redis。
- `DATA_DIR` / `LOG_DIR` / `DB_PATH`。
- Playwright。
- Docker。
- customer-agent-coze。
- 业务逻辑。

下一步任务：

- `T021-C`: 统一 `DATA_DIR` / `LOG_DIR` / `CACHE_DIR` / `DB_PATH`。

## T021-C: 统一 DATA_DIR / LOG_DIR / CACHE_DIR / DB_PATH 路径配置

状态：已完成。

修改文件：

- `core/settings.py`
- `database/db_manager.py`
- `core/di_container.py`
- `utils/runtime_path.py`
- `utils/logger_loguru.py`
- `utils/logger_config.py`
- `Knowledge/csv_exporter.py`
- `docs/config/ENVIRONMENT_VARIABLES.md`

完成内容：

- `core/settings.py` 增加 `DATA_DIR`、`LOG_DIR`、`CACHE_DIR`、`EXPORT_DIR`、`DB_PATH` 路径配置读取。
- 增加 `data_dir()`、`log_dir()`、`cache_dir()`、`export_dir()`、`db_path()` 等 helper，返回 `pathlib.Path`。
- `DatabaseManager` 默认路径改为来自 `settings.db_path()`，显式传入 `db_path` 仍优先生效。
- `core/di_container.py` 默认 `DatabaseManager` 路径改为来自 `settings.db_path()`，保留 `config_instance` 覆盖逻辑。
- `utils/runtime_path.py` 保留公开函数名，并接入 `settings` 路径配置。
- `logger_loguru.py` / `logger_config.py` 使用 `LOG_DIR` 生成日志文件路径。
- `Knowledge/csv_exporter.py` 默认导出目录改为 `EXPORT_DIR`。

路径优先级：

- `DB_PATH` 显式配置优先。
- 未配置 `DB_PATH` 时使用 `DATA_DIR/channel_shop.db`。
- `DATA_DIR` 默认 `./temp`，兼容旧 Windows 本地 DB。
- `LOG_DIR` 默认 `./logs`。
- `CACHE_DIR` 默认 `DATA_DIR/cache`。
- `EXPORT_DIR` 默认 `DATA_DIR/exports`。

未做事项：

- 不迁移 DB 文件。
- 不改 DB schema。
- 不改 Redis。
- 不改 Playwright。
- 不改 Docker。
- 不改 customer-agent-coze。
- 不改业务逻辑。

已知风险：

- CSV 默认导出目录从 `./temp` 调整为 `DATA_DIR/exports`。
- `utils/runtime_path.py` diff 较大，但公开函数名应保持兼容。

验证：

- `python -m py_compile core/settings.py database/db_manager.py core/di_container.py utils/runtime_path.py utils/logger_loguru.py utils/logger_config.py Knowledge/csv_exporter.py` 通过。
- fake env path 测试通过：`DATA_DIR=/tmp/agent-data` 时默认 DB 指向 `/tmp/agent-data/channel_shop.db`。
- fake env path 测试通过：`DB_PATH=/tmp/custom.db` 时显式 DB_PATH 优先生效。
- fake env path 测试通过：`LOG_DIR=/tmp/agent-logs` 时日志目录使用该值。
- 未设置路径变量时仍默认 `./temp/channel_shop.db`。
- `git diff --check` 通过。
- 未修改 `.env`。
- 未发现真实 key。

下一步任务：

- `T021-D`: 统一 Redis 配置。

---

## T021-D: Redis Settings Centralization

Status: completed.

Changed files:
- `core/settings.py`
- `core/config.py`
- `docs/config/ENVIRONMENT_VARIABLES.md`

Summary:
- Added centralized `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, and `REDIS_DB` loading in `core/settings.py`.
- `APP_ENV=local` defaults Redis host to `localhost`.
- `APP_ENV=linux` / `production` defaults Redis host to `redis`.
- Removed the hardcoded `REDIS_PASSWORD=123456` default; empty password remains the safe code default unless explicitly configured.
- Redis lock and Fail-Safe business semantics were not changed.

Verification:
- `python -m py_compile core/settings.py core/config.py` passed.
- Fake env tests passed for local/linux Redis defaults and explicit env override.
- `.env` was not modified.

## T021-E: Playwright Browser Path Centralization

Status: completed.

Changed files:
- `core/settings.py`
- `utils/playwright_path.py`
- `Channel/pinduoduo/pdd_login.py`
- `docs/config/ENVIRONMENT_VARIABLES.md`

Summary:
- Added `PLAYWRIGHT_BROWSERS_PATH` and `BROWSER_CACHE_DIR` loading in `core/settings.py`.
- Browser path priority is `PLAYWRIGHT_BROWSERS_PATH` > `BROWSER_CACHE_DIR` > project `.browsers` > Windows `LOCALAPPDATA/ms-playwright` fallback.
- `utils/playwright_path.py` now reads browser paths from settings while preserving public function names.
- Browser detection supports Windows and Linux Chromium/headless_shell layouts.
- `pdd_login.py` no longer unconditionally overwrites `PLAYWRIGHT_BROWSERS_PATH` during import.
- Windows local fallback and login behavior were preserved.

Verification:
- `python -m py_compile core/settings.py utils/playwright_path.py Channel/pinduoduo/pdd_login.py app.py` passed.
- Fake env tests passed for explicit `PLAYWRIGHT_BROWSERS_PATH`, explicit `BROWSER_CACHE_DIR`, project `.browsers`, and Windows fallback candidates.
- `.env` was not modified.

## T021-F: customer-agent-coze Proxy / Ollama / FastGPT Tool Config

Status: completed.

Changed files:
- `E:\develop\customer-agent-coze\ollama_proxy.py`
- `E:\develop\customer-agent-coze\projects\src\tools\knowledge_tool.py`
- `E:\develop\customer-agent-coze\projects\src\tools\llm_tool.py`
- `E:\develop\customer-agent-coze\projects\src\agents\agent.py`
- `E:\develop\customer-agent-coze\projects\config\agent_llm_config.json`
- `E:\develop\customer-agent-coze\projects\.env.example`
- `docs/config/ENVIRONMENT_VARIABLES.md`

Summary:
- `ollama_proxy.py` uses `OLLAMA_BASE_URL` > `OLLAMA_URL` > `APP_ENV` default priority.
- `PROXY_BIND_HOST` and `PROXY_PORT` are supported; CLI port argument still has the highest priority.
- `DOUBAO_AUTH` takes precedence over `Bearer <LLM_API_KEY>`.
- `knowledge_tool.py` uses explicit `KNOWLEDGE_BASE_URL` first, with local default `http://localhost:3000` and linux/production default `http://fastgpt:3000`.
- `llm_tool.py` and `agent.py` use `LLM_BASE_URL` > `LLM_API_BASE` > non-sensitive JSON fallback for base URL.
- `LLM_API_KEY` is read only from environment variables and is no longer read from JSON.
- `agent_llm_config.json` keeps `api_key` empty and does not store real keys.
- `projects/.env.example` documents proxy, Ollama, LLM, and Knowledge Base placeholders.

Verification:
- `python -m py_compile ollama_proxy.py projects/src/tools/knowledge_tool.py projects/src/tools/llm_tool.py projects/src/agents/agent.py` passed.
- `python -m json.tool projects/config/agent_llm_config.json` passed.
- Fake env tests passed for Ollama URL priority, Knowledge Base defaults, LLM base URL priority, and rejecting JSON `api_key` fallback.
- grep found no real `ark-` or `Bearer ark-` secrets.

## T021 Summary: Config Loading Centralization

Status: completed.

Key decisions:
- Added `core/settings.py` as the lightweight config entrypoint for `customer-agent-refactor-v3`.
- `APP_ENV=local` uses `localhost` / `127.0.0.1` defaults.
- `APP_ENV=linux` / `production` uses Docker service-name defaults.
- `DATA_DIR` defaults to `./temp` to preserve the legacy Windows local database location.
- Explicit `DB_PATH` wins; no database file migration is performed automatically.
- `REDIS_PASSWORD` no longer defaults to hardcoded `123456`.
- `PLAYWRIGHT_BROWSERS_PATH` / `BROWSER_CACHE_DIR` are configurable while preserving Windows fallback.
- In `customer-agent-coze`, `LLM_API_KEY` is environment-only and `agent_llm_config.json` must not store real keys.

Known limitations:
- `settings.py` is startup/import-time configuration and does not promise runtime hot reload.
- `customer-agent-coze` is currently not a Git repository, so version governance must be handled separately.
- Docker Compose is not completed.
- Headless worker is not completed.
- Health/status API is not completed.

Next task:
- `T060`: headless WebSocket worker pre-design.

---

## T060-A: headless WebSocket worker pre-design

Status: completed.

Output:
- Read-only design for a Linux headless worker that reuses `PDDChannel`, `MessageConsumer`, existing DB/config/status services, and does not start PyQt.
- Confirmed first production-safe model is one account per `PDDChannel` instance because `PDDChannel` still owns a single `self.ws`.

## T060-B: headless worker skeleton

Status: completed.

Changed files:
- `runtime/__init__.py`
- `runtime/worker.py`
- `runtime/account_loader.py`
- `runtime/health.py`

Summary:
- Added `python -m runtime.worker` entrypoint.
- Added `--dry-run`, `--status`, `--shop-id`, and `--user-id` skeleton behavior.
- Sets `HEADLESS_MODE=1` before DI setup.
- Does not import `app.py`, PyQt, or `QApplication`.
- Does not start a real WebSocket in dry-run/status mode.

## T060-C: headless worker single-account start

Status: completed.

Summary:
- `python -m runtime.worker --shop-id <shop_id> --user-id <user_id>` can create one independent `PDDChannel` and call `start_account()`.
- `--shop-id ... --user-id ... --dry-run` only validates/list accounts and does not connect WebSocket.
- Shutdown calls `channel.stop_all_connections()` instead of cancelling all tasks directly.

## T060-D: headless worker all-enabled orchestration

Status: completed.

Summary:
- `--all-enabled` supports real multi-account orchestration.
- Every account gets its own `PDDChannel` instance and its own asyncio task.
- Worker maintains `account_key -> channel/task` mappings.
- `--all-enabled --dry-run` still only lists candidate accounts.
- Candidate rule remains `channel_name == "pinduoduo" and status == 1`; this is not a durable auto-reply-enabled flag.

## T060-E: headless worker graceful shutdown diagnostics

Status: completed.

Summary:
- Added `WorkerState` fields for started/shutdown timestamps, running/failed/stopped accounts, channel ids, task ids, errors, and exit reason.
- Added account task lifecycle logs.
- Added worker shutdown status snapshot fields.
- Account start failure is isolated and does not kill the whole worker.

## T060-G: deterministic shutdown control

Status: completed.

Summary:
- Added deterministic shutdown triggers: `--run-seconds`, `--stop-file`, and `--shutdown-timeout`.
- SIGINT/SIGTERM/Ctrl+C/run-seconds/stop-file all route through `request_shutdown()`.
- Request shutdown is idempotent.
- No HTTP service or Docker changes were added.

## T060-G.1: Ctrl+C traceback cleanup

Status: completed.

Changed files:
- `runtime/worker.py`

Summary:
- `signal.signal` fallback no longer calls the previous default interrupt handler after requesting shutdown.
- `KeyboardInterrupt` routes through `request_shutdown(reason="keyboard_interrupt")`.
- `CancelledError` during requested shutdown is treated as part of normal shutdown and does not leak traceback.
- Outer `run()` catches `KeyboardInterrupt` / `CancelledError` and returns exit code `130`.
- `run-seconds` / `stop-file` normal shutdown exits with code `0`.

Verification:
- `python -m py_compile runtime\worker.py runtime\health.py runtime\account_loader.py runtime\__init__.py` passed.
- fake KeyboardInterrupt test stopped the channel and returned `130`.
- fake CancelledError shutdown test did not print traceback.
- `python -m runtime.worker --all-enabled --dry-run` passed.
- `python -m runtime.worker --status` passed.

## T060-G.2: consumer missing shutdown log noise cleanup

Status: completed.

Changed files:
- `Message/core/consumer.py`
- `Channel/pinduoduo/core/pdd_lifecycle.py`

Summary:
- `MessageConsumerManager.stop_consumer()` now accepts `missing_ok=False`.
- Default behavior is unchanged: missing consumer still logs ERROR for non-idempotent paths.
- Lifecycle shutdown cleanup passes `missing_ok=True`.
- Missing consumer during repeated shutdown cleanup is logged as already absent and returns `True`.

Verification:
- `python -m py_compile Message\core\consumer.py Channel\pinduoduo\core\pdd_lifecycle.py` passed.
- fake shutdown test confirmed first stop succeeds, second missing-ok stop returns `True` without ERROR.
- default `missing_ok=False` behavior still logs an error for missing consumers.

## T060-H: headless worker real shutdown acceptance

Status: completed.

Summary:
- Single-account real WebSocket startup was verified through the headless worker.
- `--run-seconds` graceful shutdown was accepted.
- `--stop-file` graceful shutdown was accepted.
- Ctrl+C / SIGINT graceful shutdown was accepted after `T060-G.1`.
- Shutdown path calls `PDDChannel.stop_all_connections()` and does not rely on global task cancellation.

Key decision:
- Headless worker must keep one `PDDChannel` instance per account.
- `PDDChannel` still owns a single `self.ws`; multi-account shared instances are forbidden.

---

## T061-A: worker status snapshot file

Status: completed.

Changed files:
- `runtime/worker.py`
- `runtime/health.py`
- `core/settings.py`
- `docs/config/ENVIRONMENT_VARIABLES.md`

Summary:
- Running worker writes `worker_status.json`.
- Default status file path is `DATA_DIR/runtime/worker_status.json`.
- Status writer uses atomic temp-file replace.
- Snapshot includes worker id, pid, app env, timestamps, account states, channel ids, task ids, connected count, and exit reason.

## T061-A.1: final snapshot semantics fix

Status: completed.

Summary:
- Final snapshot normalizes stopped workers so `connected_count=0`.
- Final snapshot uses `snapshot_phase=final` and `worker_state=stopped`.
- Stopped account connections are no longer reported as connected in final status.

## T061-B: CLI status reads worker status file

Status: completed.

Summary:
- `python -m runtime.worker --status` reads `WORKER_STATUS_PATH` / `DATA_DIR/runtime/worker_status.json`.
- Added `--status-file`, `--status-stale-seconds`, and `--json` support.
- Exit codes: missing `2`, invalid `3`, stale `4`, valid running/stopped `0`.

## T061-C: CLI healthcheck

Status: completed.

Summary:
- Added `python -m runtime.worker --healthcheck`.
- Designed for Docker healthcheck, systemd checks, and diagnose scripts.
- Health exit codes: healthy `0`, degraded `1`, missing `2`, invalid `3`, stale `4`, stopped `5`.
- `stopped=5` means the worker is not running; it is expected after bounded smoke tests but unhealthy for service liveness.

## T061-D: healthcheck / smoke scripts and runbook

Status: completed.

Changed files:
- `scripts/runtime/healthcheck.ps1`
- `scripts/runtime/healthcheck.sh`
- `scripts/runtime/smoke_worker.ps1`
- `scripts/runtime/smoke_worker.sh`
- `docs/runtime/HEADLESS_WORKER_RUNBOOK.md`

Summary:
- Added PowerShell and shell healthcheck wrappers.
- Added PowerShell and shell smoke test wrappers.
- Smoke scripts treat healthcheck exit code `5` (`stopped`) as expected after `--run-seconds`.
- Runbook documents single-account start, all-enabled start, run-seconds, stop-file, status, healthcheck, and exit codes.

---

## T062: headless worker diagnose package export

Status: completed.

Changed files:
- `scripts/runtime/diagnose.ps1`
- `scripts/runtime/diagnose.sh`
- `docs/runtime/DIAGNOSE_PACKAGE.md`
- `docs/runtime/HEADLESS_WORKER_RUNBOOK.md`

Summary:
- Added one-command diagnose package export for private deployment troubleshooting.
- Package includes redacted worker status, `--status --json`, `--healthcheck --json`, recent log tails, `.env.example`, config/runtime docs, Python and OS metadata, and optional Git status.
- Package does not include `.env`, databases, browser caches, full runtime directories, or message history.
- Redaction masks common credential/session fields and token-like values before files are written into the package.

## T062-A: diagnose artifact Git protection

Status: completed.

Changed files:
- `.gitignore`

Summary:
- Added explicit ignore rules for `runtime.stop`, `worker_status.json`, `diagnostics/`, and `**/diagnostics/`.
- Existing ignore rules already covered `.env`, `.env.*`, `.browsers/`, `logs/`, `*.log`, and `temp/`.
- Verified runtime artifacts are ignored and are not shown as untracked source changes.

Next task:
- `T063`: Linux/systemd service draft and start/stop/status/diagnose scripts.

---

## T063: Linux/systemd deployment skeleton

Status: completed.

Changed files:
- `deploy/linux/customer-agent-worker.service.example`
- `deploy/linux/start.sh`
- `deploy/linux/stop.sh`
- `deploy/linux/status.sh`
- `deploy/linux/healthcheck.sh`
- `deploy/linux/diagnose.sh`
- `deploy/linux/README_SYSTEMD.md`

Summary:
- Added Linux/systemd service skeleton for the headless worker.
- Added start / stop / status / healthcheck / diagnose helper scripts.
- Service skeleton runs `python -m runtime.worker --all-enabled --status-interval 5`.
- Helper scripts reuse existing runtime status, healthcheck, and diagnose commands.
- No Docker Compose and no Python business code changes were made.

## T063-A: systemd stop-file closure

Status: completed.

Summary:
- `ExecStart` now passes `--stop-file /opt/customer-agent-refactor-v3/runtime.stop`.
- `ExecStop` touches the same stop-file path.
- `ExecStartPre` removes stale `runtime.stop` before startup.
- `start.sh` removes the stop file before foreground startup and passes the same `--stop-file`.
- `stop.sh` touches the same stop file and requests graceful shutdown instead of killing the worker directly.

## T064: Linux/systemd deployment skeleton static acceptance

Status: completed.

Summary:
- Static acceptance completed for `deploy/linux`.
- Service example includes `WorkingDirectory`, `EnvironmentFile`, `ExecStartPre`, `ExecStart`, `ExecStop`, `TimeoutStopSec=30`, `Restart=on-failure`, and `RestartSec=5`.
- `start.sh` supports `REPO_ROOT`, `STOP_FILE`, and `STATUS_INTERVAL` overrides.
- `stop.sh`, `status.sh`, `healthcheck.sh`, and `diagnose.sh` support `REPO_ROOT` override.
- README documents `.env`, stop-file lifecycle, status file, healthcheck exit codes, logs, diagnose, and common failures.

Verification:
- `git diff --check -- deploy/linux` passed.
- grep confirmed service contains `ExecStartPre`, `ExecStart`, `ExecStop`, `--stop-file`, and `TimeoutStopSec`.
- grep confirmed `start.sh` and `stop.sh` share `STOP_FILE="${STOP_FILE:-$REPO_ROOT/runtime.stop}"`.
- grep found no real keys, `ark-`, `Bearer`, or `fastgpt-` values in `deploy/linux`.
- No Python files were modified.
- `shellcheck` was not available; `bash -n` could not run because the Windows WSL bash shim had no `/bin/bash`.

Known limitations:
- `deploy/linux` has only static validation so far.
- It has not yet been executed on a real Linux/systemd host.
- Docker Compose is still not completed.
- FastGPT business workflow has not yet been accepted in the Linux deployment shape.

Next tasks:
- `T065`: Linux real-machine deployment acceptance checklist.
- `T066`: systemd real-machine verification.
