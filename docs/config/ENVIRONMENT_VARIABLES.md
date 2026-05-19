# Environment Variables

本文档记录 `customer-agent-refactor-v3` 与 `customer-agent-coze` 当前和 Linux 私有化交付预留的环境变量。

约定：

- “当前是否已被代码使用”表示在当前代码中已通过 `os.getenv()`、启动脚本或等价方式读取。
- “reserved for Linux delivery” 表示当前代码未完整接入，但为后续 Linux 私有化部署、Compose、worker 或配置中心预留。
- 所有敏感变量只能写入本地 `.env`、部署环境变量或 secret backend，不允许写入代码、文档示例、JSON 示例或镜像。

## 变量清单

| 变量名 | 用途 | 当前是否已被代码使用 | Windows 示例 | Linux Compose 示例 | 是否敏感 | 默认值建议 |
| --- | --- | --- | --- | --- | --- | --- |
| `APP_ENV` | 运行环境标识 | 否，reserved for Linux delivery | `local` | `production` | 否 | `local` |
| `LOG_LEVEL` | 日志级别 | 否，reserved for Linux delivery | `INFO` | `INFO` | 否 | `INFO` |
| `HEADLESS_MODE` | 无头模式开关 | 是，`core/di_container.py` | `0` | `1` | 否 | `0` |
| `DATA_DIR` | 数据目录 | 否，reserved for Linux delivery | `./temp` | `/app/data` | 否 | `./temp` |
| `LOG_DIR` | 日志目录 | 否，reserved for Linux delivery | `./logs` | `/app/logs` | 否 | `./logs` |
| `CACHE_DIR` | 缓存目录 | 否，reserved for Linux delivery | `./temp/cache` | `/app/cache` | 否 | `./temp/cache` |
| `EXPORT_DIR` | 导出目录 | 否，reserved for Linux delivery | `./temp/export` | `/app/export` | 否 | `./temp/export` |
| `DB_PATH` | SQLite 数据库路径 | 否，reserved for Linux delivery | `./temp/channel_shop.db` | `/app/data/channel_shop.db` | 可能 | `./temp/channel_shop.db` |
| `WORKSPACE_PATH` | coze 商品工具工作区 | 是，`product_tool.py` | `E:/develop/customer-agent-coze/projects` | `/workspace/projects` | 否 | 项目目录 |
| `COZE_WORKSPACE_PATH` | coze 脚本和 CSV 工具工作区 | 是，`load_env.py`、`csv_product_tool.py` | `E:/develop/customer-agent-coze/projects` | `/workspace/projects` | 否 | `/workspace/projects` |
| `REDIS_HOST` | Redis 主机 | 是，`core/config.py` | `localhost` | `redis` | 否 | `localhost` |
| `REDIS_PORT` | Redis 端口 | 是，`core/config.py` | `6379` | `6379` | 否 | `6379` |
| `REDIS_PASSWORD` | Redis 密码 | 是，`core/config.py` | `change-me` | `change-me` | 是 | 不建议提供弱默认 |
| `REDIS_DB` | Redis DB index | 是，`core/config.py` | `0` | `0` | 否 | `0` |
| `FASTGPT_BASE_URL` | FastGPT API 基础地址 | 否，reserved for T021 配置加载 | `http://localhost:3000/api` | `http://fastgpt:3000/api` | 否 | 无 |
| `FASTGPT_API_KEY` | FastGPT API key | 是，`app.py` | `your-fastgpt-api-key` | secret 注入 | 是 | 空 |
| `FASTGPT_APP_ID` | FastGPT 应用 ID | 否，reserved for Linux delivery | `your-fastgpt-app-id` | `your-fastgpt-app-id` | 可能 | 空 |
| `KNOWLEDGE_BASE_URL` | coze 远程知识库 URL | 是，`knowledge_tool.py` | `http://localhost:3000` | `http://fastgpt:3000` | 否 | `http://localhost:3000` |
| `KNOWLEDGE_BASE_API_KEY` | coze 知识库 API key | 是，`knowledge_tool.py` | `your-knowledge-base-api-key` | secret 注入 | 是 | 空 |
| `KNOWLEDGE_BASE_DATASET_ID` | coze 知识库 dataset id | 是，`knowledge_tool.py` | `your-knowledge-base-dataset-id` | `your-knowledge-base-dataset-id` | 否 | 空 |
| `OLLAMA_URL` | coze proxy 当前 Ollama upstream | 是，`ollama_proxy.py` | `http://127.0.0.1:11434` | `http://ollama:11434` | 否 | `http://127.0.0.1:11434` |
| `OLLAMA_BASE_URL` | Ollama 基础地址统一命名 | 否，reserved for T021 配置加载 | `http://localhost:11434` | `http://ollama:11434` | 否 | 无 |
| `PROXY_BASE_URL` | Ollama/Doubao proxy 基础地址 | 否，reserved for Linux delivery | `http://127.0.0.1:11435` | `http://ollama-proxy:11435` | 否 | 无 |
| `PROXY_BIND_HOST` | proxy 监听 host | 否，reserved for Linux delivery | `127.0.0.1` | `0.0.0.0` | 否 | `127.0.0.1` |
| `PROXY_PORT` | proxy 监听端口 | 否，reserved for Linux delivery | `11435` | `11435` | 否 | `11435` |
| `LLM_BASE_URL` | coze LLM OpenAI-compatible URL | 是，`agent.py`、`llm_tool.py` | `https://ark.cn-beijing.volces.com/api/v3` | provider URL | 否 | 无 |
| `LLM_API_BASE` | refactor-v3 LLM API URL | 是，`core/config_manager.py` | `https://ark.cn-beijing.volces.com/api/v3` | provider URL | 否 | 无 |
| `LLM_API_KEY` | LLM API key | 是，两项目均使用 | `your-llm-api-key` | secret 注入 | 是 | 空 |
| `LLM_MODEL_NAME` | LLM 模型名 | 是，`core/config_manager.py` | `doubao-seed-2-0-mini-260215` | `doubao-seed-2-0-mini-260215` | 否 | 项目默认模型 |
| `DOUBAO_AUTH` | Doubao Authorization header | 是，`ollama_proxy.py` | `Bearer your-doubao-token` | secret 注入 | 是 | 可由 `LLM_API_KEY` 生成 |
| `AGENT_CONFIG_PATH` | coze agent config JSON 路径 | 是，`agent.py` | `./config/agent_llm_config.json` | `/app/config/agent_llm_config.json` | 否 | 默认 config 路径 |
| `SESSION_COMPRESS_MODEL` | 会话压缩模型 | 是，`core/config.py` | `doubao-seed-2-0-mini-260215` | `doubao-seed-2-0-mini-260215` | 否 | 当前默认 |
| `SESSION_COMPRESS_BASE_URL` | 会话压缩 API 地址 | 是，`core/config.py` | `http://host.docker.internal:11435` | `http://ollama-proxy:11435` | 否 | 当前默认 |
| `SESSION_COMPRESS_API_KEY` | 会话压缩 API key | 是，`core/config.py` | `your-session-compress-api-key` | secret 注入 | 是 | 空 |
| `SESSION_COMPRESS_TIMEOUT` | 会话压缩超时秒数 | 是，`core/config.py` | `20` | `20` | 否 | `20` |
| `SESSION_COMPRESS_MAX_TOKENS` | 会话压缩最大 tokens | 是，`core/config.py` | `80` | `80` | 否 | `80` |
| `SESSION_COMPRESS_TEMPERATURE` | 会话压缩温度 | 是，`core/config.py` | `0.3` | `0.3` | 否 | `0.3` |
| `PLAYWRIGHT_BROWSERS_PATH` | Playwright 浏览器目录 | 是，`pdd_login.py` 设置/读取环境 | `./.browsers` | `/ms-playwright` | 否 | 项目 `.browsers` |
| `BROWSER_CACHE_DIR` | 浏览器缓存目录 | 否，reserved for Linux delivery | `./.browsers` | `/ms-playwright` | 否 | `./.browsers` |
| `WORKER_CONCURRENCY` | consumer worker 数量 | 否，reserved for T021 配置加载 | `10` | `10` | 否 | `10` |
| `MESSAGE_QUEUE_MAX_SIZE` | 消息队列最大长度 | 否，reserved for Linux delivery | `1000` | `1000` | 否 | `1000` |
| `RECONNECT_MAX_ATTEMPTS` | 重连最大次数 | 否，reserved for T021 配置加载 | `10` | `10` | 否 | `10` |
| `RECONNECT_INITIAL_DELAY` | 初始重连延迟秒数 | 否，reserved for T021 配置加载 | `1` | `1` | 否 | `1` |
| `RECONNECT_MAX_DELAY` | 最大重连延迟秒数 | 否，reserved for T021 配置加载 | `60` | `60` | 否 | `60` |
| `HEARTBEAT_INTERVAL` | WebSocket 心跳间隔秒数 | 否，reserved for T021 配置加载 | `30` | `30` | 否 | `30` |
| `AUTO_REPLY_RECONNECT_SUSPEND_TTL` | UI 自动回复重连暂停 TTL | 是，`core/config.py` | `900` | `900` | 否 | `900` |
| `HUMAN_LOCK_TTL` | 人工锁 TTL | 是，`core/config.py` | `240` | `240` | 否 | `240` |
| `INFERENCE_LOCK_TTL` | 推理锁 TTL | 是，`core/config.py` | `10` | `10` | 否 | `10` |
| `INTENT_CACHE_TTL` | 意图缓存 TTL | 是，`core/config.py` | `600` | `600` | 否 | `600` |
| `ALERT_COOLDOWN_TTL` | 告警冷却 TTL | 是，`core/config.py` | `60` | `60` | 否 | `60` |
| `AI_AWAKENING_TTL` | AI 唤醒 TTL | 是，`core/config.py` | `30` | `30` | 否 | `30` |
| `PENDING_HUMAN_TTL` | 待人工状态 TTL | 是，`core/config.py` | `300` | `300` | 否 | `300` |
| `FALLBACK_SECOND_REMINDER_BEFORE_EXPIRY` | fallback 二次提醒阈值 | 是，`core/config.py` | `60` | `60` | 否 | `60` |
| `SHORT_SENTENCE_THRESHOLD` | 短句阈值 | 是，`core/config.py` | `5` | `5` | 否 | `5` |
| `CUSTOMER_AGENT_API_HOST` | API 服务监听 host | 否，reserved for Linux delivery | `0.0.0.0` | `0.0.0.0` | 否 | `0.0.0.0` |
| `CUSTOMER_AGENT_API_PORT` | API 服务监听端口 | 否，reserved for Linux delivery | `8000` | `8000` | 否 | `8000` |
| `PUSHPLUS_ENABLED` | 是否启用 PushPlus | 是，`core/config.py` | `false` | `true` | 否 | `false` |
| `PUSHPLUS_TOKEN` | PushPlus token | 是，`core/config.py` | `your-pushplus-token` | secret 注入 | 是 | 空 |
| `PUSHPLUS_TOPIC` | PushPlus topic | 否，reserved for topic routing | `your-pushplus-topic` | `your-pushplus-topic` | 可能 | 空 |
| `PUSHPLUS_CHANNEL` | PushPlus channel | 是，`core/config.py` | `clawbot` | `clawbot` | 否 | `clawbot` |
| `PUSHPLUS_TEMPLATE` | PushPlus 模板 | 是，`core/config.py` | `txt` | `txt` | 否 | `txt` |
| `PUSHPLUS_TIMEOUT` | PushPlus 请求超时秒数 | 是，`core/config.py` | `8` | `8` | 否 | `8` |
| `DATABASE_URL` | coze LangGraph memory 数据库 URL | 是，`memory_saver.py` | `postgresql://user:change-me@localhost:5432/agent_db` | `postgresql://customer_agent:change-me@postgres:5432/customer_agent` | 是 | 空 |
| `PGDATABASE_URL` | coze storage database URL | 是，`storage/database/db.py` | `postgresql://user:change-me@localhost:5432/agent_db` | `postgresql://customer_agent:change-me@postgres:5432/customer_agent` | 是 | 空 |
| `POSTGRES_HOST` | PostgreSQL host | 否，reserved for Linux delivery | `localhost` | `postgres` | 否 | `postgres` |
| `POSTGRES_PORT` | PostgreSQL port | 否，reserved for Linux delivery | `5432` | `5432` | 否 | `5432` |
| `POSTGRES_USER` | PostgreSQL user | 否，reserved for Linux delivery | `customer_agent` | `customer_agent` | 可能 | `customer_agent` |
| `POSTGRES_PASSWORD` | PostgreSQL password | 否，reserved for Linux delivery | `change-me` | secret 注入 | 是 | 无弱默认 |
| `POSTGRES_DB` | PostgreSQL database | 否，reserved for Linux delivery | `customer_agent` | `customer_agent` | 否 | `customer_agent` |
| `MONGO_URL` | MongoDB URL for FastGPT compose | 否，reserved for Linux delivery | `mongodb://localhost:27017/fastgpt` | `mongodb://mongo:27017/fastgpt` | 可能 | 无 |
| `MINIO_ENDPOINT` | MinIO endpoint for FastGPT compose | 否，reserved for Linux delivery | `http://localhost:9000` | `http://minio:9000` | 否 | 无 |
| `MINIO_ACCESS_KEY` | MinIO access key | 否，reserved for Linux delivery | `change-me` | secret 注入 | 是 | 无弱默认 |
| `MINIO_SECRET_KEY` | MinIO secret key | 否，reserved for Linux delivery | `change-me` | secret 注入 | 是 | 无弱默认 |

## 当前已使用变量摘要

`customer-agent-refactor-v3` 当前已使用：

- `FASTGPT_API_KEY`
- `HEADLESS_MODE`
- `REDIS_HOST`
- `REDIS_PORT`
- `REDIS_PASSWORD`
- `REDIS_DB`
- `LLM_API_BASE`
- `LLM_API_KEY`
- `LLM_MODEL_NAME`
- `SESSION_COMPRESS_*`
- `PUSHPLUS_*`
- `HUMAN_LOCK_TTL`
- `INFERENCE_LOCK_TTL`
- `INTENT_CACHE_TTL`
- `ALERT_COOLDOWN_TTL`
- `AI_AWAKENING_TTL`
- `PENDING_HUMAN_TTL`
- `FALLBACK_SECOND_REMINDER_BEFORE_EXPIRY`
- `AUTO_REPLY_RECONNECT_SUSPEND_TTL`
- `SHORT_SENTENCE_THRESHOLD`
- `PLAYWRIGHT_BROWSERS_PATH`

`customer-agent-coze` 当前已使用：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `DOUBAO_AUTH`
- `OLLAMA_URL`
- `AGENT_CONFIG_PATH`
- `KNOWLEDGE_BASE_URL`
- `KNOWLEDGE_BASE_API_KEY`
- `KNOWLEDGE_BASE_DATASET_ID`
- `DATABASE_URL`
- `PGDATABASE_URL`
- `WORKSPACE_PATH`
- `COZE_WORKSPACE_PATH`

## Linux 交付预留变量摘要

以下变量主要用于后续 T021 / Docker Compose / headless worker，不代表当前代码已经完整读取：

- `APP_ENV`
- `LOG_LEVEL`
- `DATA_DIR`
- `LOG_DIR`
- `CACHE_DIR`
- `EXPORT_DIR`
- `DB_PATH`
- `FASTGPT_BASE_URL`
- `FASTGPT_APP_ID`
- `OLLAMA_BASE_URL`
- `PROXY_BASE_URL`
- `PROXY_BIND_HOST`
- `PROXY_PORT`
- `BROWSER_CACHE_DIR`
- `WORKER_CONCURRENCY`
- `MESSAGE_QUEUE_MAX_SIZE`
- `RECONNECT_MAX_ATTEMPTS`
- `RECONNECT_INITIAL_DELAY`
- `RECONNECT_MAX_DELAY`
- `HEARTBEAT_INTERVAL`
- `CUSTOMER_AGENT_API_HOST`
- `CUSTOMER_AGENT_API_PORT`
- `PUSHPLUS_TOPIC`
- `POSTGRES_*`
- `MONGO_URL`
- `MINIO_*`

## T021-B service settings update

`customer-agent-refactor-v3` now has a lightweight `core/settings.py` loader for service URL and secret-style settings.

Currently centralized through `core/settings.py`:

- `APP_ENV`
- `FASTGPT_BASE_URL`
- `FASTGPT_API_KEY`
- `SESSION_COMPRESS_BASE_URL`
- `SESSION_COMPRESS_API_KEY`
- `LLM_API_BASE`
- `LLM_API_KEY`
- `LOCAL_MODEL_BASE_URL`

Default behavior:

- `APP_ENV=local`: `FASTGPT_BASE_URL=http://localhost:3000/api`, `LOCAL_MODEL_BASE_URL=http://localhost:11434`, `SESSION_COMPRESS_BASE_URL=http://127.0.0.1:11435`
- `APP_ENV=linux` or `APP_ENV=production`: `FASTGPT_BASE_URL=http://fastgpt:3000/api`, `LOCAL_MODEL_BASE_URL=http://ollama:11434`, `SESSION_COMPRESS_BASE_URL=http://ollama-proxy:11435`

Production deployments should explicitly set service URLs and keys in environment variables or local `.env` files. Do not put real keys in code, docs, JSON examples, or images.
