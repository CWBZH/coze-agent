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

状态：待执行。

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

## D008：当前下一步任务是 T003

状态：已确认。

说明：

`T002：reconnect lifecycle lock + generation` 完成后，下一步稳定性任务是 `T003：graceful shutdown`。

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

下一步执行 `T003-B：LifecycleMixin.stop_account / stop_all_connections 统一 await 清理`。
