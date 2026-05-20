# T010 Windows 路径和硬编码配置扫描

扫描日期：2026-05-19

扫描范围：

- `E:\develop\customer-agent-refactor-v3`：已扫描。
- `E:\develop\customer-agent-coze`：可访问，已一并扫描。

说明：本报告只做 Linux 私有化部署兼容性审计，不包含代码修改方案的实现。扫描时重点排除了 `.git`、`__pycache__`、`.browsers`、运行日志和二进制缓存等非源码目录；但对已在源码目录内出现的启动脚本、配置文件、文档和历史测试脚本进行了记录。

## 1. 总览结论

当前 `customer-agent-refactor-v3` 仍是 Windows / PyQt 本地原型优先的运行形态，核心拼多多 WebSocket runtime 由 `AutoReplyThread(QThread)` 拉起，尚未形成独立 Linux headless worker 入口。

主要 Linux 私有化部署阻塞点：

1. 启动编排强依赖 Windows 路径、PowerShell、Docker Desktop 和本机 Ollama。
2. FastGPT / Ollama / proxy / Redis / Qdrant / API 端口默认值分散在多个文件中。
3. 数据库、日志、缓存、Playwright 浏览器目录没有统一通过 `DATA_DIR` / `LOG_DIR` / `CACHE_DIR` 管理。
4. `customer-agent-coze` 中存在硬编码真实 API Key / Bearer Token 风险，必须脱敏、轮换并改为环境变量。
5. PyQt UI 与核心 WebSocket runtime 仍耦合，Linux 服务端需要新增 headless worker，而不是删除 Windows UI。

总体建议：不要在 T010 阶段改代码。后续应先处理密钥外泄和配置集中化，再增加 Linux headless worker 与 Docker Compose 私有化部署。

## 2. 高风险项

### H001：`customer-agent-coze` 存在硬编码真实密钥

文件和位置：

- `E:\develop\customer-agent-coze\projects\config\agent_llm_config.json:4`
- `E:\develop\customer-agent-coze\ollama_proxy.py:10`

当前写法：

- `agent_llm_config.json` 中写入了真实 `api_key`，值以 `ark-...` 开头。
- `ollama_proxy.py` 中写入了 `DOUBAO_AUTH = "Bearer ark-...<redacted>"`。

为什么影响 Linux 私有化部署：

- 密钥进入仓库、压缩包或部署镜像后不可控。
- 私有化部署通常会复制配置文件到服务器，硬编码密钥容易泄漏。
- 后续多人交付或客户现场部署时无法做到环境隔离。

建议改造方式：

- 立即轮换当前密钥。
- 将 `DOUBAO_AUTH`、`LLM_API_KEY`、`FASTGPT_API_KEY` 等统一改为环境变量。
- 提供 `.env.example` 只保留占位符，不写真实值。
- 对历史提交中的密钥泄漏做单独处置，不和功能改造混在一起。

### H002：Windows 一键启动脚本承担了完整启动编排

文件和位置：

- `start_all_services.ps1:8-16`
- `start_all_services.ps1:88-92`
- `start_all_services.ps1:137-139`
- `start_all_services.ps1:174-229`
- `start_all_services.ps1:264-286`
- `one-click-start.bat:20`
- `start.bat:33`

当前写法：

- 固定 `$ProjectRoot = "E:\develop\customer-agent-refactor-v3"`。
- 固定 `$FastGptRoot = "E:\develop\fastgpt"`。
- 固定 `$ProxyRoot = "E:\develop\customer-agent-coze"`。
- 固定 `$Python = "D:\anaconda\python.exe"`。
- 固定 Docker Desktop 路径 `C:\Program Files\Docker\Docker\Docker Desktop.exe`。
- 通过 PowerShell / bat / `.venv\Scripts\activate.bat` 启动。
- 检查 `localhost:3000`、`127.0.0.1:11434`、`127.0.0.1:11435`。

为什么影响 Linux 私有化部署：

- Linux 服务器没有 PowerShell bat 入口、Docker Desktop、Windows Python 路径或 `%LOCALAPPDATA%`。
- 当前脚本混合启动 FastGPT、Ollama、proxy、PyQt 客户端和后端服务，不利于 systemd / Docker Compose 托管。

建议改造方式：

- 保留 Windows 启动能力，不删除现有脚本。
- 新增独立 Linux 部署脚本，例如 `deploy/linux/start.sh`、`stop.sh`、`status.sh`、`diagnose.sh`。
- Docker Compose 内部访问使用 service name，不使用宿主机 `localhost`。
- Windows 脚本和 Linux 脚本共享同一套 `.env` 配置键。

### H003：核心 WebSocket runtime 仍由 PyQt QThread 持有

文件和位置：

- `app.py:26`
- `app.py:89`
- `ui/auto_reply/manager.py:57`
- `ui/auto_reply/threads.py:5`
- `ui/auto_reply/threads.py:55`
- `ui/auto_reply/threads.py:89`
- `ui/auto_reply/threads.py:105`
- `ui/auto_reply/threads.py:125`

当前写法：

- `app.py` 创建 `QApplication`。
- `AutoReplyManager` 创建 `AutoReplyThread`。
- `AutoReplyThread(QThread)` 内部创建 `asyncio` event loop。
- `AutoReplyThread` 内部创建 `PDDChannel()` 并调用 `start_account()`。

为什么影响 Linux 私有化部署：

- Linux 服务端需要无头运行，不能依赖桌面 UI 进程来持有拼多多 WebSocket。
- systemd / Docker 容器中不适合以 PyQt 主进程作为核心 worker。
- 停止、健康检查、自动重启、日志采集都应由服务端 runtime 承担。

建议改造方式：

- 不删除 PyQt UI，短期保留为 Windows 管理端。
- 新增 `customer-agent-worker` 或等价 headless 入口，复用 `PDDChannel`、consumer、handler。
- 将账号 start/stop/status 逐步移到 API / worker 层。
- PyQt 后续通过 API 管理 worker，而不是直接持有核心长连接。

### H004：Redis 密码和端口存在弱默认与宿主机暴露

文件和位置：

- `core/config.py:77-79`
- `docker-compose.yml:7`
- `docker-compose.yml:9`

当前写法：

- `REDIS_HOST` 默认 `localhost`。
- `REDIS_PORT` 默认 `6379`。
- `REDIS_PASSWORD` 默认 `123456`。
- `docker-compose.yml` 使用 `redis-server --requirepass 123456`。
- Redis 端口发布为 `"6379:6379"`。

为什么影响 Linux 私有化部署：

- 弱密码和宿主机端口暴露在客户服务器上风险较高。
- Docker 内部服务应该通过内部网络访问 Redis，不应默认对外发布。

建议改造方式：

- Redis 密码必须来自 `.env`。
- 私有化 Compose 默认不对公网发布 Redis。
- 健康检查和应用连接统一读取 `REDIS_HOST`、`REDIS_PORT`、`REDIS_PASSWORD`。

### H005：proxy / Ollama / Doubao 地址和端口硬编码

文件和位置：

- `core/config.py:57`
- `core/config_manager.py:166`
- `core/config_manager.py:551`
- `Message/handlers/fastgpt_handler.py:49`
- `E:\develop\customer-agent-coze\ollama_proxy.py:8-10`
- `E:\develop\customer-agent-coze\ollama_proxy.py:102-103`

当前写法：

- `SESSION_COMPRESS_BASE_URL` 默认 `http://host.docker.internal:11435`。
- 本地模型默认 `http://localhost:11434`。
- FastGPT handler 默认 `http://localhost:3000/api`。
- `ollama_proxy.py` 固定 `OLLAMA_URL = "http://127.0.0.1:11434"`。
- `ollama_proxy.py` 默认监听 `0.0.0.0:11435`。

为什么影响 Linux 私有化部署：

- Docker 容器内 `localhost` 指向容器自身，不等于宿主机或其他服务。
- `host.docker.internal` 在 Linux Docker 环境下不是稳定默认能力。
- proxy 暴露到 `0.0.0.0` 时需要明确访问控制和密钥管理。

建议改造方式：

- 使用 `OLLAMA_BASE_URL`、`FASTGPT_BASE_URL`、`PROXY_BASE_URL`、`PROXY_BIND_HOST`、`PROXY_PORT`。
- Docker 内部默认使用 service name，例如 `http://ollama:11434`、`http://fastgpt:3000`。
- 本地 Windows 默认值可以保留在 `.env.example.windows` 或文档中。

## 3. 中风险项

### M001：本地地址和端口配置分散

文件和位置：

- `core/config.py:57`
- `core/config.py:77-79`
- `core/config_manager.py:166`
- `core/config_manager.py:551`
- `Message/handlers/fastgpt_handler.py:49`
- `E:\develop\customer-agent-coze\projects\src\main.py:181-183`
- `E:\develop\customer-agent-coze\projects\src\tools\knowledge_tool.py:36`
- `E:\develop\customer-agent-coze\projects\config\agent_llm_config.json:12`
- `E:\develop\customer-agent-coze\projects\config\agent_llm_config.json:17-18`

当前写法：

- FastGPT、Ollama、proxy、Redis、API server 的 host/port 默认散落在不同模块。
- `customer-agent-coze` API 默认 `0.0.0.0:8000`，LLM config 默认 `http://localhost:8001`。
- knowledge tool 默认 `http://localhost:3000`。

为什么影响 Linux 私有化部署：

- 配置来源不统一会导致部署时改漏。
- 容器内部和宿主机本地调试的地址语义不同。

建议改造方式：

- 建立统一配置表和 `.env.example`。
- 分离 Windows local、Linux compose、production private 三套示例配置。
- 所有服务 URL 统一从配置层注入，不在业务类构造函数中写死生产默认值。

### M002：SQLite、日志、临时目录、导出目录未统一

文件和位置：

- `config.json.template:20`
- `database/db_manager.py:19`
- `core/di_container.py:361`
- `utils/logger_loguru.py:48`
- `utils/runtime_path.py:70-172`
- `Knowledge/csv_exporter.py:32`
- `ui/Knowledge_ui.py:450`

当前写法：

- SQLite 默认 `./temp/channel_shop.db`。
- 默认日志 `logs/app.log`。
- runtime path 使用 `temp`、`temp/logs`、`agent.db`、`vector_db`、`contents.db`。
- CSV 导出默认进入 `./temp`。

为什么影响 Linux 私有化部署：

- 容器内相对路径容易随工作目录变化。
- 数据、日志、缓存、导出文件需要明确挂载 volume。
- 备份和诊断脚本需要稳定目录结构。

建议改造方式：

- 增加 `DATA_DIR`、`LOG_DIR`、`CACHE_DIR`、`EXPORT_DIR`、`DB_PATH`。
- Docker Compose 中明确 volume mount。
- Linux 默认使用 `/opt/customer-agent/data`、`/opt/customer-agent/logs` 或部署目录下 `data/`、`logs/`。

### M003：Playwright 浏览器路径对 Windows 偏置明显

文件和位置：

- `utils/playwright_path.py:63-85`
- `Channel/pinduoduo/pdd_login.py:13-24`
- `app.py:77-86`

当前写法：

- 优先查找项目 `.browsers`。
- Windows fallback 使用 `LOCALAPPDATA` / `ms-playwright`。
- `pdd_login.py` 直接设置 `PLAYWRIGHT_BROWSERS_PATH`。

为什么影响 Linux 私有化部署：

- Linux 容器需要固定浏览器安装路径和依赖包。
- `.browsers` 目录不应作为可提交源码资产。
- 浏览器路径配置分散会导致登录自动化在服务器上不可诊断。

建议改造方式：

- 统一通过 `PLAYWRIGHT_BROWSERS_PATH` 或 `BROWSER_CACHE_DIR` 配置。
- Linux 镜像内预安装 Playwright 浏览器和系统依赖。
- 将 `.browsers/` 明确加入忽略和部署排除清单。

### M004：测试和评估脚本包含旧 Windows 绝对路径

文件和位置：

- `generate_eval_dataset.py:8`
- `run_hell_test_matrix.py:7`
- `run_real_telemetry_e2e.py:7`
- `run_router_benchmark.py:7`
- `simulate_business_trace.py:7`
- `test_e2e_pipeline.py:11`
- `test_sync_worker_recovery.py:12`
- `tests/test_integration.py:7`
- `scripts/v3_four_product_multiturn_eval.py:17`

当前写法：

- 多个脚本文档头部或常量指向 `E:\develop\customer-agent-refactor` 或 `E:\develop\customer-agent-refactor-v3`。
- 部分测试默认连接 `localhost:11434`。

为什么影响 Linux 私有化部署：

- CI / Linux 服务器无法直接运行这些脚本。
- 部分路径指向旧项目名，容易误导维护者。

建议改造方式：

- 如果只是历史脚本，标记为非部署入口。
- 后续用 `Path(__file__).resolve()` 或环境变量替代绝对路径。
- 将依赖外部服务的测试改为显式集成测试，不默认执行。

### M005：账号 cookie / password 存储需要私有化安全策略

文件和位置：

- `database/models.py:38`
- `database/db_manager.py:199`
- `database/db_manager.py:217`
- `database/db_manager.py:237`
- `database/db_manager.py:257`
- `database/db_manager.py:281-297`
- `database/db_manager.py:316-334`
- `Channel/pinduoduo/pdd_login.py:240`
- `Channel/pinduoduo/pdd_login.py:284`

当前写法：

- 账号 cookie、password 等敏感字段由本地 SQLite 保存和读取。

为什么影响 Linux 私有化部署：

- 私有化服务器需要明确数据库文件权限、备份加密和访问控制。
- 容器 volume 中的 cookie 数据属于高敏运行数据。

建议改造方式：

- 短期：限制 DB 文件权限，诊断包默认排除敏感字段。
- 中期：支持敏感字段加密或外部 secret backend。
- 不建议在当前 T010 直接改 schema。

## 4. 低风险项

### L001：Windows 打包脚本和快捷方式逻辑

文件和位置：

- `scripts/build_exe.py`
- `scripts/build_win_exe.py`
- `scripts/agent_customer.spec`

当前写法：

- 包含 PyInstaller、NSIS、桌面快捷方式、Windows exe 相关逻辑。

为什么影响 Linux 私有化部署：

- 这些文件不是 Linux 服务端运行入口，但可能误认为可部署入口。

建议改造方式：

- 保留 Windows 客户端打包能力。
- 在文档中标记为 Windows client only。
- Linux 部署脚本单独放在 `deploy/linux/`。

### L002：历史文档和崩溃日志包含本地路径

文件和位置：

- `E:\develop\customer-agent-coze\app_crash.log`
- `E:\develop\customer-agent-coze\app_crash2.log`
- 多个历史 Markdown 文档中的 localhost / Windows 示例。

当前写法：

- 日志中出现本地绝对路径、`.browsers`、项目目录。

为什么影响 Linux 私有化部署：

- 如果这些日志随部署包交付，会泄漏本地开发环境路径。
- 文档示例可能误导部署人员。

建议改造方式：

- 部署包排除崩溃日志和本地运行日志。
- 文档保留 Windows 示例时，明确标记为 Windows local only。

### L003：开发 compose 暴露 Qdrant / Redis 端口

文件和位置：

- `docker-compose.yml:9`
- `docker-compose.yml:16-17`

当前写法：

- Redis、Qdrant 端口直接发布到宿主机。

为什么影响 Linux 私有化部署：

- 单客户内网部署可以接受，但默认暴露面偏大。

建议改造方式：

- 私有化 Compose 默认只暴露业务 API 和必要 UI。
- Redis/Qdrant/Postgres/Mongo/MinIO 默认使用内部网络。

## 5. 文件路径和行号汇总

| 风险 | 项目 | 文件:行 | 当前写法摘要 | 建议 |
| --- | --- | --- | --- | --- |
| 高 | customer-agent-coze | `projects/config/agent_llm_config.json:4` | 硬编码真实 `api_key` | 轮换密钥，改为环境变量 |
| 高 | customer-agent-coze | `ollama_proxy.py:10` | 硬编码 `Bearer ark-...<redacted>` | 轮换密钥，改为 `DOUBAO_AUTH` env |
| 高 | refactor-v3 | `start_all_services.ps1:8-16` | Windows 绝对路径和 Docker Desktop 路径 | 保留 Windows 脚本，新增 Linux 脚本 |
| 高 | refactor-v3 | `one-click-start.bat:20` | PowerShell 启动依赖 | Linux 另建入口 |
| 高 | refactor-v3 | `start.bat:33` | `.venv\Scripts\activate.bat` | Linux 使用 `.venv/bin/activate` 或容器 |
| 高 | refactor-v3 | `app.py:26,89` | PyQt `QApplication` 主入口 | 新增 headless worker |
| 高 | refactor-v3 | `ui/auto_reply/threads.py:55,89,105,125` | QThread 持有 `PDDChannel` 和 event loop | runtime 从 UI 抽离 |
| 高 | refactor-v3 | `core/config.py:77-79` | Redis 默认 `localhost:6379` / `123456` | env 强制覆盖，私有化默认不暴露 |
| 高 | refactor-v3 | `docker-compose.yml:7,9` | Redis `requirepass 123456` 且发布端口 | 使用 `.env` 和内部网络 |
| 中 | refactor-v3 | `core/config.py:57` | `host.docker.internal:11435` | Linux Compose 使用 service name |
| 中 | refactor-v3 | `core/config_manager.py:166,551` | 本地模型默认 `localhost:11434` | 改为配置注入 |
| 中 | refactor-v3 | `Message/handlers/fastgpt_handler.py:49` | FastGPT 默认 `localhost:3000/api` | 改为 `FASTGPT_BASE_URL` |
| 中 | refactor-v3 | `database/db_manager.py:19` | SQLite 默认 `./temp/channel_shop.db` | 引入 `DB_PATH` / `DATA_DIR` |
| 中 | refactor-v3 | `utils/logger_loguru.py:48` | 默认 `logs/app.log` | 引入 `LOG_DIR` |
| 中 | refactor-v3 | `utils/playwright_path.py:63-85` | `.browsers` / `LOCALAPPDATA` fallback | Linux 浏览器路径配置化 |
| 中 | refactor-v3 | `Channel/pinduoduo/pdd_login.py:13-24` | 直接设置 Playwright browser path | 统一浏览器配置 |
| 中 | customer-agent-coze | `projects/src/tools/knowledge_tool.py:36` | knowledge URL 默认 `localhost:3000` | env + service name |
| 中 | customer-agent-coze | `projects/config/agent_llm_config.json:12` | LLM base URL `localhost:8001` | env + service name |
| 中 | customer-agent-coze | `projects/src/main.py:181-183` | API 默认 `0.0.0.0:8000` | 保留 bind，端口 env 化 |
| 低 | refactor-v3 | `scripts/build_exe.py` | Windows exe / shortcut | 标记 Windows client only |
| 低 | customer-agent-coze | `app_crash.log` | 本地路径崩溃日志 | 部署包排除日志 |

## 6. 当前写法分类

### Windows 绝对路径

- `start_all_services.ps1`：生产式启动编排直接写死 `E:\develop\...`、`D:\anaconda\...`、`C:\Program Files\Docker\...`。
- 多个测试 / 评估脚本头部写死 `cd E:\develop\...`。
- `scripts/v3_four_product_multiturn_eval.py` 写死旧项目 SQLite 路径。

### 本地地址和端口

- FastGPT：`localhost:3000`
- Ollama：`localhost:11434` / `127.0.0.1:11434`
- proxy：`127.0.0.1:11435`
- Redis：`localhost:6379`
- Qdrant：`6333` / `6334`
- customer-agent-coze API：`0.0.0.0:8000`
- coze LLM config：`localhost:8001`

### 本地启动依赖

- PowerShell / bat。
- Docker Desktop。
- Windows Ollama exe。
- Windows virtualenv Scripts 路径。
- PyQt desktop process。

### 数据和缓存目录

- `./temp/channel_shop.db`
- `logs/app.log`
- `temp/logs`
- `.browsers`
- `LOCALAPPDATA/ms-playwright`

### 敏感配置

- `ark-...` API key / Bearer token 硬编码。
- Redis 默认密码 `123456`。
- SQLite 中保存 cookie / password 运行数据。

## 7. 为什么影响 Linux 私有化部署

1. Linux 容器内 `localhost` 指向当前容器，不是 FastGPT、Ollama 或 proxy。
2. Windows 路径在 Linux 中不可解析，导致脚本、测试和启动入口不可复用。
3. Docker Desktop 和 PowerShell 不是服务器部署依赖。
4. PyQt 进程不适合作为 Linux 后台 worker 的生命周期管理者。
5. 未集中配置的数据目录会让备份、恢复、迁移、诊断包导出变得不可控。
6. 硬编码密钥和弱默认密码会直接影响交付安全。
7. 浏览器缓存路径和 Playwright 依赖没有 Linux 镜像化，会影响拼多多登录自动化。

## 8. 建议改造方式

### 配置层

- 增加 `.env.example`，集中声明：
  - `APP_ENV`
  - `DATA_DIR`
  - `LOG_DIR`
  - `CACHE_DIR`
  - `DB_PATH`
  - `REDIS_HOST`
  - `REDIS_PORT`
  - `REDIS_PASSWORD`
  - `FASTGPT_BASE_URL`
  - `OLLAMA_BASE_URL`
  - `PROXY_BASE_URL`
  - `CUSTOMER_AGENT_API_HOST`
  - `CUSTOMER_AGENT_API_PORT`
  - `PLAYWRIGHT_BROWSERS_PATH`
  - `DOUBAO_AUTH`
  - `LLM_API_KEY`

### 启动层

- 保留 `one-click-start.bat` / `start_all_services.ps1`。
- 新增 Linux 部署脚本，不复用 Windows PowerShell。
- Docker Compose 中服务间访问使用 service name。
- Redis、Qdrant、Postgres、Mongo、MinIO 默认内部网络，不直接暴露到公网。

### runtime 层

- 新增 headless worker 入口，专门启动 `PDDChannel`。
- PyQt 只作为本地管理端或调试端。
- worker 暴露 health/status，而不是依赖 UI 线程状态。

### 数据层

- SQLite 短期继续保留，但路径配置化。
- Linux 部署明确 volume 和备份目录。
- cookie/password 等敏感字段后续做加密或最小化导出。

### 安全层

- 立即从仓库中移除真实密钥，并轮换已泄漏密钥。
- `.env`、运行日志、崩溃日志、`.browsers/` 不进入提交和部署包。
- 诊断包默认脱敏。

## 9. 不建议现在改的项

1. 不建议删除 Windows 一键启动脚本。当前仍需要保留 Windows 本地运行能力。
2. 不建议立即删除 PyQt UI。短期仍可作为管理端和本地调试入口。
3. 不建议在 T010 中重构 `PDDChannel` 或 WebSocket 生命周期，T010 只输出扫描报告。
4. 不建议立刻把 SQLite 替换成 PostgreSQL。先把路径、备份和权限规范化。
5. 不建议把所有测试脚本一次性重写。先区分部署入口、开发测试、历史评估脚本。
6. 不建议在同一轮同时处理密钥轮换、Docker Compose、headless worker 和配置系统，风险过高。

## 10. 后续任务拆分建议

### T010-A：密钥和本地日志泄漏处置

- 轮换 `customer-agent-coze` 中硬编码的 `ark-...` 密钥。
- 改 `ollama_proxy.py` 和 `agent_llm_config.json` 为环境变量。
- 确认 `.env`、`.browsers/`、崩溃日志不进入提交。

### T020：增加 `.env.example`

- 覆盖 refactor-v3 和 coze 所需的服务地址、端口、数据目录、日志目录和密钥占位符。

### T021：统一配置加载

- 收敛 `core/config.py`、`core/config_manager.py`、FastGPT handler、coze tool 的默认 URL。
- 保持 Windows local 默认和 Linux compose 默认可区分。

### T022：路径配置化

- 统一 `DATA_DIR`、`LOG_DIR`、`CACHE_DIR`、`DB_PATH`、`EXPORT_DIR`、`PLAYWRIGHT_BROWSERS_PATH`。

### T030：后端 API / proxy 容器化准备

- 为 customer-agent-coze API 和 proxy 明确容器入口、环境变量、健康检查。

### T032：docker-compose.private.yml

- 使用内部网络和 service name。
- Redis/Qdrant 等基础服务默认不对公网暴露。

### T040：Linux 部署脚本

- `deploy/linux/install.sh`
- `deploy/linux/start.sh`
- `deploy/linux/stop.sh`
- `deploy/linux/status.sh`
- `deploy/linux/diagnose.sh`
- `deploy/linux/backup.sh`

### T060：headless WebSocket worker

- 新增不依赖 PyQt 的 worker 入口。
- 复用现有 `PDDChannel`、consumer、handler。
- 提供健康检查和状态查询。

### T061：运行状态和健康检查

- 输出连接状态、consumer 状态、queue size、last_message_at、last_error、generation、worker_count。

## 审计结论

T010 未发现需要立即删除 Windows 能力的理由。正确路线是保留 Windows 本地启动，同时新增 Linux 私有化部署路径。

最优先处理项不是 Dockerfile，而是：

1. 移除并轮换硬编码密钥。
2. 统一配置和目录。
3. 新增 headless worker。
4. 再做 Linux Compose 和部署脚本。
