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

状态：待执行。

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

下一步：

- `T003-C：AutoReplyThread.stop graceful shutdown`。

## T004：诊断日志增强

状态：待执行。

目标：

补齐诊断字段。

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

下一步建议执行：`T003-C：AutoReplyThread.stop graceful shutdown`。
