# T088-A FastGPT Runtime / Workflow / Dataset Inventory

Date: 2026-05-20

Scope: read-only inventory for current FastGPT runtime integration, local configuration, local SQLite metadata, and read-only FastGPT dataset / collection metadata. This report does not change code, database rows, FastGPT datasets, collections, workflow, prompt, knowledge base, or `.env`.

## 0. Sources And Method

Local sources inspected:

- `docs/acceptance/T083E_WORKFLOW_KB_POLICY_DECISIONS.md`
- `docs/acceptance/T083F_KNOWLEDGE_BASE_SUPPLEMENT_PLAN.md`
- `docs/acceptance/T083C_FASTGPT_SYNTHETIC_QA_REPORT.md`
- `docs/acceptance/T083D_FASTGPT_QA_REMEDIATION_MATRIX.md`
- `Message/handlers/fastgpt_handler.py`
- `Message/core/pipeline.py`
- `docs/config/ENVIRONMENT_VARIABLES.md`
- `database/models.py`
- `database/db_manager.py`
- `core/settings.py`
- Local SQLite DB, opened read-only: `temp/channel_shop.db`

Official FastGPT docs consulted:

- [FastGPT Dataset API](https://doc.fastgpt.io/en/openapi/dataset)
- [FastGPT Workflows & Plugins](https://doc.fastgpt.io/en/guide/build/workflow/intro)
- [FastGPT Knowledge Base Search node](https://doc.fastgpt.io/en/guide/build/workflow/nodes/dataset_search)
- [FastGPT Knowledge Base Search Methods and Parameters](https://doc.fastgpt.io/en/guide/dataset/dataset_engine)
- [FastGPT API File Library](https://doc.fastgpt.io/en/docs/guide/knowledge_base/api_dataset/)

Read-only FastGPT API calls performed:

- `GET /api/core/dataset/detail?id=...`
- `POST /api/core/dataset/collection/listV2`

Not performed:

- No dataset / collection / data creation, update, deletion, or `pushData`.
- No `searchTest`, because it can return raw knowledge chunks and this inventory should not dump knowledge text.
- No workflow update or prompt update.

Sensitive handling:

- API keys and provider auth values were not written to this report.
- Dataset and collection IDs are masked.
- Local DB `fastgpt:api_key` was checked only for presence, length, and hash.

## 1. Current FastGPT Call Chain

Runtime chain:

1. PDD WebSocket message is converted into `Context`.
2. Message is enqueued into `pdd_{shop_id}`.
3. `MessageConsumer` selects `AIReplyHandler`.
4. `AIReplyHandler._get_ai_reply()` lazily initializes:
   - `DatabaseManager`
   - `SessionManager`
   - `KeywordHandler`
   - `FastGPTHandler`
   - `MessagePipeline`
5. `MessagePipeline.process()` resolves the shop and conversation.
6. `MessagePipeline` reads `shops.fastgpt_dataset_id`.
7. `MessagePipeline` builds `chat_id = "{shop_platform_id}_{buyer_id}_{session_id}"`.
8. `MessagePipeline` calls `FastGPTHandler.call()` through `asyncio.to_thread`.
9. `FastGPTHandler.call()` sends `POST {FASTGPT_BASE_URL}/v1/chat/completions`.
10. Pipeline returns `reply`, `transfer_human`, `block`, or `skip`.
11. `AIReplyHandler._send_reply()` sends the final PDD reply only when the action requires a reply.

Configuration sources:

| Item | Current source | Notes |
| --- | --- | --- |
| `FASTGPT_BASE_URL` | `core/settings.py`, from env / `.env`, default by `APP_ENV` | local default `http://localhost:3000/api`; linux/production default `http://fastgpt:3000/api` |
| `FASTGPT_API_KEY` | env / `.env` via `core/settings.py`; historical DB fallback `app_config.fastgpt:api_key` | current local DB has `fastgpt:api_key` present; value not printed |
| `shops.fastgpt_dataset_id` | `shops` table | required for the normal FastGPT path |
| `chatId` | generated in `MessagePipeline` | `shop_platform_id + buyer_id + session_id` |
| `FASTGPT_APP_ID` | not read by current runtime | reserved only; current runtime does not call an application ID route |

Current request payload in `FastGPTHandler.call()`:

| Field | Value / source |
| --- | --- |
| `model` | hardcoded `doubao-seed-2-0-lite-260215` |
| `messages` | session context from `SessionManager.build_context_messages()` |
| `datasetId` | `shops.fastgpt_dataset_id` |
| `chatId` | generated synthetic runtime chat ID |
| `temperature` | default `0.7` |
| `max_tokens` | default `120` |
| `stream` | `False` |

Important implication:

- Updated by T088-B / T088-D: the local code calls FastGPT's app / agent chat endpoint and does not pass `appId` or `workflowId` explicitly, but the FastGPT API key is now business-confirmed to bind to the screenshot workflow in the Docker-hosted FastGPT low-code platform.
- Therefore workflow node topology still cannot be inferred from the local runtime request alone; it must be read from the FastGPT console or execution trace.

## 2. Current Model Configuration

Runtime request model:

| Config | Value | Source |
| --- | --- | --- |
| Chat model in request payload | `doubao-seed-2-0-lite-260215` | hardcoded in `Message/handlers/fastgpt_handler.py` |
| ConfigManager LLM default | `doubao-seed-1-6-flash-250828` | `core/config_manager.py` default |
| `.env.example` LLM sample | `doubao-seed-2-0-mini-260215` | docs/sample only |

Dataset-level model metadata from read-only FastGPT API:

| dataset_id_masked | dataset_name | dataset_status | vector_model | vector_name | vector_endpoint | agent_model | agent_name |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `6a08***6dcd` | 美肌萌主驿站 | active | `bge-m3` | `ollama bge-m3` | local proxy / Ollama-compatible endpoint | `doubao-seed-2-0-mini-260215` | 豆包mini |
| `6a08***77b4` | 佳琪如梦 | active | `bge-m3` | `ollama bge-m3` | local proxy / Ollama-compatible endpoint | `doubao-seed-2-0-mini-260215` | 豆包mini |

Embedding conclusion:

- Current FastGPT datasets are using local/Ollama-style `bge-m3` embedding through a local proxy endpoint.
- This matches the current architecture assumption that embeddings are local bge / bge-m3 class models.
- Dataset metadata did not show an external embedding API provider as the active vector model for these two datasets.

Rerank / search model conclusion:

- Dataset detail and collection list API did not expose active rerank configuration.
- Official FastGPT docs describe rerank and hybrid search behavior, but the current dataset metadata query did not prove whether rerank is enabled for the current runtime.
- Rerank, search mode, minimum relevance, query extension, reference token limit, and max context should be exported from the FastGPT console or tested through controlled `searchTest` later.

Security note:

- FastGPT dataset detail returned provider auth metadata. It was treated as sensitive and intentionally excluded from this report.

## 3. Current Dataset / Collection Structure

Local DB shop readiness:

| channel | shop_id_masked | user_id_masked | account_status | dataset_id_masked | dataset_present | expected_route |
| --- | --- | --- | ---: | --- | --- | --- |
| pinduoduo | `3234***3738` | `1633***9769` | 1 | `6a08***6dcd` | yes | FastGPT route eligible |
| pinduoduo | `5***7` | `7***9` | 1 | `6a08***77b4` | yes | FastGPT route eligible |

FastGPT dataset / collection metadata:

| dataset_id_masked | dataset_name | update_time | collection_count | collection_id_masked | collection_name | type | training_type | data_amount | training_amount | collection_update_time |
| --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | --- |
| `6a08***6dcd` | 美肌萌主驿站 | 2026-05-16T11:25:45.876Z | 1 | `6a08***6ea4` | `fastgpt_export_20260516_192609.csv` | file | chunk | 38 | 0 | 2026-05-16T11:32:08.742Z |
| `6a08***77b4` | 佳琪如梦 | 2026-05-16T11:32:25.821Z | 1 | `6a08***af25` | `fastgpt_export_20260516_231946.csv` | file | chunk | 48 | 0 | 2026-05-16T15:25:38.279Z |

Observed collection structure:

- Each shop currently has one FastGPT file collection.
- Both collections appear to be CSV exports.
- Both use `trainingType=chunk`.
- There is no observed separate collection by product, logistics policy, after-sales SOP, promotion policy, redline escalation, or FAQ.
- No folder hierarchy was visible from the collection list response.
- Collection naming currently follows export timestamp naming, not business-domain naming.

Local SQLite knowledge tables:

| shop_id_masked | product_knowledge_count | customer_service_knowledge_count | enabled_keyword_count |
| --- | ---: | ---: | ---: |
| `3234***3738` | 36 | 0 | 0 |
| `5***7` | 46 | 0 | 0 |

Implication:

- Local product knowledge exists in SQLite, but the audited FastGPT runtime path does not retrieve it before the FastGPT call.
- Current FastGPT dataset content appears derived from CSV exports, not from a versioned SOP/FAQ/policy collection design.

## 4. Current Knowledge Shape Analysis

Current observed shape:

| Knowledge type | Current evidence | Assessment |
| --- | --- | --- |
| Q&A | Not proven from metadata; collections use `chunk`, not `qa` | likely not primary shape |
| Markdown docs | Not visible | not proven |
| Product data | Local SQLite has product rows; FastGPT collections are CSV exports | likely primary current dataset content |
| Policy / SOP | Not separately visible | missing or mixed into CSV |
| Table knowledge | CSV file collections indicate table-like source | likely present |
| No-auto-promise boundary | Not separately visible | needs explicit collection / document |
| After-sales evidence collection | Not separately visible | needs explicit collection / document |
| Logistics policy | Some synthetic QA answers show logistics policy exists, but not separated | needs controlled policy wording |
| Redline escalation | Some answers transfer, but one fake-product case failed | workflow / policy boundary incomplete |

Current quality signal from T083-C:

- Both datasets can answer some product / greeting / basic logistics questions.
- Failures cluster around no-order logistics delay, damaged / missing / wrong item evidence handling, and fake-product redline routing.
- This means dataset existence is not enough; workflow routing and domain-specific policy collections are needed.

Recommended knowledge partition:

| Partition | Suggested collection style |
| --- | --- |
| Product facts | structured product collection, generated from DB / CSV |
| Store logistics policy | Markdown SOP collection |
| Promotion policy | Markdown SOP collection |
| After-sales evidence collection | Markdown SOP collection |
| Redline human escalation | Markdown policy collection |
| Sensitive user / health safety | Markdown policy collection |
| FAQ examples | optional Q&A collection, generated from approved SOP |

## 5. Current Workflow Structure

Current runtime does not call a FastGPT application ID:

- `FASTGPT_APP_ID` is reserved and not used.
- No runtime app/workflow ID is passed to FastGPT.
- No workflow node list can be derived from the current local code path.
- The observed path relies on `datasetId` in the chat-completions payload.

What was obtained by API:

- Dataset details.
- Collection list.
- Dataset model metadata.

What was not obtained:

- Workflow node graph.
- Classification nodes.
- Branch names.
- AI Chat nodes.
- Knowledge Base Search nodes.
- Manual service / specified reply nodes.
- Branch-to-dataset mapping.

Required manual FastGPT console export / screenshot:

| Needed artifact | Why needed |
| --- | --- |
| Application workflow canvas | confirm whether any application workflow exists outside current runtime |
| Node list with IDs/types | verify classifier, KB search, AI chat, specified reply, human escalation nodes |
| Branch conditions / classifier labels | verify `logistics_policy`, `logistics_order_status`, `after_sales_evidence_collection`, `human_escalation_redline` |
| Knowledge Base Search node config | inspect selected datasets, search mode, limit, similarity, query extension, rerank |
| AI Chat node config | inspect prompt, model, history count, max response, temperature |
| Human / specified reply nodes | verify redline escalation behavior |

Current workflow gap against T083-E:

| Required branch | Current proof | Status |
| --- | --- | --- |
| `product_basic` | synthetic QA mostly passes | partially covered |
| `logistics_policy` | generic shipping answers exist | partially covered |
| `logistics_order_status` | no-order "not arrived" failed | missing / insufficient |
| `promotion_policy` | mostly passes, one timeout | partially covered |
| `after_sales_evidence_collection` | damaged/missing/wrong item failed or unstable | missing / insufficient |
| `human_escalation_redline` | fake-product failed for one shop | missing / insufficient |
| `explicit_human_request` | synthetic QA passes | partially covered |

## 6. Retrieval Configuration

Known from FastGPT metadata:

| Item | Current value |
| --- | --- |
| Vector model | `bge-m3` |
| Vector model display name | `ollama bge-m3` |
| Vector max token | 2048 |
| Vector default token | 512 |
| Vector batch size | 5 |
| Dataset collection training type | `chunk` |
| Collection data amount | 38 / 48 |
| Collection training amount | 0 / 0 |

Unknown from read-only metadata:

| Config | Status |
| --- | --- |
| search mode | not exposed by dataset detail / collection list |
| topK | FastGPT docs prefer reference token limit over unstable topK in mixed knowledge bases; current node config unknown |
| reference token limit | unknown |
| minimum relevance / similarity threshold | unknown |
| rerank enabled | unknown |
| rerank model | unknown |
| query extension enabled | unknown |
| query extension model | unknown |
| max context for chat node | runtime request does not expose workflow node max context |
| chunk size / overlap | not returned by collection list; collection detail could expose `chunkSize` for a specific collection, but was not queried to avoid expanding metadata scope |
| index training status details | not queried; collection `trainingAmount=0` suggests no pending training in the list response |

Recommended next read-only export:

- Export or screenshot each Knowledge Base Search node's search parameters from FastGPT console.
- If later using API, run `searchTest` with synthetic non-private queries only and do not store raw retrieved chunks in public docs.

## 7. FastGPT API Capability Inventory

Based on the official Dataset API documentation:

| Capability | API / documentation status | Fit for merchant SOP sync |
| --- | --- | --- |
| Dataset create | `POST /api/core/dataset/create` | useful for onboarding new shop datasets |
| Dataset list / detail | `POST /api/core/dataset/list`, `GET /api/core/dataset/detail` | useful for inventory and audit |
| Dataset delete | `DELETE /api/core/dataset/delete` | dangerous; not needed for phase one |
| Collection create empty | `POST /api/core/dataset/collection/create` | useful for versioned folder/manual collection setup |
| Text collection create | `POST /api/core/dataset/collection/create/text` | useful for SOP Markdown ingestion |
| Link collection create | `POST /api/core/dataset/collection/create/link` | useful only for controlled public docs |
| Local file collection create | `POST /api/core/dataset/collection/create/localFile` | useful for Markdown/CSV upload pipelines |
| API collection create | `POST /api/core/dataset/collection/create/apiCollection` | useful for managed file IDs |
| External file collection | commercial endpoint | useful if using external source-of-truth files |
| Collection list / detail | `POST /api/core/dataset/collection/listV2`, `GET /api/core/dataset/collection/detail` | useful for inventory and drift detection |
| Collection update / delete | update/delete endpoints exist | should be controlled by versioning and approvals |
| Batch add data | `POST /api/core/dataset/data/pushData`, max 200 groups per push in docs | suitable for structured SOP/product sync after design |
| Data list / detail | data list/detail endpoints exist | useful for audit, but may expose raw knowledge content |
| Data update / delete | update/delete endpoints exist | should be gated by review workflow |
| Search test | `POST /api/core/dataset/searchTest` | useful for retrieval QA with synthetic queries |

API fit conclusion:

- `pushData` is suitable for derived data synchronization only after a source-of-truth and versioning model exists.
- API File Library / external file collection can be suitable if merchant SOP files live outside FastGPT and FastGPT should ingest derived artifacts.
- Do not start with a sync implementation until SOP ownership, review, versioning, rollback, and per-shop override strategy are decided.

## 8. Architecture Decision Recommendations

Recommended ownership model:

| Layer | Recommendation |
| --- | --- |
| Merchant SOP source of truth | keep outside FastGPT as reviewed Markdown / structured records / approved docs |
| FastGPT dataset | treat as derived artifact generated from approved source-of-truth |
| Product facts | keep structured source in DB/CSV; generate FastGPT product collection |
| Policies / SOP / no-auto-promise boundaries | store as reviewed Markdown documents, then ingest into FastGPT |
| FAQ | generate or curate from SOP; optional Q&A collection |
| Workflow | own intent classification and routing; do not rely on a single free-form dataset search |
| Code | own missing dataset, FastGPT failure, media intercepts, send failure, privacy, trace, and notification isolation |

Embedding recommendation:

- Keep `bge-m3` / Ollama embedding for now because current datasets already use it and Linux deployment has an Ollama/proxy path.
- Do not switch to an external embedding API until:
  - recall quality has been measured with a retrieval test set,
  - cost/latency/privacy are approved,
  - re-embedding downtime or migration plan is defined.
- Any embedding model switch requires re-indexing/re-embedding affected datasets and rerunning synthetic QA.

Dataset / collection recommendation:

- Keep each shop's dataset independent for shop-specific product facts and policies.
- Consider a shared template source for common safety/redline SOP, then materialize it into each shop dataset as a derived collection.
- Use explicit collection naming, for example:
  - `product_catalog_vYYYYMMDD`
  - `logistics_policy_vYYYYMMDD`
  - `promotion_policy_vYYYYMMDD`
  - `after_sales_evidence_vYYYYMMDD`
  - `redline_human_escalation_vYYYYMMDD`
  - `sensitive_user_safety_vYYYYMMDD`
- Avoid a single timestamped CSV collection as the only knowledge shape.

Workflow recommendation:

- Introduce explicit workflow branches from T083-E:
  - `product_basic`
  - `logistics_policy`
  - `logistics_order_status`
  - `promotion_policy`
  - `after_sales_evidence_collection`
  - `human_escalation_redline`
  - `explicit_human_request`
  - `fallback`
- Use Knowledge Base Search nodes per branch or branch group.
- Use specified reply / human escalation nodes for redline cases.
- Ensure `logistics_order_status` never claims a specific order state without order context.

## 9. Pending Decisions

| Decision | Options | Recommended direction |
| --- | --- | --- |
| SOP review owner | product / ops / shop owner | assign shop owner + product reviewer before dataset ingestion |
| SOP versioning | file names / DB version table / Git docs | use versioned source docs first; add DB sync table later |
| Dataset structure | one collection per export vs domain collections | move to domain collections |
| Dataset sharing | per-shop independent vs shared template + shop override | shared template source + per-shop materialized dataset |
| Product source | DB / Markdown / CSV / FastGPT-only | DB/CSV source of truth, FastGPT derived |
| Policy source | Markdown / DB / FastGPT-only | reviewed Markdown source of truth |
| Knowledge sync state | none / app_config / dedicated table | dedicated table later if automated sync is built |
| Embedding model switch | keep Ollama bge-m3 / external API | keep bge-m3 until retrieval tests show need |
| Workflow template | per-shop workflow / shared workflow | shared workflow template, per-shop dataset parameters |
| Raw knowledge audit | API data list / console export / no raw export | controlled console export or API export into private diagnostic artifact, not public docs |

## 10. Next Direction Only

Recommended next directions:

1. Manually export or screenshot the FastGPT workflow canvas and node configs.
2. Export read-only Knowledge Base Search node retrieval settings.
3. Build a retrieval-only synthetic test set for:
   - logistics no-order context,
   - after-sales evidence collection,
   - redline human escalation,
   - promotion no-private-discount,
   - sensitive user safety.
4. Decide SOP source-of-truth and review workflow.
5. Decide collection versioning and naming policy.
6. Only after those decisions, design a dataset sync mechanism.

Do not implement now:

- Do not write a dataset sync job yet.
- Do not call `pushData` yet.
- Do not change embedding provider yet.
- Do not create or delete datasets/collections yet.
- Do not rewrite workflow or prompt from code.
- Do not make `FASTGPT_APP_ID` mandatory until runtime actually uses an application workflow route.

## 11. Information Coverage Summary

Information obtained locally:

- Runtime FastGPT call chain.
- FastGPT URL / key source semantics.
- `shops` schema and dataset field.
- Two current PDD shops and their masked dataset IDs.
- Local product knowledge counts.
- Current DB `fastgpt:api_key` presence by length/hash only.
- Direct runtime `model`, `datasetId`, `chatId`, and failure behavior.

Information obtained via read-only FastGPT API:

- Dataset names, active status, update time.
- Dataset vector model metadata.
- Dataset agent model metadata.
- Collection list, type, training type, data amount, training amount, update time.

Information still requiring FastGPT console export/screenshot:

- Workflow node graph.
- Classification node labels and branch conditions.
- Knowledge Base Search node settings.
- AI Chat node prompt/model/history/max response settings.
- Rerank/search mode/minimum relevance/reference token limit.
- Whether an application workflow exists but is not used by current runtime.
