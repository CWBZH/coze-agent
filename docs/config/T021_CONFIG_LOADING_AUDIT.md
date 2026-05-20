# T021-A 统一配置加载前置审计

审计日期：2026-05-19

审计范围：

- `E:\develop\customer-agent-refactor-v3`
- `E:\develop\customer-agent-coze`，当前可访问，已扫描

本轮只读审计，不修改代码、不修改 `.env`、不新增 Dockerfile、不删除 Windows 启动能力。

## 1. 当前配置来源清单

### 1.1 环境变量

`customer-agent-refactor-v3` 当前有两套环境变量读取方式：

- `core/config.py` 在导入期调用 `load_dotenv(<repo>/.env, override=False)`，然后以模块常量形式读取 TTL、PushPlus、Redis、会话压缩等配置。
- `core/config_manager.py` 在实例初始化时确保 `.env` 存在，调用 `load_dotenv(..., override=True)`，并提供 `get_env()` / `set_env()` 给 UI 配置页读写。

`customer-agent-coze` 当前使用：

- `ollama_proxy.py` 直接 `os.getenv()` 读取 `OLLAMA_URL`、`DOUBAO_URL`、`DOUBAO_AUTH`、`LLM_API_KEY`。
- `projects/src/agents/agent.py` 读取 `AGENT_CONFIG_PATH`、`LLM_API_KEY`、`LLM_BASE_URL`。
- `projects/src/tools/llm_tool.py` 读取 `LLM_API_KEY`、`LLM_BASE_URL`，再回退到 JSON。
- `projects/src/tools/knowledge_tool.py` 读取 `KNOWLEDGE_BASE_URL`、`KNOWLEDGE_BASE_API_KEY`、`KNOWLEDGE_BASE_DATASET_ID`。
- `projects/src/storage/memory/memory_saver.py` 读取 `DATABASE_URL`。
- `projects/src/storage/database/db.py` 读取 `PGDATABASE_URL`。

### 1.2 `config.py`

文件：

- `core/config.py`

职责：

- 当前是 runtime 常量模块。
- 在导入期加载 `.env`。
- 将环境变量转为模块级常量。

风险：

- 导入期读取后值固定，后续 UI 修改 `.env` 可能不会自动更新已导入模块常量。
- 默认值里仍包含 Linux 不友好的地址，例如 `host.docker.internal`、`localhost`、Redis 弱默认密码。

### 1.3 `config.json`

文件：

- `config.py`
- `config.json.template`
- `start.bat`
- 历史脚本和文档中仍引用 `config.json`

当前状态：

- `config.py` 是旧的 JSON 配置管理器，支持 `config.json` 自动创建和点号访问。
- `config.json.template` 仍包含 `db_path = "./temp/channel_shop.db"` 和 LLM 配置占位符。
- `start.bat` 仍要求 `config.json` 存在。

风险：

- `.env` 和 `config.json` 双轨并存，容易出现配置来源不一致。
- 部署侧不知道哪个配置是最终生效源。

### 1.4 `ConfigManager`

文件：

- `core/config_manager.py`

职责：

- UI 与底层配置的解耦层。
- 负责读写 `.env`。
- 负责将提示词、一级拦截规则、路由关键词等写入 SQLite `AppConfig`。

当前特征：

- `get_llm_config()` 读取 `LLM_API_BASE`、`LLM_API_KEY`、`LLM_MODEL_NAME`。
- `get_local_model_config()` 读取 `LOCAL_MODEL_*`，默认 `http://localhost:11434`。
- `get_ttl_config()` 读取部分 TTL，但不是 `core/config.py` 中所有 TTL。
- `get_prompt_instructions()`、`get_agent_reply_rules()`、`get_route_keywords()` 从 DB 读取并回退到代码默认值。

风险：

- UI 写入 `.env` 使用 `override=True` 加载，和 `core/config.py` 的 `override=False` 语义不一致。
- 有些默认值在 `ConfigManager`，有些在 `core/config.py`，有些在业务类构造函数。

### 1.5 数据库配置

文件：

- `database/db_manager.py`
- `core/config_manager.py`
- `Message/handlers/ai_handler.py`
- `ui/Knowledge_ui.py`
- `Session/session_manager.py`

当前用途：

- `database/db_manager.py` 默认 SQLite 路径 `./temp/channel_shop.db`。
- `core/di_container.py` 默认注册 `DatabaseManager(db_path="./temp/channel_shop.db")`，可被 `config_instance.get("db_path")` 覆盖。
- `AppConfig` 表保存 `fastgpt:api_key`、提示词、固定话术、路由关键词、fallback 状态、CSV 导出目录等。
- `Message/handlers/ai_handler.py` 会从 DB 读取 `fastgpt:api_key`。

风险：

- 密钥和业务配置同时存在 DB 中，需要明确哪些允许 DB 管理，哪些只允许环境变量/secret 管理。
- SQLite 路径仍未统一到 `DB_PATH`。

### 1.6 硬编码默认值

硬编码默认值分布在：

- `core/config.py`
- `core/config_manager.py`
- `Message/handlers/fastgpt_handler.py`
- `database/db_manager.py`
- `utils/runtime_path.py`
- `utils/logger_loguru.py`
- `utils/logger_config.py`
- `utils/playwright_path.py`
- `Channel/pinduoduo/pdd_login.py`
- `customer-agent-coze/ollama_proxy.py`
- `customer-agent-coze/projects/src/tools/knowledge_tool.py`
- `customer-agent-coze/projects/config/agent_llm_config.json`

### 1.7 UI 输入

文件：

- `core/config_manager.py`
- `ui/setting_ui.py`
- 其他 UI 页面通过 manager 或 DB 间接读写配置

当前形态：

- UI 侧主要通过 `ConfigManager` 写 `.env` 或 SQLite。
- 这部分属于 Windows 本地管理能力，应保留，不应在 T021 中直接删除。

### 1.8 脚本参数

文件：

- `start_all_services.ps1`
- `start.bat`
- `one-click-start.bat`
- `customer-agent-coze/projects/scripts/start_local.bat`
- `customer-agent-coze/projects/src/main.py`

当前形态：

- `start_all_services.ps1` 写死 Windows 路径和本机端口。
- `customer-agent-coze/projects/src/main.py` 使用 CLI 参数 `--host`、`--port`、`--config`。
- `start_local.bat` 传入 `--host 0.0.0.0 --port 8000`。

## 2. 当前已从环境变量读取的变量

| 变量名 | 文件位置 | 默认值 | 是否适合 Linux |
| --- | --- | --- | --- |
| `HUMAN_LOCK_TTL` | `core/config.py:25` | `240` | 是 |
| `INFERENCE_LOCK_TTL` | `core/config.py:28` | `10` | 是 |
| `INTENT_CACHE_TTL` | `core/config.py:31` | `600` | 是 |
| `ALERT_COOLDOWN_TTL` | `core/config.py:34` | `60` | 是 |
| `AI_AWAKENING_TTL` | `core/config.py:37` | `30` | 是 |
| `PENDING_HUMAN_TTL` | `core/config.py:40` | `300` | 是 |
| `FALLBACK_SECOND_REMINDER_BEFORE_EXPIRY` | `core/config.py:43` | `60` | 是 |
| `AUTO_REPLY_RECONNECT_SUSPEND_TTL` | `core/config.py:46` | `900` | 是 |
| `PUSHPLUS_ENABLED` | `core/config.py:49` | `false` | 是 |
| `PUSHPLUS_TOKEN` | `core/config.py:50` | 空 | 是，敏感 |
| `PUSHPLUS_CHANNEL` | `core/config.py:51` | `clawbot` | 是 |
| `PUSHPLUS_TEMPLATE` | `core/config.py:52` | `txt` | 是 |
| `PUSHPLUS_TIMEOUT` | `core/config.py:53` | `8` | 是 |
| `SESSION_COMPRESS_MODEL` | `core/config.py:56` | `doubao-seed-2-0-mini-260215` | 是 |
| `SESSION_COMPRESS_BASE_URL` | `core/config.py:57` | `http://host.docker.internal:11435` | 否，Linux Compose 应改为 service name |
| `SESSION_COMPRESS_API_KEY` | `core/config.py:58` | 空 | 是，敏感 |
| `SESSION_COMPRESS_TIMEOUT` | `core/config.py:59` | `20` | 是 |
| `SESSION_COMPRESS_MAX_TOKENS` | `core/config.py:60` | `80` | 是 |
| `SESSION_COMPRESS_TEMPERATURE` | `core/config.py:61` | `0.3` | 是 |
| `SHORT_SENTENCE_THRESHOLD` | `core/config.py:70` | `5` | 是 |
| `REDIS_HOST` | `core/config.py:77` | `localhost` | Windows 可用，Linux Compose 应为 `redis` |
| `REDIS_PORT` | `core/config.py:78` | `6379` | 是 |
| `REDIS_PASSWORD` | `core/config.py:79` | `123456` | 否，弱默认 |
| `REDIS_DB` | `core/config.py:80` | `0` | 是 |
| `FASTGPT_API_KEY` | `app.py:58` | 空 | 是，敏感 |
| `HEADLESS_MODE` | `core/di_container.py:374` | 空/`0` | 是 |
| `LLM_API_BASE` | `core/config_manager.py:132` | `https://ark.cn-beijing.volces.com/api/v3` | 是 |
| `LLM_API_KEY` | `core/config_manager.py:133` | 空 | 是，敏感 |
| `LLM_MODEL_NAME` | `core/config_manager.py:134` | `doubao-seed-1-6-flash-250828` | 是，但默认模型和 `.env.example` 不一致 |
| `LOCAL_MODEL_ENABLED` | `core/config_manager.py:165` | `true` | 是 |
| `LOCAL_MODEL_BASE_URL` | `core/config_manager.py:166` | `http://localhost:11434` | Windows 可用，Linux Compose 应为 `http://ollama:11434` |
| `LOCAL_MODEL_NAME` | `core/config_manager.py:167` | `customer-service` | 是 |
| `LOCAL_MODEL_MAX_TOKENS` | `core/config_manager.py:168` | `50` | 是 |
| `LOCAL_MODEL_TEMPERATURE` | `core/config_manager.py:169` | `0.3` | 是 |
| `LOCAL_MODEL_TIMEOUT` | `core/config_manager.py:170` | `60` | 是 |
| `BUSINESS_HOURS_START` | `core/config_manager.py:264` | `08:00` | 是 |
| `BUSINESS_HOURS_END` | `core/config_manager.py:265` | `23:00` | 是 |
| `LOG_LEVEL` | `utils/logger_loguru.py:56` | `info` | 是 |
| `ENVIRONMENT` | `utils/logger_config.py:22` | 推断为 `production` | 是，但与 `APP_ENV` 未统一 |
| `DEBUG` | `utils/logger_config.py:27` | 空 | 是 |
| `TESTING` | `utils/logger_config.py:29` | 空 | 是 |
| `BUSINESS_LOGGING` | `utils/logger_config.py:50` | `true` | 是 |
| `UI_LOGGING` | `utils/logger_config.py:54` | `true` | 是 |
| `LOG_RETENTION_DAYS` | `utils/logger_config.py:58` | `7` | 是 |
| `LOG_ROTATION_SIZE` | `utils/logger_config.py:62` | `10 MB` | 是 |
| `LOCALAPPDATA` | `utils/playwright_path.py:65`、`pdd_login.py:20` | 系统变量 | 否，Windows only fallback |
| `OLLAMA_URL` | `customer-agent-coze/ollama_proxy.py:9` | `http://127.0.0.1:11434` | Windows 可用，Linux Compose 应为 `http://ollama:11434` |
| `DOUBAO_URL` | `customer-agent-coze/ollama_proxy.py:10` | Ark URL | 是 |
| `DOUBAO_AUTH` | `customer-agent-coze/ollama_proxy.py:11` | 空 | 是，敏感 |
| `AGENT_CONFIG_PATH` | `customer-agent-coze/projects/src/agents/agent.py:43` | config JSON 默认路径 | 是 |
| `LLM_BASE_URL` | `customer-agent-coze/projects/src/agents/agent.py:62`、`llm_tool.py:41` | JSON 回退 | 是 |
| `KNOWLEDGE_BASE_URL` | `customer-agent-coze/projects/src/tools/knowledge_tool.py:36` | `http://localhost:3000` | Windows 可用，Linux Compose 应为 `http://fastgpt:3000` |
| `KNOWLEDGE_BASE_API_KEY` | `customer-agent-coze/projects/src/tools/knowledge_tool.py:40` | 空 | 是，敏感 |
| `KNOWLEDGE_BASE_DATASET_ID` | `customer-agent-coze/projects/src/tools/knowledge_tool.py:44` | 空 | 是 |
| `DATABASE_URL` | `customer-agent-coze/projects/src/storage/memory/memory_saver.py:35` | 空 | 是，敏感 if credentials |
| `PGDATABASE_URL` | `customer-agent-coze/projects/src/storage/database/db.py:19` | 空 | 是，敏感 if credentials |
| `WORKSPACE_PATH` | `customer-agent-coze/projects/src/tools/product_tool.py:74` | repo-relative fallback | 是 |
| `COZE_WORKSPACE_PATH` | `customer-agent-coze/projects/scripts/load_env.py:12`、`csv_product_tool.py:78` | `/workspace/projects` | 是 |

## 3. 当前仍硬编码的配置

### 3.1 Localhost / 127.0.0.1 / host.docker.internal

| 文件位置 | 当前写法 | 影响 |
| --- | --- | --- |
| `core/config.py:57` | `SESSION_COMPRESS_BASE_URL` 默认 `http://host.docker.internal:11435` | Linux Docker 不稳定，应由 env 指向 proxy service |
| `core/config.py:77` | `REDIS_HOST` 默认 `localhost` | 容器内应为 `redis` |
| `core/config_manager.py:166` | `LOCAL_MODEL_BASE_URL` 默认 `http://localhost:11434` | 容器内应为 `http://ollama:11434` |
| `core/config_manager.py:551` | 更新本地模型配置默认 `http://localhost:11434` | 同上 |
| `Message/handlers/fastgpt_handler.py:49` | `fastgpt_url="http://localhost:3000/api"` | 容器内应为 `http://fastgpt:3000/api` |
| `customer-agent-coze/ollama_proxy.py:9` | `OLLAMA_URL` 默认 `http://127.0.0.1:11434` | 容器内应为 `http://ollama:11434` |
| `customer-agent-coze/projects/src/tools/knowledge_tool.py:36` | `KNOWLEDGE_BASE_URL` 默认 `http://localhost:3000` | 容器内应为 `http://fastgpt:3000` |
| `customer-agent-coze/projects/config/agent_llm_config.json:12` | `base_url="http://localhost:8001"` | JSON 配置默认仍本地化 |
| `start_all_services.ps1` | 多处 `localhost:3000`、`127.0.0.1:11434`、`127.0.0.1:11435` | Windows 脚本可保留，但 Linux 不复用 |

### 3.2 端口

| 文件位置 | 当前写法 | 影响 |
| --- | --- | --- |
| `docker-compose.yml:9` | `6379:6379` | Redis 暴露宿主机，私有化 compose 应默认内网 |
| `docker-compose.yml:16-17` | `6333:6333`、`6334:6334` | Qdrant 暴露宿主机，需按部署策略决定 |
| `customer-agent-coze/ollama_proxy.py:107` | 默认 CLI port `11435` | 可配置但未读取 `PROXY_PORT` |
| `customer-agent-coze/projects/src/main.py:183` | 默认 port `8000` | CLI 参数可覆盖，尚未读取 `CUSTOMER_AGENT_API_PORT` |
| `customer-agent-coze/projects/scripts/start_local.bat:45` | `--port 8000` | Windows local 脚本固定值 |

### 3.3 Redis 密码

| 文件位置 | 当前写法 | 影响 |
| --- | --- | --- |
| `core/config.py:79` | `REDIS_PASSWORD` 默认 `123456` | 弱默认，不适合 Linux 私有化 |
| `docker-compose.yml:7` | `redis-server --requirepass 123456` | 弱默认进入 compose |

### 3.4 DB 路径

| 文件位置 | 当前写法 | 影响 |
| --- | --- | --- |
| `database/db_manager.py:19` | `./temp/channel_shop.db` | 未读取 `DB_PATH` |
| `core/di_container.py:361` | `db_path = "./temp/channel_shop.db"` | 只可被旧 `config.json` 覆盖 |
| `config.json.template:20` | `"db_path": "./temp/channel_shop.db"` | 仍使用 JSON 模板 |
| `utils/runtime_path.py:134` | 默认 `agent.db` | 与主 DB 路径不统一 |

### 3.5 日志路径

| 文件位置 | 当前写法 | 影响 |
| --- | --- | --- |
| `utils/logger_loguru.py:48` | `DEFAULT_LOG_FILE = "logs/app.log"` | 未读取 `LOG_DIR` |
| `utils/logger_config.py:103` | `logs/app.log` | 未读取 `LOG_DIR` |
| `utils/logger_config.py:77,86` | `logs/dev.log`、`logs/test.log` | 未读取 `LOG_DIR` |

### 3.6 cache / temp / export 路径

| 文件位置 | 当前写法 | 影响 |
| --- | --- | --- |
| `utils/runtime_path.py:70-172` | `temp`、`temp/logs`、`vector_db`、`contents.db` | 未读取 `DATA_DIR` / `CACHE_DIR` |
| `docker-compose.yml:19` | `./temp/qdrant_data:/qdrant/storage` | dev 路径进入 compose |
| `ui/Knowledge_ui.py:445-454` | CSV export dir 存 DB，否则 `./temp` | UI 管理值，不应直接覆盖 |

### 3.7 Playwright 路径

| 文件位置 | 当前写法 | 影响 |
| --- | --- | --- |
| `utils/playwright_path.py:63` | `get_app_dir() / ".browsers"` | Windows local 可用，容器应可配置 |
| `utils/playwright_path.py:65-67` | `LOCALAPPDATA/ms-playwright` | Windows only |
| `utils/playwright_path.py:45-54` | 检查 `chrome-win/chrome.exe`、`headless_shell.exe` | Linux Chromium 路径不兼容 |
| `Channel/pinduoduo/pdd_login.py:13-24` | 导入期直接设置 `PLAYWRIGHT_BROWSERS_PATH` | 与统一配置冲突，且重复设置 |
| `Channel/pinduoduo/pdd_login.py:58` | `user_data/<name>` | 未读取 `DATA_DIR` / `BROWSER_CACHE_DIR` |

## 4. 配置优先级建议

建议统一优先级：

1. 环境变量：容器、systemd、CI 和运维注入的最高优先级。
2. `.env`：Windows local 和单机部署本地覆盖。
3. `config.json` / DB：保留给历史兼容、UI 管理和业务配置。
4. 代码默认值：只能是安全、非敏感、跨平台的最后兜底。

关键约束：

- 密钥类配置优先级应为：环境变量 / `.env` > DB 中已有值 > 空。不要再把真实 key 写入 JSON 或代码。
- 业务规则类配置继续由 DB / UI 管理，例如提示词、一级拦截、路由关键词。
- Windows local 默认值可以保留，但必须集中在一个配置模块里，而不是散落在业务类构造函数中。
- Linux compose 默认值建议统一使用 service name，例如 `redis`、`fastgpt`、`ollama`、`ollama-proxy`。

## 5. 建议新增或复用的配置模块

### 5.1 是否已有 config loader

已有但分散：

- `core/config.py`：导入期 `.env` -> 模块常量。
- `core/config_manager.py`：UI 读写 `.env` 和 DB。
- `config.py`：旧 `config.json` loader。
- `utils/runtime_path.py`：路径工具，但不读环境变量。

结论：

- 不建议继续扩展旧 `config.py` 作为新入口。
- `core/config_manager.py` 更偏 UI 配置管理，不适合作为所有 runtime 模块的依赖。
- 建议新增轻量 `core/settings.py`，只负责集中读取环境变量和安全默认值，并提供 typed helper。

### 5.2 是否需要新增 `core/settings.py`

建议需要，职责如下：

- 在一个位置加载 `.env`，避免多个模块分别 `load_dotenv`。
- 提供 `get_str()`、`get_int()`、`get_bool()`、`get_path()`。
- 提供 settings dataclass 或简单常量分组：
  - `ServiceSettings`
  - `RedisSettings`
  - `FastGPTSettings`
  - `LLMSettings`
  - `PathSettings`
  - `PlaywrightSettings`
  - `RuntimeSettings`
- 不写业务逻辑，不依赖 PyQt，不依赖 DB。

### 5.3 是否需要支持 pathlib

需要。

路径类配置建议都返回 `Path`：

- `DATA_DIR`
- `LOG_DIR`
- `CACHE_DIR`
- `EXPORT_DIR`
- `DB_PATH`
- `PLAYWRIGHT_BROWSERS_PATH`
- `BROWSER_CACHE_DIR`

理由：

- 当前 Windows 和 Linux 路径混用，`pathlib` 能减少分隔符问题。
- Docker volume 路径、PyInstaller 路径、开发路径都需要统一解析。

### 5.4 是否需要支持 Windows local / Linux compose 两套默认值

建议支持，但不要在业务代码里分支判断。

最小做法：

- `APP_ENV=local` 时默认值偏 Windows 本地：
  - FastGPT `http://localhost:3000/api`
  - Ollama `http://localhost:11434`
  - Proxy `http://127.0.0.1:11435`
  - Redis `localhost`
- `APP_ENV=production` 或 `APP_ENV=linux` 时默认值偏 Compose：
  - FastGPT `http://fastgpt:3000/api`
  - Ollama `http://ollama:11434`
  - Proxy `http://ollama-proxy:11435`
  - Redis `redis`

但更推荐生产环境显式配置，不依赖环境推断默认值。

## 6. 最小改造方案

### T021-B：只统一服务 URL 和密钥

范围建议：

- 新增 `core/settings.py`。
- 将以下值集中读取：
  - `FASTGPT_BASE_URL`
  - `FASTGPT_API_KEY`
  - `SESSION_COMPRESS_BASE_URL`
  - `SESSION_COMPRESS_API_KEY`
  - `LLM_API_BASE`
  - `LLM_API_KEY`
  - `LOCAL_MODEL_BASE_URL`
- 改造调用点时保持业务逻辑不变。

优先改造点：

- `app.py` 中 FastGPT handler 创建。
- `Message/handlers/fastgpt_handler.py` 默认 URL。
- `core/config.py` 中 session compression URL。
- `core/config_manager.py` 中 local model URL 默认值。

### T021-C：统一目录路径 `DATA_DIR` / `LOG_DIR` / `CACHE_DIR` / `DB_PATH`

范围建议：

- `database/db_manager.py`
- `core/di_container.py`
- `utils/runtime_path.py`
- `utils/logger_loguru.py`
- `utils/logger_config.py`

策略：

- `DB_PATH` 优先，其次 `DATA_DIR/channel_shop.db`。
- `LOG_DIR` 优先，其次 `logs/`。
- `CACHE_DIR` / `DATA_DIR` 统一替代散落的 `temp`。

注意：

- 不要直接迁移已有 DB 文件。
- Windows 本地用户已有 `./temp/channel_shop.db`，默认仍应兼容。

### T021-D：统一 Redis 配置

范围建议：

- `core/config.py`
- `docker-compose.yml` 后续单独任务处理，不在 T021-D 强改。

策略：

- 移除弱默认 `123456`，或至少在生产环境要求显式配置。
- 保持 Windows local 如果没有 Redis，也不能让应用直接崩溃，现有 Fail-Safe 行为要保留。

### T021-E：统一 Playwright 路径

范围建议：

- `utils/playwright_path.py`
- `Channel/pinduoduo/pdd_login.py`
- `app.py` 仅保留调用入口。

策略：

- 优先读取 `PLAYWRIGHT_BROWSERS_PATH`。
- 再读取 `BROWSER_CACHE_DIR`。
- Windows fallback 保留 `LOCALAPPDATA/ms-playwright`。
- Linux 不应检查 `chrome-win/chrome.exe` 作为唯一有效条件，需要增加 Linux Chromium 路径兼容。

### T021-F：统一 FastGPT / Ollama / Proxy 配置

范围建议：

- `customer-agent-coze/ollama_proxy.py`
- `customer-agent-coze/projects/src/tools/knowledge_tool.py`
- `customer-agent-coze/projects/src/tools/llm_tool.py`
- `customer-agent-coze/projects/src/agents/agent.py`
- `customer-agent-coze/projects/config/agent_llm_config.json`

策略：

- `ollama_proxy.py` 应读取 `PROXY_BIND_HOST` / `PROXY_PORT`，并保留 CLI 参数覆盖。
- `knowledge_tool.py` 默认值从 `localhost` 改为可配置常量或无默认。
- `agent_llm_config.json` 只保留非敏感模型参数，密钥始终来自环境变量。

## 7. 风险和边界

### 7.1 由 UI / DB 管理，不应直接改的配置

以下配置目前具有业务含义或 UI 管理入口，不建议在 T021 里直接迁移：

- 店铺提示词：`shop:{shop_id}:prompt_instructions`
- 一级拦截和固定话术：`shop:{shop_id}:agent_reply_rules`
- 路由关键词：`shop:{shop_id}:route_keywords`
- CSV 导出目录：`product_knowledge:csv_export_dir`
- 会话 fallback 状态：`Session/session_manager.py` 中的 DB key
- `fastgpt:api_key` 作为历史兼容值可以读取，但不建议继续由代码写入默认密钥

### 7.2 必须保留 Windows 兼容的默认值

短期应保留：

- Windows `.browsers` 或 `LOCALAPPDATA/ms-playwright` fallback。
- `localhost:3000` FastGPT local 默认。
- `localhost:11434` Ollama local 默认。
- `127.0.0.1:11435` proxy local 默认。
- `./temp/channel_shop.db` 作为 Windows 旧数据兼容默认。
- Windows bat / PowerShell 启动脚本。

### 7.3 Linux delivery 预留，不应立即强制读取的变量

以下变量可以先在 `.env.example` 和文档中保留，T021 不必一次性接入：

- `WORKER_CONCURRENCY`
- `MESSAGE_QUEUE_MAX_SIZE`
- `RECONNECT_MAX_ATTEMPTS`
- `RECONNECT_INITIAL_DELAY`
- `RECONNECT_MAX_DELAY`
- `HEARTBEAT_INTERVAL`
- `CUSTOMER_AGENT_API_HOST`
- `CUSTOMER_AGENT_API_PORT`
- `POSTGRES_*`
- `MONGO_URL`
- `MINIO_*`
- `PUSHPLUS_TOPIC`

原因：

- 有些需要代码结构配合，例如 headless worker 和 API service。
- 有些属于 Docker Compose 阶段。
- 有些会改变运行时行为，不适合和配置加载重构混做。

### 7.4 其他风险

1. `core/config.py` 导入期常量会让运行期热更新不生效。
2. `ConfigManager` 会自动创建 `.env`，Linux 容器只读文件系统时可能失败。
3. `config.py` 旧 JSON loader 和 `.env` loader 并存，容易让维护者误判配置来源。
4. `app.py` 在 PyQt 入口中初始化 FastGPT handler 和 DB 配置，未来 headless worker 需要拆出独立 runtime 入口。
5. `customer-agent-coze` 不是当前 Git 仓库，配置变更需要单独纳入版本管理或交付包流程。

## 8. 建议执行顺序

推荐按以下顺序做最小改造：

1. `T021-B`：统一服务 URL 和密钥，只解决最容易改漏的网络地址和 secret。
2. `T021-C`：统一目录路径，解决 Linux volume、备份、诊断包基础。
3. `T021-D`：统一 Redis 配置，移除弱默认密码和 Docker 暴露风险。
4. `T021-E`：统一 Playwright 路径，为 Linux 登录自动化做准备。
5. `T021-F`：统一 coze / FastGPT / Ollama / Proxy 配置，为后续 Docker Compose 做准备。

## 9. 结论

当前项目已经部分使用 `.env`，但配置加载仍处于多中心状态：

- runtime 常量在 `core/config.py`
- UI 配置在 `core/config_manager.py`
- 旧 JSON 配置在 `config.py` / `config.json.template`
- 路径默认值在 `utils/runtime_path.py` / logger / DB manager
- 服务 URL 默认值散落在 handler、proxy、tool、脚本中
- 业务配置和部分 secret 存在 SQLite `AppConfig`

T021 不应一次性重构所有配置。最小可控路线是先新增或复用一个轻量 `core/settings.py`，从服务 URL 和密钥开始收敛，再逐步迁移目录、Redis、Playwright 和 coze 侧配置。
