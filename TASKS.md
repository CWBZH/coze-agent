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

状态：待执行。

目标：

防止重复 reconnect task 和旧 task 误伤新连接。

要求：

1. 每个 `connection_key` 有 lifecycle lock。
2. 已有 reconnect task 时，cancel 后必须 await timeout。
3. 引入 generation。
4. cleanup 前检查 generation。
5. stale task 不允许清理新 session。
6. 不修改业务逻辑。

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

下一步建议执行：`T002：reconnect lifecycle lock + generation`。
