# T088-C Customer-Agent-Coze / FastGPT Information Trace

Date: 2026-05-20

Scope: read-only investigation across `customer-agent-refactor-v3`, `customer-agent-coze`, and the local FastGPT Docker stack. This report does not modify code, `.env`, database rows, Docker containers, FastGPT workflow, prompts, datasets, or collections.

Terminology update after product clarification:

- `FastGPT Agent API` means the Docker-hosted FastGPT low-code app/workflow endpoint exposed by `fastgpt-app` on port 3000, especially `/api/v1/chat/completions`.
- `customer-agent-coze/projects/src/main.py` on port 8000 is a separate local FastAPI `/ask` service. It should not be called "the FastGPT Agent API".
- The current PDD production chain calls the Docker FastGPT Agent/workflow API, not the coze `/ask` service.

## 1. 调查范围

Read-only sources checked:

| Area | Path / Target | Purpose |
| --- | --- | --- |
| refactor runtime | `E:\develop\customer-agent-refactor-v3\Message\handlers\fastgpt_handler.py` | Confirm FastGPT request endpoint, headers, payload fields |
| refactor pipeline | `E:\develop\customer-agent-refactor-v3\Message\core\pipeline.py` | Confirm `shops.fastgpt_dataset_id`, `chatId`, and missing-dataset behavior |
| refactor settings | `E:\develop\customer-agent-refactor-v3\core\settings.py` | Confirm `FASTGPT_BASE_URL` defaults |
| T088-A / T088-B reports | `docs\architecture\T088A_*`, `T088B_*` | Reuse previous dataset and endpoint findings |
| coze proxy | `E:\develop\customer-agent-coze\ollama_proxy.py` | Confirm model / embedding proxy role |
| coze local agent | `E:\develop\customer-agent-coze\projects\src\agents\agent.py` | Confirm separate LangGraph agent role |
| coze tools | `projects\src\tools\llm_tool.py`, `knowledge_tool.py`, `product_tool.py` | Confirm LLM, knowledge, and product lookup paths |
| coze API | `projects\src\main.py` | Confirm `/ask`, `/ask/stream`, `/health` service |
| coze config | `projects\config\agent_llm_config.json`, `projects\.env.example` | Confirm non-sensitive fallback config |
| coze deployment docs | `projects\FASTGPT_DEPLOY.md`, `docs\fastgpt-ollama-embedding-fix.md` | Confirm historical FastGPT / Ollama proxy intent |
| Docker | `docker ps`, `docker inspect fastgpt-app`, `docker compose ls` | Confirm running containers and exposed ports |
| Local ports | `Get-NetTCPConnection` | Confirm listeners on 3000 / 8000 / 11434 / 11435 |

No write API was called. No container was restarted.

## 2. customer-agent-coze 目录结构和角色

`customer-agent-coze` contains two distinct runtime roles. Neither role should be confused with the FastGPT Agent API in the Docker FastGPT platform.

| Component | Location | Confirmed role | Current relation to PDD runtime |
| --- | --- | --- | --- |
| Ollama / Doubao proxy | `ollama_proxy.py` | HTTP proxy for FastGPT model-provider compatibility. Embedding paths go to Ollama; chat paths go to Doubao-compatible API. | Can be downstream of FastGPT. It is not directly called by refactor-v3 PDD runtime. |
| Local `/ask` FastAPI service | `projects\src\main.py` | Separate FastAPI service exposing `/ask`, `/ask/stream`, `/health`. | Running locally on port 8000, but no current refactor-v3 runtime call to this service was found. |
| LangGraph agent | `projects\src\agents\agent.py` | Builds a local `ChatOpenAI` + LangGraph react-agent with product tools. | Parallel / historical agent path, not proven to be used by current PDD reply chain. |
| LLM tool | `projects\src\tools\llm_tool.py` | Direct Doubao-compatible OpenAI client. Reads key only from environment. | Used by coze-side tooling, not by refactor-v3 FastGPTHandler. |
| Knowledge tool | `projects\src\tools\knowledge_tool.py` | Calls FastGPT dataset search API: `/api/core/dataset/search`. | Used by coze-side product tools; not used by refactor-v3 FastGPTHandler. |
| Product tools | `projects\src\tools\product_tool.py` | LangChain tools. Priority: remote FastGPT knowledge, local CSV fallback, then fallback text. | Registered in coze-side LangGraph agent only. |
| Agent config | `projects\config\agent_llm_config.json` | Non-sensitive fallback: model/base URL defaults, tool prompt, server port. API key field is empty. | Does not define FastGPT app/workflow binding for refactor-v3. |

Important distinction:

- `customer-agent-coze` is not the upstream endpoint for refactor-v3's current AI reply call.
- `ollama_proxy.py` may be used by FastGPT internally for chat and/or embedding, depending on FastGPT provider configuration.
- `projects/src/main.py` is a separate local `/ask` service. It can query FastGPT datasets through `knowledge_tool.py`, but no current refactor-v3 production path was found that calls `http://localhost:8000/ask`.

## 3. refactor-v3 到 FastGPT 请求链

Current refactor-v3 runtime path:

```text
PDD WebSocket
 -> Channel/pinduoduo/core/pdd_message_handler.py
 -> Message/core/consumer.py
 -> Message/core/pipeline.py
 -> Message/handlers/fastgpt_handler.py
 -> POST {FASTGPT_BASE_URL}/v1/chat/completions
 -> FastGPT service
```

Confirmed request construction in `FastGPTHandler.call()`:

| Field | Source / Value |
| --- | --- |
| URL | `{settings.fastgpt_base_url()}/v1/chat/completions` |
| Local default base URL | `http://localhost:3000/api` |
| Linux / production default base URL | `http://fastgpt:3000/api` |
| Credential source | `FASTGPT_API_KEY` via settings, with DB historical fallback elsewhere |
| Payload `model` | `doubao-seed-2-0-lite-260215` |
| Payload `messages` | Built by `MessagePipeline` from session context and buyer text |
| Payload `datasetId` | `shops.fastgpt_dataset_id` |
| Payload `chatId` | `shop_platform_id + buyer_id + session_id` |
| Payload `temperature` | default `0.7` |
| Payload `max_tokens` | default `120` |
| Payload `stream` | `False` |

Confirmed dataset handling in `MessagePipeline`:

- `dataset_id = (shop.get("fastgpt_dataset_id") or "").strip()`
- Missing dataset ID does not call FastGPT.
- Missing dataset ID sets the session to `pending_human` and triggers transfer-human notification.

Conclusion:

- refactor-v3 calls the FastGPT container/app service on port 3000.
- It does not call `customer-agent-coze` port 8000.
- It does not call `ollama_proxy.py` directly.

## 4. Docker FastGPT / Ollama / proxy 链路

Read-only Docker and port checks showed:

| Service | Runtime evidence | Port |
| --- | --- | --- |
| FastGPT app | container `fastgpt-app`, image `ghcr.io/labring/fastgpt:latest` | host `3000` -> container `3000` |
| FastGPT plugin | container `fastgpt-plugin` | internal `3000` |
| PostgreSQL | container `fastgpt-pg`, image `pgvector/pgvector:pg16` | host `5433` -> container `5432` |
| Redis | container `fastgpt-redis` | internal `6379` |
| MongoDB | container `fastgpt-mongo` | host `27018` -> container `27017` |
| MinIO | container `fastgpt-minio` | host `9000-9001` |
| Ollama | container `ollama` | host `11434` -> container `11434` |
| coze proxy | Windows process `D:\anaconda\python.exe ollama_proxy.py` | host `11435` |
| coze local `/ask` service | Windows process `D:\anaconda\envs\mynev\python.exe src\main.py --host 0.0.0.0 --port 8000` | host `8000` |

Observed local endpoint checks:

| Endpoint | Result |
| --- | --- |
| `http://localhost:8000/health` | HTTP 200, service reports `customer-agent` |
| `http://localhost:11435/v1/embeddings` `OPTIONS` | HTTP 200 |
| `http://localhost:3000/api/system/version` | HTTP 404, so this optional version endpoint is not available in the current FastGPT build |

Static FastGPT config evidence is mixed:

| Source | Finding |
| --- | --- |
| `E:\develop\fastgpt\config\config.json` | `chatBaseUrl` and `vectorBaseUrl` point to `http://host.docker.internal:11435`; default chat model is Doubao; vector model key is `text-embedding-ada-002`. |
| `E:\develop\fastgpt\docker-compose.yml` and container env | Chat/vector base URLs are configured to the Ark-compatible provider endpoint, with secrets omitted here. |
| T088-A dataset metadata | The two active shop datasets report vector model `bge-m3` and display name `ollama bge-m3`. |

Interpretation:

- The historical and dataset evidence confirms that Ollama bge-m3 has been used for current dataset indexing.
- Static Docker env and config file are not fully aligned. The effective provider used by current FastGPT app/workflow must be confirmed in the FastGPT console.
- Do not infer the active workflow provider solely from `docker-compose.yml`.

## 5. FastGPT app/workflow 绑定关系

Confirmed:

- refactor-v3 calls FastGPT's OpenAI-compatible app chat endpoint: `/api/v1/chat/completions` after base URL normalization.
- T088-B already established that this endpoint is the FastGPT app / agent conversation endpoint.
- refactor-v3 does not pass `FASTGPT_APP_ID`, `appId`, `workflowId`, or `agentId`.
- Product clarification after T088-C: the current FastGPT API key is bound to the screenshot workflow in the Docker-hosted FastGPT low-code platform.

Previously not confirmed by local-only evidence:

- Which FastGPT app is selected by the API key.
- Whether the request-level `datasetId` is consumed by the workflow graph or ignored by fixed node configuration.

Now business-confirmed:

- The key-to-app binding points to the screenshot workflow.
- The workflow uses `datasetId` / filter semantics for per-shop knowledge isolation.

Still requires console-level technical proof:

- The exact Knowledge Base Search node variable/expression that consumes `datasetId`.
- Whether collection-level filtering is available.
- Search parameters such as similarity, rerank, query rewrite, and reference token limit.

Most likely binding model:

```text
FastGPT API key
 -> selects one Docker FastGPT low-code app/workflow
 -> app executes its configured workflow graph
 -> request `chatId` identifies the conversation
 -> request `datasetId` may be available to knowledge retrieval, depending on node configuration
```

The high-level workflow binding is business-confirmed. Node-level dataset and retrieval behavior still needs FastGPT console configuration or a workflow execution trace.

## 6. workflow 节点和 customer-agent-coze 的关系

Code and config search did not find a direct FastGPT workflow definition in `customer-agent-coze`.

No local file evidence was found for:

- `workflowId`
- `agentId`
- a FastGPT workflow graph export
- a FastGPT node graph JSON checked into `customer-agent-coze`
- a workflow HTTP/tool/plugin node that calls `customer-agent-coze` `/ask`

Possible relationships:

| Relationship | Current evidence | Status |
| --- | --- | --- |
| FastGPT workflow calls `customer-agent-coze` `/ask` | No reference found in local code or docs; needs FastGPT console node inspection. | Unconfirmed, and not required by the confirmed PDD main chain |
| FastGPT model provider calls `ollama_proxy.py` | Historical docs and config file support this; dataset metadata supports bge-m3 usage. | Partially confirmed |
| FastGPT knowledge search calls coze `knowledge_tool.py` | No. `knowledge_tool.py` calls FastGPT; direction is coze -> FastGPT, not FastGPT -> coze. | Not in current chain |
| refactor-v3 calls coze agent API | No runtime reference found. | Not in current chain |

## 7. datasetId / Knowledge Base Search 使用方式

Confirmed in refactor-v3:

- `shops.fastgpt_dataset_id` is read from the local SQLite `shops` table.
- Current local DB has two shops with non-empty dataset IDs:

| shop_id_masked | shop_name | dataset_id_masked |
| --- | --- | --- |
| `3234***3738` | 美肌萌主驿站 | `6a08***6dcd` |
| `565***617` | 佳琪如梦 | `6a08***77b4` |

Confirmed in T088-A:

- Each current shop dataset has one CSV file collection.
- Current collections are product CSV imports.
- No separate collections were observed for logistics, after-sales, promotion, red-line escalation, sensitive users, or SOP.

Unconfirmed in workflow:

- Whether a Knowledge Base Search node dynamically uses incoming `datasetId`.
- Whether the workflow has a fixed linked dataset.
- Whether collection filtering is supported or configured.
- Whether the app key selects a fixed dataset independent of request `datasetId`.

Implication:

- The project is designed around per-shop dataset isolation.
- The actual FastGPT workflow must be inspected before implementing collection-level synchronization or workflow branch assumptions.

## 8. embedding 链路

Confirmed facts:

| Item | Current finding |
| --- | --- |
| Dataset vector model | `bge-m3` from T088-A dataset metadata |
| Vector display name | `ollama bge-m3` from T088-A dataset metadata |
| Ollama container | Running on host port `11434` |
| Proxy | `ollama_proxy.py` running on host port `11435` |
| Proxy embedding route | `/`, `/embeddings`, `/v1/embeddings` -> Ollama `/v1/embeddings` |
| Proxy chat route | `/`, `/chat/completions`, `/v1/chat/completions` with `messages` -> Doubao-compatible chat endpoint |

Historical rationale:

- `docs/fastgpt-ollama-embedding-fix.md` records that FastGPT v4.15.0 sent incompatible embedding requests to Ollama.
- The proxy normalized those requests so FastGPT could index via Ollama bge-m3.

External embedding API switch point:

- The switch is primarily in FastGPT model provider / vector provider configuration, not in refactor-v3.
- If changed from Ollama bge-m3 to an external embedding API, affected datasets need re-indexing / re-embedding.
- T083-C style synthetic QA should be rerun after any embedding switch.

## 9. 当前知识库结构和同步影响

Current knowledge shape:

| Domain | Current state |
| --- | --- |
| Product knowledge | Present as one CSV collection per shop dataset |
| Logistics policy | Not observed as independent collection |
| After-sales evidence collection | Not observed as independent collection |
| Promotion policy | Not observed as independent collection |
| Complaint / compensation red line | Not observed as independent collection |
| Sensitive users / medical safety wording | Not observed as independent collection |
| Merchant SOP | Not observed as versioned source-of-truth |

Architecture impact:

- Product CSV alone is insufficient for the T083-E / T083-F business policy decisions.
- Merchant SOP should be treated as the reviewed source-of-truth.
- FastGPT dataset should be treated as a derived artifact generated from reviewed SOP, product data, and policy documents.
- If workflow Knowledge Base Search cannot filter by collection, prefer either:
  - separate datasets by business domain, or
  - strict document headings / metadata conventions plus workflow query rewriting.
- Do not implement synchronization until workflow dataset/collection behavior is proven.

## 10. 信息链路图

Current confirmed PDD reply path:

```text
PDD WebSocket
 -> refactor-v3 PDD message handler
 -> MessageConsumer
 -> MessagePipeline
 -> FastGPTHandler
 -> POST http://localhost:3000/api/v1/chat/completions
    payload: messages + chatId + datasetId
 -> FastGPT Docker low-code platform
 -> screenshot workflow selected by app API key
 -> workflow nodes
 -> Knowledge Base retrieval using app/node config
 -> LLM response
 -> refactor-v3 AIReplyHandler
 -> SendMessage
 -> PDD buyer
```

Confirmed proxy/model side path:

```text
FastGPT Docker service
 -> model provider / vector provider configuration
 -> host.docker.internal:11435 if configured to proxy
 -> customer-agent-coze/ollama_proxy.py
    - embedding requests -> Ollama /v1/embeddings
    - chat requests -> Doubao-compatible /chat/completions
 -> model response
 -> FastGPT node / dataset indexing
```

Separate coze local `/ask` service path:

```text
External caller
 -> http://localhost:8000/ask
 -> customer-agent-coze FastAPI local service
 -> LangGraph react-agent
 -> product tools
 -> FastGPT dataset search API or local CSV fallback
 -> ChatOpenAI-compatible model
 -> response
```

No evidence currently connects this separate local service into the refactor-v3 PDD production path.

## 11. 已确认事实

1. refactor-v3 sends chat requests to FastGPT `/api/v1/chat/completions`.
2. refactor-v3 sends `datasetId`, `chatId`, `messages`, model, temperature, and max token fields.
3. refactor-v3 does not read or pass `FASTGPT_APP_ID`.
4. The current FastGPT API key is business-confirmed to bind to the screenshot workflow.
5. refactor-v3 does not call `customer-agent-coze` port 8000 in the current runtime chain.
6. `customer-agent-coze` port 8000 is running and exposes `/health`, `/ask`, and `/ask/stream`, but this is a separate local service rather than the FastGPT Agent API.
6. `ollama_proxy.py` is running on port 11435.
7. FastGPT Docker service is running on port 3000.
8. Ollama container is running on port 11434.
9. The two active shop datasets have non-empty dataset IDs.
10. T088-A confirmed both observed datasets use `bge-m3` / `ollama bge-m3` vector metadata.
11. Current dataset structure is one CSV file collection per shop dataset.
12. No local coze workflow graph export was found; workflow configuration lives in the Docker FastGPT low-code console.

## 12. 未确认事项

1. Whether the runtime request-level `datasetId` is consumed directly by a Knowledge Base Search node, or first mapped to a workflow variable.
2. Whether the workflow uses fixed datasets as fallback.
3. Whether collection-level filtering is available.
4. Whether chat generation currently goes through `ollama_proxy.py` or directly to the Ark-compatible provider endpoint.
5. Whether rerank is enabled.
6. Current workflow node retrieval parameters: topK, score threshold, query extension, reference token limit, history settings.
7. Whether any workflow HTTP/tool/plugin node calls `customer-agent-coze`.

## 13. 需要人工截图/导出的项目

FastGPT console items needed:

1. API key owner page showing which app the current key belongs to.
2. App basic settings: app ID, app type, model provider, published status.
3. Workflow canvas full screenshot.
4. Classifier node configuration.
5. Knowledge Base Search node configuration:
   - linked dataset source
   - whether incoming `datasetId` is referenced
   - collection filtering if any
   - topK / similarity threshold / rerank / query extension / max context
6. AI Chat node configuration:
   - model
   - prompt
   - temperature
   - max response length
   - history settings
   - quote / reference behavior
7. Human service / fixed reply nodes if present.
8. A synthetic debug run with node execution trace or `detail=true` response summary.
9. Dataset collection list for each shop:
   - collection ID masked
   - collection type
   - row count
   - updated time
   - training / indexing status

## 14. 架构判断

Current best judgment:

1. refactor-v3's runtime request enters the Docker FastGPT app/workflow endpoint.
2. The current API key is business-confirmed to bind to the screenshot workflow; node-level settings still need console proof.
3. `customer-agent-coze` is not the upstream AI responder for refactor-v3 PDD messages.
4. `customer-agent-coze` is currently relevant mainly as:
   - `ollama_proxy.py`, a model/embedding proxy that FastGPT can call downstream.
   - a standalone local `/ask` service that is separate from the current PDD runtime chain.
5. Current per-shop dataset design should be retained for isolation, but the workflow must be inspected before relying on dynamic `datasetId` behavior.
6. The current one-CSV-collection dataset shape is too coarse for business acceptance. It should evolve toward product, logistics, after-sales, promotion, red-line, sensitive-user, and SOP domains.
7. Merchant SOP should be the reviewed source-of-truth; FastGPT datasets should be generated artifacts.
8. Keep Ollama bge-m3 for now because current datasets are already indexed with it and T066-C pinned the Linux browser/runtime stack separately. External embedding API should be evaluated only after retrieval quality and latency tests justify the change.

## 15. 暂不建议实现的内容

Do not implement these yet:

1. FastGPT dataset synchronization code.
2. FastGPT workflow modification or prompt update.
3. Runtime switch from current app chat endpoint to a new app/workflow endpoint.
4. Collection-level routing assumptions.
5. External embedding API migration.
6. Re-indexing or re-embedding jobs.
7. Direct integration from refactor-v3 to `customer-agent-coze` `/ask`.
8. Docker compose rewiring for coze proxy services.

Recommended next action:

- First collect the FastGPT console screenshots / exports listed above.
- Then decide whether the current workflow already supports dynamic per-shop datasets.
- Only after that should T083-F knowledge categories be mapped to concrete dataset / collection / workflow changes.
