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

## D005：P0 consumer 幂等化已完成

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

## D006：下一步计划改 MessageConsumer 固定 worker pool

状态：待执行。

目标：

将当前“每条消息创建一个 task”的模型，改成固定 worker pool。

原因：

当前模型即使有 semaphore，也只能限制并发处理数量，不能限制已创建 task 的数量。消息积压时可能产生大量等待 task。

目标模型：

1. consumer 启动时创建固定数量 worker。
2. worker 数量等于 `max_concurrent`。
3. 每个 worker 循环从 queue 取消息。
4. 不再每条消息创建无界 task。
5. stop 时 cancel workers 并 gather with timeout。

## D007：后续需要引入 reconnect generation

状态：待执行。

目标：

防止旧 reconnect task / cleanup task 误清理新连接。

语义：

1. 每次连接启动生成一个 generation。
2. task 记录自己的 generation。
3. cleanup 前检查 generation 是否仍是当前 generation。
4. 过期 task 不能关闭新 websocket、不能停止新 consumer、不能覆盖新状态。

## D008：后续需要 graceful shutdown

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
