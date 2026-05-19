# CODEX_RULES.md

## 基本规则

1. 每次只完成用户明确指定的任务。
2. 修改前必须先阅读相关文件并说明计划。
3. 不允许做未要求的大规模重构。
4. 不允许删除 Windows 本地启动能力。
5. 不允许改变现有业务逻辑，除非任务明确要求。
6. 不允许把密钥、token、cookie 写入代码。
7. 所有新增配置必须进入 `.env.example` 或配置说明。
8. 所有路径必须跨平台，优先使用 `pathlib` 或环境变量。
9. 所有服务端新增接口必须有最小健康检查或测试。
10. 每次改动后必须说明：
    - 改了哪些文件
    - 为什么这样改
    - 如何验证
    - 有哪些风险
    - 如何回滚

## 修改边界规则

如果任务是稳定性修复：

- 不要修改业务回复策略。
- 不要修改 FastGPT prompt。
- 不要修改 MessagePipeline 流程。
- 不要修改 UI。
- 不要修改数据库 schema，除非任务明确要求。
- 不要引入新服务，除非任务明确要求。

如果任务是 Linux 部署：

- 不要删除 Windows 启动脚本。
- 不要硬编码 Linux 路径。
- 不要硬编码 Docker 网络地址。
- 不要把本地开发配置覆盖为生产配置。
- 新增配置必须可通过 `.env` 覆盖。

## WebSocket / asyncio 规则

修改 WebSocket、consumer、queue、task 相关代码时，必须检查：

1. 是否会重复创建 task。
2. 是否会重复创建 consumer。
3. 是否会重复注册 handler。
4. 是否会跨 event loop 使用 `asyncio.Queue`。
5. 是否 cancel 后 await。
6. 是否 close websocket 后 wait_closed。
7. 是否存在 while True 空转。
8. 是否有 timeout。
9. 是否有诊断日志。
10. 是否可以重复 stop/start。

## 验证要求

每次改动至少执行一种验证：

1. `python -m py_compile`
2. 单元测试
3. 最小异步测试
4. smoke test
5. 静态扫描报告

如果无法运行测试，必须说明原因。

## 输出格式

每次完成任务后，必须输出：

```text
任务：
修改文件：
核心修改：
验证结果：
风险：
回滚方式：
下一步建议：
```
