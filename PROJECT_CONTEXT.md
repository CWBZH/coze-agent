# PROJECT_CONTEXT.md

## 项目目标

这是一个面向拼多多商家的 AI 客服助手。

核心能力：

1. 连接拼多多商家后台 WebSocket。
2. 接收买家消息。
3. 转换为统一 Context。
4. 进入消息队列。
5. 调用 AI 回复流程。
6. 支持人工接管。
7. 支持转人工通知。
8. 支持消息发送回拼多多。

## 当前阶段

当前项目正在从 Windows 本地可运行原型，升级为单客户 Linux 私有化部署版本。

当前最重要目标：

1. 修复断线重连后的稳定性问题。
2. 规范 WebSocket 生命周期。
3. 规范 MessageConsumer 并发模型。
4. 逐步抽离 PyQt 对核心运行时的控制。
5. 最终形成 Linux 服务器可部署、可诊断、可维护的交付版本。

## 当前两个项目

### 1. `customer-agent-coze`

定位：

启动编排、后端 API、proxy、FastGPT/Ollama 编排相关项目。

可能包含：

- FastAPI 服务
- proxy
- FastGPT/Ollama 启动脚本
- Windows 一键启动脚本
- 后续 Linux 部署脚本

### 2. `customer-agent-refactor-v3`

定位：

当前核心业务运行项目。

包含：

- PyQt 桌面 UI
- 拼多多 WebSocket 监听
- 消息队列
- MessageConsumer
- AI 回复
- 人工接管
- 转人工通知
- 数据库访问

## 当前运行模型

当前核心业务仍主要运行在 PyQt 进程中。

运行链路大致为：

1. `app.py` 启动 PyQt。
2. `AutoReplyManager` 管理账号启动。
3. 每个账号启动一个 `AutoReplyThread`。
4. 每个 `AutoReplyThread` 创建一个独立 `asyncio` event loop。
5. 每个线程创建一个 `PDDChannel`。
6. `PDDChannel` 建立拼多多 WebSocket。
7. 收到消息后转换为 `Context`。
8. 消息进入 `queue_manager`。
9. `MessageConsumer` 消费消息。
10. `AIReplyHandler` 调用 `MessagePipeline`。
11. `MessagePipeline` 调用 FastGPT。
12. `SendMessage` 发送回复。

## 已确认业务假设

1. 当前一个店铺就是一个账号。
2. 暂时不修改 `queue_name = pdd_{shop_id}`。
3. 当前优先修稳定性，不先改业务回复策略。
4. Windows 本地启动能力暂时保留。
5. Linux 私有化部署是目标交付形态。
6. PyQt 后续可以作为管理端，但不应该长期持有核心 WebSocket 运行时。

## 短期目标

短期优先：

1. WebSocket 断线重连稳定。
2. Consumer 不重复创建。
3. Handler 不重复注册。
4. 消息处理并发受控。
5. 停止/重启账号不会留下僵尸 task。
6. 具备基础诊断日志。

## 中期目标

中期目标：

1. 抽离 runtime core。
2. 建立 headless WebSocket worker。
3. 建立 Linux 后台运行能力。
4. 增加 health/status API。
5. 引入 Redis 或可靠 lock backend。
6. 支持 Docker Compose 部署。

## 不做

当前阶段不做：

1. 不做完整 SaaS。
2. 不做多租户计费。
3. 不做多平台客服接入。
4. 不做大规模 UI 重构。
5. 不删除 Windows 一键启动能力。
6. 不引入过度复杂的微服务架构。
