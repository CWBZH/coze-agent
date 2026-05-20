# DECISIONS.md

## D001：当前一个店铺就是一个账号

状态：已确认。

说明：

当前业务假设是一个拼多多店铺对应一个客服账号。

影响：

1. 暂时不强制将 `queue_name` 从 `pdd_{shop_id}` 改成 `pdd_{shop_id}_{user_id}`。
2. 后续如果支持同店铺多账号，需要重新评估 queue 隔离模型。
3. 当前重构优先修 consumer 幂等、worker pool、重连 generation、graceful shutdown。

## D002：短期不修改业务回复逻辑

状态：已确认。

说明：

当前重构重点是运行时稳定性，不是业务策略。

禁止随意修改：

1. `MessagePipeline`
2. `AIReplyHandler`
3. FastGPT 调用逻辑
4. 关键词规则逻辑
5. 人工接管业务流程
6. 转人工文案策略

除非用户明确要求。

## D003：保留 Windows 本地启动能力

状态：已确认。

说明：

虽然目标是 Linux 私有化部署，但 Windows 本地版本仍需要保留。

影响：

1. 不删除 Windows 一键启动脚本。
2. 不删除 PyQt UI。
3. 不强制把所有逻辑一次性迁移到 Linux。
4. 新增代码应尽量跨平台。

## D004：Linux 私有化部署是目标交付形态

状态：已确认。

说明：

未来可交付形态应支持 Linux 服务器部署。

目标包括：

1. Docker Compose 部署。
2. `.env` 配置。
3. 日志目录。
4. 健康检查。
5. 服务自动重启。
6. 诊断脚本。
7. 备份脚本。

## D005：P0 consumer setup 幂等化已完成

状态：已完成。

修改范围：

1. `Message/core/consumer.py`
2. `Message/__init__.py`
3. `Channel/pinduoduo/core/pdd_message_handler.py`

已完成内容：

1. `MessageConsumer` 记录所属 event loop。
2. 新增 `is_bound_to_current_loop()`。
3. 新增 `loop_id()`。
4. 新增 `handler_count()`。
5. 新增 `diagnostic_state()`。
6. `add_handler()` 按 handler 类去重。
7. `start()` 已运行时直接复用。
8. `stop_from_any_loop(timeout)` 支持跨 loop 调度停止。
9. `MessageConsumerManager.stop_consumer()` 返回 bool。
10. `force_remove()` 拒绝移除仍在运行的 consumer。
11. `create_consumer()` 遇到已运行 consumer 时直接返回。
12. `_setup_message_consumer()` 已有运行中且同 loop consumer 时直接复用。
13. 不再无条件 `recreate_queue()`。
14. 改为 `get_or_create_queue()`。

验证：

1. `python -m py_compile` 通过。
2. 内联异步幂等测试通过。
3. 连续两次 `_setup_message_consumer("pdd_idempotency_test")` 后 consumer 未重建。
4. `handler_count() == 1`。
5. `stop_consumer(timeout=5.0)` 正常退出。

## D006：后续需要引入 reconnect generation

状态：已完成。

目标：

防止旧 reconnect task / cleanup task 误清理新连接。

结果：

已通过 D010 引入 reconnect lifecycle lock + generation。

## D007：后续需要 graceful shutdown

状态：已完成。

目标：

停止账号或退出程序时，先完成资源清理，再关闭 event loop。

正确顺序：

1. set stop_event
2. stop receiving new messages
3. cancel heartbeat/message/reconnect tasks
4. await cancellation with timeout
5. close websocket
6. wait websocket closed
7. stop consumer
8. clear processing tasks
9. remove session/manager references
10. stop event loop

禁止：

不要先 stop event loop，再尝试执行 async cleanup。

结果：

已通过 D011、D012、D013 完成 graceful shutdown 的分阶段改造。

## D008：当前下一步建议任务是 T010

状态：已确认。

说明：

`T006` 历史隐私债日志清理已完成，下一步建议执行 `T010：Windows 路径和硬编码配置扫描`。

## D009：MessageConsumer 已改为固定 worker pool

状态：已完成。

修改文件：

1. `Message/core/consumer.py`

决策：

将 `MessageConsumer` 从“每条消息创建一个 asyncio task”的模式改为“固定 worker pool”模式。

原因：

旧模型即使通过 semaphore 限制并发处理数量，也不能限制已创建 task 的数量。消息积压或断线重连场景下，等待中的 task 可能持续增长并推高内存占用。

已完成内容：

1. `MessageConsumer.start()` 按 `max_concurrent` 固定创建 worker task。
2. 新增 `_worker_tasks` 记录 worker task 集合。
3. 新增 `_worker_loop(worker_id)`，worker 循环从 queue 读取消息并调用原 `_process_message()`。
4. 不再按每条消息无限 `create_task(_process_message)`。
5. `MessageConsumer.stop()` 会 cancel worker tasks，并通过 `asyncio.gather(..., return_exceptions=True)` + timeout 等待退出。
6. `diagnostic_state()` 增加 `worker_count` 和 `worker_task_ids`。
7. 保持 handler 执行逻辑不变。
8. 保持 `queue_name = pdd_{shop_id}` 不变。

验证结果：

1. `python -m py_compile Message/core/consumer.py Message/__init__.py` 通过。
2. `max_concurrent=3` 时 `worker_count == 3`。
3. 连续 put 12 条测试消息时 worker task id 保持不变。
4. `consumer._tasks == 0`。
5. `stop_consumer(timeout=5.0)` 后 `running=False` 且 `worker_count == 0`。

## D010：已引入 reconnect lifecycle lock + generation

状态：已完成。

修改文件：

1. `Channel/pinduoduo/core/pdd_lifecycle.py`
2. `Channel/pinduoduo/core/pdd_connection.py`
3. `Channel/pinduoduo/pdd_channel.py`

决策：

为拼多多 WebSocket 连接生命周期引入 per-connection lifecycle lock 和 generation 机制，防止同一个 `connection_key` 重复 start/reconnect 时旧任务误清理新连接。

关键结果：

1. `start_account()` 使用 per-connection lifecycle lock。
2. 旧 reconnect task cancel 后会 await，避免 cancel 后直接删除再创建新 task。
3. generation 每次新连接流程自增。
4. generation 已传递到 connect / init / cleanup / heartbeat。
5. stale generation 不会执行 `_cleanup_resources()`。
6. stale generation 不会清理当前 `ws`。
7. 最大重试失败分支的 `stop_event.set()` 已加 generation guard。
8. 保持 `queue_name = pdd_{shop_id}` 不变。
9. 未修改业务消息处理逻辑。

验证结果：

1. `python -m py_compile Channel/pinduoduo/core/pdd_lifecycle.py Channel/pinduoduo/core/pdd_connection.py Channel/pinduoduo/pdd_channel.py` 通过。
2. `python -m py_compile Channel/pinduoduo/core/pdd_connection.py` 通过。
3. 连续两次 `start_account()` 时 generation 从 1 到 2。
4. 旧 reconnect task 被 cancel，并 await 到 done。
5. stale generation 调用 cleanup 不清理当前 `ws`。

后续：

下一步执行 `T003：graceful shutdown`。

## D011：WebSocket 安全关闭已增加 wait_closed 和 timeout

状态：已完成。

修改文件：

1. `Channel/pinduoduo/core/pdd_connection.py`

决策：

`ConnectionMixin._safe_close_websocket()` 已增强 WebSocket 安全关闭逻辑，在 `close()` 后继续等待 `wait_closed()`，并为两个阶段都增加有界 timeout，降低 event loop 关闭时 WebSocket close handshake 未完成的风险。

关键结果：

1. `ws` 为空时直接返回。
2. `close()` 返回 coroutine 时使用 `asyncio.wait_for(..., timeout=5.0)`。
3. `wait_closed()` 返回 coroutine 时使用 `asyncio.wait_for(..., timeout=5.0)`。
4. `close()` 和 `wait_closed()` 各自只 await 一次。
5. 未修改调用方。
6. 未修改业务逻辑。
7. 保持 `queue_name = pdd_{shop_id}` 不变。

验证结果：

1. `python -m py_compile Channel/pinduoduo/core/pdd_connection.py` 通过。
2. fake websocket 测试通过。
3. `close_called == True`。
4. `wait_closed_called == True`。
5. 未出现 `RuntimeError: cannot reuse already awaited coroutine`。

后续：

下一步建议执行 `T010：Windows 路径和硬编码配置扫描`。

## D016：历史隐私债日志清理已完成

状态：已完成。

修改范围：

1. Message handlers。
2. PDD API request / response logs。
3. FastGPT handler logs。
4. `Reply.__str__()`。

决策：

将旧日志中可能输出完整用户消息、完整 AI 回复、回复预览、消息预览、原始 API 响应的位置，统一改为摘要字段。

清理原则：

1. 不记录完整用户消息。
2. 不记录完整 AI 回复。
3. 不记录 token / cookie / access_token / authorization。
4. 不记录完整 `response.text` / `resp.text` / `result`。
5. 统一使用 `length` / `hash` / `type` / `status_code` / `error_type` / `request_id` / `trace_id`。

已知取舍：

1. 调试日志可读性下降。
2. 需要通过 `trace_id` 和数据库 / PDD 后台定位完整会话。

验证结果：

1. `python -m py_compile` 本轮修改文件通过。
2. grep 检查新增 diff 中未发现完整 `content` / `reply` / `response.text` / `resp.text` / `result` 输出。
3. grep 检查未发现 token / cookie / access_token / authorization 值输出。

后续：

下一步建议执行 `T010：Windows 路径和硬编码配置扫描`。

## D015：message trace 闭环已完成

状态：已完成。

修改文件：

1. `Channel/pinduoduo/core/pdd_message_handler.py`
2. `Channel/pinduoduo/pdd_message.py`
3. `bridge/context.py`
4. `Message/models/queue_models.py`
5. `Message/core/consumer.py`
6. `Message/handlers/ai_handler.py`
7. `Message/core/pipeline.py`

决策：

在不改变业务逻辑、不修改 `queue_name` 的前提下，完成单条买家消息的 trace 闭环：

```text
WebSocket -> Context -> Queue -> Consumer -> Handler -> Pipeline -> AI -> SendMessage
```

关键结果：

1. `T005-A` 已完成 WebSocket -> Context -> MessageWrapper -> Consumer 的 `trace_id` / `source_message_id` / `queue_message_id` 透传。
2. `T005-A.1` 已修正 `shop_id` 为空时的 `trace_id` 规则，并将高频 trace 事件降为 debug。
3. `T005-B` 已完成 `AIReplyHandler` / `MessagePipeline` 的 pipeline、AI、静态规则、人工锁、转人工 outcome 日志。
4. `T005-B.1` 已修正事件语义：pipeline outcome 使用 `pdd.pipeline.*`，真实 FastGPT 调用边界才使用 `pdd.ai.request.*`。
5. `T005-C` 已完成 SendMessage 发送结果追踪。
6. `T005-C.1` 已修正 unknown delivery 的 final_status 语义。

final_status 语义：

1. `reply_sent`：PDD 明确返回 ok。
2. `reply_send_failed`：非 ok / None / 异常 / 缺少发送字段。
3. `reply_delivery_unknown`：调用成功但无明确 ok。

事件边界：

1. `pdd.message.completed` 只在 SendMessage 发送结果明确后记录。
2. Pipeline 阶段不记录 `pdd.message.completed`。
3. `pdd.ai.request.started` / `pdd.ai.request.succeeded` / `pdd.ai.request.failed` 只用于真实 FastGPT 调用边界。
4. `pdd.reply.send.succeeded` 只在 PDD 明确返回 ok 时记录。
5. unknown delivery 使用 `pdd.reply.send.call_succeeded status=unknown_delivery`。

主要事件：

1. `pdd.message.received`
2. `pdd.message.queued`
3. `pdd.consumer.dequeued`
4. `pdd.pipeline.started`
5. `pdd.ai.request.started`
6. `pdd.ai.request.succeeded`
7. `pdd.reply.send.started`
8. `pdd.reply.send.succeeded`
9. `pdd.reply.send.failed`
10. `pdd.reply.send.call_succeeded status=unknown_delivery`
11. `pdd.message.completed final_status=...`

隐私原则：

1. 不记录完整用户消息。
2. 不记录完整 AI 回复。
3. 只记录 `content_length` / `content_hash` / `reply_length` / `reply_hash`。
4. 不记录 token / cookie / access_token。

验证结果：

1. `py_compile` 通过。
2. fake trace metadata test 通过。
3. fake reply / transfer_human / skip 测试通过。
4. fake SendMessage ok / non-ok / unknown_delivery / exception 测试通过。
5. grep 确认新增 trace 日志未记录完整 `content` / `reply` / `token` / `cookie`。

后续：

下一步建议执行 `T006：历史隐私债日志清理` 或 `T010：Linux 兼容扫描`。

## D013：AutoReplyThread.stop 已改为 graceful shutdown

状态：已完成。

修改文件：

1. `ui/auto_reply/threads.py`

决策：

`AutoReplyThread.stop()` 不再直接全量 cancel 当前 event loop 上的 tasks，而是先向线程内 event loop 提交 shutdown coroutine，等待 `channel.stop_all_connections()` 完成后再停止 loop，降低 pending task destroyed、consumer 未停完、WebSocket close handshake 未完成的风险。

关键结果：

1. `AutoReplyThread.stop()` 不再直接 `asyncio.all_tasks(self.loop)` 全量 cancel。
2. `stop()` 使用 `asyncio.run_coroutine_threadsafe(self._shutdown_async(), self.loop)`。
3. `_shutdown_async()` 先 `await self.channel.stop_all_connections()`。
4. pending tasks 使用 `asyncio.gather(..., return_exceptions=True)` + `asyncio.wait_for(..., timeout=5.0)` 清理。
5. `run()` finally 在 `_shutdown_complete=True` 时不重复 cleanup。
6. 未修改业务逻辑。
7. 保持 `queue_name = pdd_{shop_id}` 不变。

验证结果：

1. `python -m py_compile ui/auto_reply/threads.py` 通过。
2. T003-C 只修改 `ui/auto_reply/threads.py`。

已知风险：

1. `stop()` 最多等待 5 秒。
2. 外层 `thread.wait(5000)` 存在最坏接近 10 秒 UI 阻塞风险，后续根据实测优化。

后续：

下一步建议执行 `T006：历史隐私债日志清理` 或 `T010：Linux 兼容扫描`。

## D012：shutdown task map 清理保留未退出 task 引用

状态：已完成。

修改文件：

1. `Channel/pinduoduo/core/pdd_lifecycle.py`
2. `Channel/pinduoduo/pdd_channel.py`

决策：

`LifecycleMixin.stop_account()` 和 `stop_all_connections()` 已统一 await 清理顺序，并且 `_cancel_mapped_task()` 在 cancel timeout 后会保留仍未完成的 task 引用，避免误删仍运行 task 或误删已替换的新 task。

关键结果：

1. `stop_account()` 会依次 set stop_event、cancel reconnect / heartbeat / message / stop-wait task、await with timeout、close websocket、cleanup resources、更新 DISCONNECTED、清理当前 key。
2. `stop_all_connections()` 会 set 所有 stop_event，cancel 并 await 所有 task maps，close websocket，然后按 `connection_key -> queue_name` 映射逐个 cleanup。
3. 新增 `_connection_queue_names` 显式记录 queue name，不通过 `connection_key.split()` 反推。
4. 继续保持 `queue_name = pdd_{shop_id}`。
5. `cleanup_processing_tasks()` 已增加 timeout，避免无限等待。
6. `_cancel_mapped_task()` timeout 后如果 task 仍未 done，会保留 map 引用。
7. `_cancel_mapped_task()` pop 前确认 `current is task`，避免误删新 task。
8. 未修改 UI。
9. 未修改业务逻辑。

验证结果：

1. `python -m py_compile Channel/pinduoduo/core/pdd_lifecycle.py Channel/pinduoduo/pdd_channel.py` 通过。
2. `python -m py_compile Channel/pinduoduo/core/pdd_lifecycle.py` 通过。
3. fake task 测试通过。
4. 已完成 task 会被 pop。
5. cancel 后正常完成的 task 会被 pop。
6. cancel 后超时且仍未 done 的 task 不会被 pop。
7. map 中已被新 task 替换时不会误删新 task。

后续：

下一步建议执行 `T006：历史隐私债日志清理` 或 `T010：Linux 兼容扫描`。

## D014：runtime observability 和 message trace 基线已完成

状态：已完成。

修改文件：

1. `ui/auto_reply/threads.py`
2. `Channel/pinduoduo/core/pdd_lifecycle.py`
3. `Channel/pinduoduo/core/pdd_connection.py`
4. `Channel/pinduoduo/core/pdd_message_handler.py`
5. `Channel/pinduoduo/pdd_message.py`
6. `bridge/context.py`
7. `Message/models/queue_models.py`
8. `Message/core/consumer.py`

决策：

在不改变业务逻辑、不修改 `queue_name` 的前提下，补齐运行时诊断日志和单条消息 trace 基线，让断线重连、停止流程、队列消费和消息处理链路可追踪。

T004 关键结果：

1. `AutoReplyThread.run()` 增加 loop / channel / start_task / run_forever / loop close 诊断日志。
2. `AutoReplyThread.stop()` 增加 shutdown_started / future timeout / fallback loop.stop / shutdown_complete 诊断日志。
3. `LifecycleMixin.start_account()` 增加 lifecycle lock、generation、reconnect task 创建日志。
4. `LifecycleMixin.stop_account()` 和 `stop_all_connections()` 增加 shutdown 阶段、task cancel、websocket close、consumer cleanup 日志。
5. `MessageConsumer.start()` / `stop()` 增加 worker_count、loop_id、consumer_id、handler_count 日志。
6. `_setup_message_consumer()` 增加 existing consumer reused / replaced / rejected 诊断日志。

T005-A 关键结果：

1. WebSocket 原始消息解析后生成 `trace_id`。
2. 有 PDD 原始 `msg_id` 时使用 `pdd:{shop_id}:{msg_id}`。
3. 无 `msg_id` 时使用 12 位短 uuid。
4. 保留 `source_message_id`，对应 PDD 原始 `msg_id`。
5. 将 `trace_id` / `source_message_id` 写入 `Context.kwargs`。
6. `MessageWrapper` 保留并输出 `trace_id`、`source_message_id`、`queue_message_id`、`shop_id`、`user_id`、`from_uid`、`to_uid`、`queue_name`、`message_type`、`content_length`、`content_hash`。
7. `MessageConsumer._process_message()` 日志携带 `trace_id` / `source_message_id` / `queue_message_id`。
8. 新增事件日志：`pdd.message.received`、`pdd.context.created`、`pdd.message.queued`、`pdd.consumer.dequeued`、`pdd.handler.selected`、`pdd.handler.completed`、`pdd.handler.failed`、`pdd.message.skipped`。

T005-A.1 小补丁：

1. `shop_id` 为空时 `trace_id` 使用 `unknown`。
2. 所有 ID 统一转为字符串。
3. 高频 trace 事件降为 debug。
4. `pdd.message.skipped` 保持 info。
5. `pdd.handler.failed` 保持 warning/error。

隐私约束：

1. 新增日志不记录完整买家消息内容。
2. 新增日志不记录完整 AI 回复。
3. 新增日志不记录 token / cookie / access_token。
4. 消息内容仅记录 `content_length` 和截断 `content_hash`。

验证结果：

1. `py_compile` 通过。
2. fake trace metadata test 通过。
3. trace id rule test 通过。
4. 新增日志未记录完整 `content` / `token` / `cookie`。

后续：

下一步建议执行 `T006：历史隐私债日志清理` 或 `T010：Linux 兼容扫描`。

## D017: T021-A/B 统一配置加载进展

状态：已完成。

相关任务：

- `T021-A`: 统一配置加载前置审计已完成。
- `T021-B`: 服务 URL 和密钥统一读取已完成。

修改文件：

- `core/settings.py`
- `app.py`
- `Message/handlers/fastgpt_handler.py`
- `core/config.py`
- `core/config_manager.py`
- `docs/config/ENVIRONMENT_VARIABLES.md`
- `docs/config/T021_CONFIG_LOADING_AUDIT.md`

决策：

- 新增轻量 `core/settings.py` 作为服务 URL 和密钥类配置的集中读取层。
- `core/settings.py` 统一加载 `.env`，使用 `override=False`，保持外部环境变量优先。
- `core/settings.py` 提供 `get_str()`、`get_int()`、`get_bool()`。
- 当前统一读取 `FASTGPT_BASE_URL`、`FASTGPT_API_KEY`、`SESSION_COMPRESS_BASE_URL`、`SESSION_COMPRESS_API_KEY`、`LLM_API_BASE`、`LLM_API_KEY`、`LOCAL_MODEL_BASE_URL`。

默认值策略：

- `APP_ENV=local` 时使用 Windows/local 友好的 `localhost` / `127.0.0.1` 默认值。
- `APP_ENV=linux` 或 `APP_ENV=production` 时使用 Docker service name 默认值，例如 `fastgpt`、`ollama`、`ollama-proxy`。
- 生产环境仍建议显式配置服务 URL 和密钥，不依赖推断默认值。

已知限制：

- `core/settings.py` 是 import-time / startup 配置。
- UI 修改 `.env` 后，不承诺当前进程热更新已导入的 settings 常量。
- `ConfigManager` 使用 `override=False` 后，外部环境变量优先于 `.env`。

未改范围：

- Redis。
- `DATA_DIR` / `LOG_DIR` / `DB_PATH`。
- Playwright。
- Docker。
- customer-agent-coze。
- 业务逻辑。

验证结果：

- `python -m py_compile core/settings.py app.py Message/handlers/fastgpt_handler.py core/config.py core/config_manager.py` 通过。
- `APP_ENV=local` 默认 FastGPT 为 `http://localhost:3000/api`。
- `APP_ENV=linux` 默认 FastGPT 为 `http://fastgpt:3000/api`。
- 显式 `FASTGPT_BASE_URL` 优先生效。
- 显式 `LOCAL_MODEL_BASE_URL` 优先生效。
- 未修改 `.env`。
- 未修改 customer-agent-coze。

后续：

- 下一步任务为 `T021-C`: 统一 `DATA_DIR` / `LOG_DIR` / `CACHE_DIR` / `DB_PATH`。

## D018: T021-C 路径配置集中化已完成

状态：已完成。

相关任务：

- `T021-C`: 统一 `DATA_DIR` / `LOG_DIR` / `CACHE_DIR` / `DB_PATH` 路径配置已完成。

修改文件：

- `core/settings.py`
- `database/db_manager.py`
- `core/di_container.py`
- `utils/runtime_path.py`
- `utils/logger_loguru.py`
- `utils/logger_config.py`
- `Knowledge/csv_exporter.py`
- `docs/config/ENVIRONMENT_VARIABLES.md`

决策：

- `core/settings.py` 统一读取 `DATA_DIR`、`LOG_DIR`、`CACHE_DIR`、`EXPORT_DIR`、`DB_PATH`。
- 路径 helper 使用 `pathlib.Path`。
- 使用点按需创建目录，避免在 import 阶段创建过多无关目录。
- `DatabaseManager` 显式传入 `db_path` 时继续优先生效。
- `core/di_container.py` 保留 `config_instance` 覆盖逻辑。
- `utils/runtime_path.py` 保留原公开函数名，并接入集中路径配置。

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
- `utils/runtime_path.py` diff 较大，但公开函数应保持兼容。

验证结果：

- `python -m py_compile core/settings.py database/db_manager.py core/di_container.py utils/runtime_path.py utils/logger_loguru.py utils/logger_config.py Knowledge/csv_exporter.py` 通过。
- fake env path 测试通过：`DATA_DIR=/tmp/agent-data` 时默认 DB 指向 `/tmp/agent-data/channel_shop.db`。
- fake env path 测试通过：`DB_PATH=/tmp/custom.db` 时显式 DB_PATH 优先生效。
- fake env path 测试通过：`LOG_DIR=/tmp/agent-logs` 时日志目录使用该值。
- 未设置路径变量时仍默认 `./temp/channel_shop.db`。
- `git diff --check` 通过。
- 未修改 `.env`。
- 未发现真实 key。

后续：

- 下一步任务为 `T021-D`: 统一 Redis 配置。

---

## D019: T021 Config Loading Centralization Completed

Status: completed.

Related tasks:
- `T021-A`: config loading audit completed.
- `T021-B`: service URL / key centralization completed.
- `T021-C`: `DATA_DIR` / `LOG_DIR` / `CACHE_DIR` / `DB_PATH` path centralization completed.
- `T021-D`: Redis settings completed.
- `T021-E`: Playwright browser path settings completed.
- `T021-F`: `customer-agent-coze` / proxy / Ollama / FastGPT tool config completed.

Key decisions:
1. Added `core/settings.py` as the lightweight config entrypoint for `customer-agent-refactor-v3`.
2. `core/settings.py` loads `.env` with `override=False`, keeping external environment variables first.
3. `APP_ENV=local` uses `localhost` / `127.0.0.1` defaults.
4. `APP_ENV=linux` / `production` uses Docker service-name defaults.
5. `DATA_DIR` defaults to `./temp` to preserve legacy Windows local DB compatibility.
6. Explicit `DB_PATH` wins; without it, DB path is `DATA_DIR/channel_shop.db`.
7. No automatic database migration is performed and DB schema is not changed.
8. `REDIS_PASSWORD` no longer defaults to hardcoded `123456`; production must configure it explicitly when needed.
9. `PLAYWRIGHT_BROWSERS_PATH` / `BROWSER_CACHE_DIR` are configurable while preserving Windows `.browsers` / `LOCALAPPDATA/ms-playwright` fallback.
10. In `customer-agent-coze`, `LLM_API_KEY` is environment-only and `agent_llm_config.json` no longer stores real keys.
11. `OLLAMA_BASE_URL` takes precedence over legacy `OLLAMA_URL`; CLI proxy port still takes precedence over `PROXY_PORT`.
12. `KNOWLEDGE_BASE_URL` defaults to `http://localhost:3000` locally and `http://fastgpt:3000` for linux/production.

Not changed:
- Docker Compose is not implemented.
- Headless worker is not implemented.
- Health/status API is not implemented.
- PDDChannel / MessagePipeline / SendMessage business logic is not changed.
- Windows local startup capability is not removed.

Known limitations:
1. `settings.py` is startup/import-time configuration and does not promise runtime hot reload.
2. UI updates to `.env` do not guarantee automatic refresh for modules already imported in the current process.
3. `customer-agent-coze` is currently not a Git repository, so version governance must be handled separately.
4. Config centralization now covers the main local and Linux delivery defaults, but deployment orchestration is still pending.

Verification summary:
- T021-B/C/D/E `py_compile` and fake env tests passed.
- T021-F `py_compile`, `json.tool`, and fake env tests passed.
- grep found no real `ark-` / `Bearer ark-` secrets in the updated config surfaces.
- `.env` was not modified or reintroduced to Git tracking.

Next task:
- `T060`: headless WebSocket worker pre-design.

---

## D020: Headless WebSocket worker baseline completed

Status: completed.

Related tasks:
- `T060-A`: headless worker pre-design completed.
- `T060-B`: headless worker skeleton completed.
- `T060-C`: single-account real start completed.
- `T060-D`: all-enabled multi-account orchestration completed.
- `T060-E`: worker graceful shutdown diagnostics completed.
- `T060-G`: deterministic shutdown control completed.

Changed files:
- `runtime/__init__.py`
- `runtime/worker.py`
- `runtime/account_loader.py`
- `runtime/health.py`

Key decisions:
1. The headless worker does not import `app.py`, PyQt, PySide, or `QApplication`.
2. `HEADLESS_MODE=1` is set before DI service initialization.
3. The worker reuses existing `PDDChannel`, queue, consumer, handler, DB, and config components.
4. Because `PDDChannel` still owns a single `self.ws`, multi-account headless mode uses one independent `PDDChannel` instance per account.
5. `--all-enabled` uses candidate rule `channel_name == "pinduoduo" and status == 1`; this is not yet a durable auto-reply-enabled flag.
6. Shutdown should call `channel.stop_all_connections()` and should not use global `asyncio.all_tasks()` cancellation.
7. `--run-seconds`, `--stop-file`, SIGINT, and SIGTERM all route through the same idempotent `request_shutdown()` path.

Verification summary:
- runtime py_compile passed.
- dry-run and status commands passed.
- fake multi-account tests covered success, partial failure, shutdown, and timeout behavior.
- runtime source has no PyQt/QApplication imports.
- runtime source has no cookie/password/token/access_token/authorization log strings.

Known limitations:
1. No HTTP health/status API yet.
2. No Docker service wrapper yet.
3. Real long-duration multi-account soak test is still pending.
4. Durable auto-reply-enabled account selection is still pending.

## D021: Headless worker Ctrl+C shutdown exits cleanly

Status: completed.

Related task:
- `T060-G.1`: Ctrl+C traceback cleanup.

Changed files:
- `runtime/worker.py`

Decision:
- Ctrl+C / SIGINT must trigger graceful shutdown through `request_shutdown()` and must not skip `channel.stop_all_connections()`.
- The Windows `signal.signal` fallback does not call the previous default interrupt handler after requesting shutdown, preventing a second default `KeyboardInterrupt` traceback.
- `asyncio.CancelledError` during an already requested shutdown is treated as a normal shutdown path.

Exit code rules:
- `SIGINT` / `KeyboardInterrupt` / `keyboard_interrupt`: `130`.
- `run_seconds_elapsed` / `stop_file_detected`: `0`.

Verification:
- fake KeyboardInterrupt test called `channel.stop_all_connections()` and returned `130`.
- outer `run()` KeyboardInterrupt test returned `130` without traceback.
- fake CancelledError test returned `130` without traceback.
- `--all-enabled --dry-run` and `--status` still passed.

## D022: shutdown consumer missing is idempotent when requested by lifecycle cleanup

Status: completed.

Related task:
- `T060-G.2`: consumer missing shutdown log noise cleanup.

Changed files:
- `Message/core/consumer.py`
- `Channel/pinduoduo/core/pdd_lifecycle.py`

Decision:
- `MessageConsumerManager.stop_consumer()` now supports `missing_ok=False` by default.
- Non-shutdown callers keep the original missing-consumer ERROR behavior.
- Lifecycle resource cleanup calls `stop_consumer(..., missing_ok=True)` because repeated shutdown cleanup can legitimately observe an already removed consumer.
- `missing_ok=True` returns `True` and logs that the consumer is already absent instead of emitting ERROR noise.

Verification:
- `python -m py_compile Message\core\consumer.py Channel\pinduoduo\core\pdd_lifecycle.py` passed.
- fake shutdown test confirmed repeated `stop_consumer(..., missing_ok=True)` returns `True` without ERROR.
- default `missing_ok=False` still logs an error for missing consumers.

---

## D023: Headless worker runtime acceptance completed

Status: completed.

Related tasks:
- `T060-B`: headless worker skeleton completed.
- `T060-C`: single-account real start completed.
- `T060-D`: all-enabled multi-account orchestration completed.
- `T060-E`: worker graceful shutdown diagnostics completed.
- `T060-G`: deterministic shutdown control completed.
- `T060-H`: run-seconds / stop-file / Ctrl+C acceptance completed.

Key decisions:
1. Headless worker uses one independent `PDDChannel` instance per account.
2. `PDDChannel` still owns a single `self.ws`; multi-account shared `PDDChannel` instances are forbidden.
3. `--run-seconds`, `--stop-file`, Ctrl+C, SIGINT, and SIGTERM use the same idempotent shutdown request path.
4. Shutdown must call `PDDChannel.stop_all_connections()` before process exit.
5. `--all-enabled` remains candidate-based with `channel_name == "pinduoduo" and status == 1`; it is not yet a durable auto-reply-enabled selection model.

Verification:
- Headless skeleton and dry-run commands passed.
- Single-account real startup path was exercised.
- Multi-account orchestration uses per-account channel/task mappings.
- run-seconds, stop-file, and Ctrl+C graceful shutdown paths were accepted.

## D024: Worker status and healthcheck file contract completed

Status: completed.

Related tasks:
- `T061-A`: `worker_status.json` writer completed.
- `T061-A.1`: final snapshot semantics fixed.
- `T061-B`: `--status` reads status file.
- `T061-C`: `--healthcheck` completed.
- `T061-D`: smoke / healthcheck scripts and runbook completed.

Key decisions:
1. Worker status file path is `DATA_DIR/runtime/worker_status.json` unless `WORKER_STATUS_PATH` overrides it.
2. Status writes use atomic temp-file replace.
3. Final snapshots use `snapshot_phase=final`, `worker_state=stopped`, and `connected_count=0`.
4. `python -m runtime.worker --status` is the human/operator status command.
5. `python -m runtime.worker --healthcheck` is the preferred Docker/systemd healthcheck command.
6. Healthcheck exit code `5` means `stopped`: the worker is not running. This is expected after smoke tests but unhealthy for service liveness.

Healthcheck exit codes:
- `0`: healthy.
- `1`: degraded.
- `2`: missing status file.
- `3`: invalid status JSON.
- `4`: stale running snapshot.
- `5`: stopped final snapshot.

## D025: Headless worker diagnose package completed

Status: completed.

Related tasks:
- `T062`: diagnose package export completed.
- `T062-A`: diagnose artifact Git protection completed.

Changed files:
- `scripts/runtime/diagnose.ps1`
- `scripts/runtime/diagnose.sh`
- `docs/runtime/DIAGNOSE_PACKAGE.md`
- `docs/runtime/HEADLESS_WORKER_RUNBOOK.md`
- `.gitignore`

Key decisions:
1. Diagnose scripts export a redacted package for private deployment troubleshooting.
2. Packages may include worker status, status/healthcheck JSON output, recent log tails, `.env.example`, config/runtime docs, Python/OS metadata, and optional Git status.
3. Packages must not include `.env`, databases, browser caches, full runtime directories, or message history.
4. Redaction is best-effort and masks common credential/session fields before files are written into the package.
5. Runtime artifacts are protected by `.gitignore`: `runtime.stop`, `worker_status.json`, `diagnostics/`, `**/diagnostics/`, `temp/`, `logs/`, `*.log`, and `.browsers/`.

Known limits:
- Redaction must be updated if new log formats contain sensitive values under unrecognized field names.
- Diagnose package export is not a backup mechanism.

Next task:
- `T063`: Linux/systemd service draft and start/stop/status/diagnose scripts.

---

## D026: Linux/systemd deployment skeleton accepted statically

Status: completed.

Related tasks:
- `T063`: Linux/systemd service skeleton completed.
- `T063-A`: stop-file closure fixed.
- `T064`: static acceptance completed.

Changed files:
- `deploy/linux/customer-agent-worker.service.example`
- `deploy/linux/start.sh`
- `deploy/linux/stop.sh`
- `deploy/linux/status.sh`
- `deploy/linux/healthcheck.sh`
- `deploy/linux/diagnose.sh`
- `deploy/linux/README_SYSTEMD.md`

Key decisions:
1. The systemd skeleton starts the headless worker with `python -m runtime.worker --all-enabled --status-interval 5`.
2. `ExecStart` must include `--stop-file /opt/customer-agent-refactor-v3/runtime.stop`.
3. `ExecStartPre` must remove the old stop file before startup.
4. `ExecStop` triggers graceful shutdown by touching the same stop file.
5. `systemd stop` should request graceful shutdown through stop-file, not bypass runtime cleanup.
6. `python -m runtime.worker --healthcheck` is suitable for systemd/Docker probes.
7. Healthcheck exit code `5` means the worker is stopped and not running.
8. `DATA_DIR/runtime/worker_status.json` remains the default status file path unless overridden by `WORKER_STATUS_PATH`.
9. Each account still requires its own `PDDChannel` instance because `PDDChannel` owns a single `self.ws`; shared multi-account channel instances remain forbidden.

Static acceptance:
- Service file contains `WorkingDirectory=/opt/customer-agent-refactor-v3`.
- Service file contains `EnvironmentFile=/opt/customer-agent-refactor-v3/.env`.
- Service file contains `ExecStartPre`, `ExecStart`, `ExecStop`, `--stop-file`, `TimeoutStopSec=30`, `Restart=on-failure`, and `RestartSec=5`.
- `start.sh` removes stale stop-file and passes `--stop-file`.
- `stop.sh` touches the same stop-file and does not kill the worker directly.
- `status.sh` calls `python -m runtime.worker --status`.
- `healthcheck.sh` calls `python -m runtime.worker --healthcheck`.
- `diagnose.sh` delegates to `scripts/runtime/diagnose.sh`.

Known limitations:
- `deploy/linux` has only been statically validated.
- It has not yet been run on a real Linux/systemd host.
- Docker Compose is not completed.
- FastGPT business workflow has not yet been accepted end-to-end in the Linux deployment shape.

Next tasks:
- `T065`: Linux real-machine deployment acceptance checklist.
- `T066`: systemd real-machine verification.
