# T088-B FastGPT Agent API And Workflow Binding Audit

Date: 2026-05-20

Scope: read-only audit for the current runtime FastGPT endpoint, app / agent / workflow binding semantics, and the role of per-shop `datasetId`. This report does not modify code, database rows, FastGPT workflow, prompts, datasets, collections, data, or `.env`.

## 1. Audit Scope

Local sources inspected:

- `docs/architecture/T088A_FASTGPT_RUNTIME_INVENTORY.md`
- `docs/acceptance/T083E_WORKFLOW_KB_POLICY_DECISIONS.md`
- `docs/acceptance/T083F_KNOWLEDGE_BASE_SUPPLEMENT_PLAN.md`
- `Message/handlers/fastgpt_handler.py`
- `Message/core/pipeline.py`
- `core/settings.py`
- `docs/config/ENVIRONMENT_VARIABLES.md`
- `database/models.py`
- `database/db_manager.py`

Official FastGPT documentation consulted:

- [FastGPT Chat API](https://doc.fastgpt.io/zh-CN/openapi/chat)
- [FastGPT Application API](https://doc.fastgpt.io/en/openapi/app)
- [FastGPT Workflows & Plugins](https://doc.fastgpt.io/en/guide/build/workflow/intro)
- [FastGPT Knowledge Base Search node](https://doc.fastgpt.io/en/guide/build/workflow/nodes/dataset_search)
- [FastGPT Dataset API](https://doc.fastgpt.io/en/openapi/dataset)

Read-only metadata reused from T088-A:

- Local SQLite shop / dataset readiness inventory.
- FastGPT dataset detail metadata.
- FastGPT collection list metadata.

Not performed in this audit:

- No FastGPT chat request.
- No `detail=true` runtime probe, because it may create chat history and return raw node data.
- No dataset / collection / data create, update, delete, or `pushData`.
- No workflow or prompt update.
- No PDD message send and no WebSocket startup.

## 2. Current Endpoint Semantics

Current project runtime sends:

```text
POST {FASTGPT_BASE_URL}/v1/chat/completions
```

`FASTGPT_BASE_URL` is read from `core/settings.py`:

- local default: `http://localhost:3000/api`
- linux / production default: `http://fastgpt:3000/api`
- explicit environment value wins

Therefore the effective default endpoint is FastGPT's native:

```text
/api/v1/chat/completions
```

This is not a local project-specific proxy endpoint. No local Python file was found that implements or rewrites this endpoint.

FastGPT official Chat API documentation describes `/api/v1/chat/completions` as the GPT-compatible endpoint for requesting conversation Agent and workflow execution. The same documentation states that the request should use an application-specific key and that fields such as `model` and `temperature` are controlled by the orchestration rather than by the API payload when using this application/workflow endpoint.

Implications:

- The endpoint is a FastGPT application chat endpoint, not a raw dataset management endpoint.
- The runtime does not pass `appId`.
- Application / agent / workflow selection is expected to be bound by the FastGPT-side API key or application configuration, not by local `FASTGPT_APP_ID`.
- Runtime payload fields `model`, `temperature`, and `max_tokens` may be ignored by FastGPT workflow orchestration, depending on the application type and node configuration.
- Current runtime does not pass `detail=true`, so it cannot observe node-level execution details in normal production traffic.

## 3. Does Current Runtime Hit A Workflow?

Current status is a two-layer conclusion:

| Question | Current conclusion | Evidence |
| --- | --- | --- |
| Does runtime call the FastGPT app / agent chat endpoint? | Yes. | `FastGPTHandler.call()` posts to `/v1/chat/completions`; official docs describe this as the Agent/workflow conversation endpoint. |
| Does local code explicitly select an app/workflow by ID? | No. | No runtime read of `FASTGPT_APP_ID`; no `appId`, `workflowId`, or `agentId` is passed in `FastGPTHandler.call()`. |
| Does the request execute a FastGPT workflow internally? | Likely, if the configured FastGPT key belongs to a workflow/advanced app; not proven at node level. | Official endpoint semantics support workflow execution, but this audit did not obtain the key-to-app binding or node trace. |
| Is the screenshot workflow definitely the runtime workflow? | Not confirmed. | Need FastGPT console/API proof that the runtime key belongs to that exact app/workflow. |

The previous T088-A wording "direct chat-completions call, not a configured workflow call" should be read narrowly: the local code does not pass an app/workflow ID. It does not mean the FastGPT server cannot route the request into an app workflow. T088-B refines that conclusion: endpoint semantics support workflow execution; exact workflow binding remains unverified.

To prove the exact workflow for a single request without guessing, use one of these read-only / low-risk methods later:

1. FastGPT console: locate the application whose API key matches the configured key, then export or screenshot its workflow canvas and node settings.
2. FastGPT chat trace: send a synthetic non-private request with `detail=true` in an isolated acceptance chat ID, then inspect returned flow/node metadata without storing raw buyer data in public reports.
3. FastGPT chat history API: if `appId` and `chatId` are known, inspect the response data for a synthetic acceptance run only.

## 4. App / Agent / Workflow Binding Relationship

Current runtime binding inputs:

| Binding item | Current local status |
| --- | --- |
| `FASTGPT_BASE_URL` | Used. |
| `FASTGPT_API_KEY` | Used when provided by environment; DB `fastgpt:api_key` remains historical fallback. |
| DB `fastgpt:api_key` | Present in local DB per T088-A, checked only by length/hash. |
| `FASTGPT_APP_ID` | Reserved only; current runtime does not read it. |
| `appId` request field | Not sent. |
| `workflowId` request field | Not sent. |
| `agentId` request field | Not sent. |
| `datasetId` request field | Sent from `shops.fastgpt_dataset_id`. |
| `chatId` request field | Generated as shop/buyer/session-scoped ID. |

Likely binding model:

- FastGPT app/agent/workflow is selected server-side by the application-specific API key.
- `chatId` identifies conversation history under the selected FastGPT app.
- `datasetId` is an extra runtime selector sent by this project, but its exact effect depends on FastGPT server behavior and workflow node configuration.

Unknowns requiring FastGPT console/export:

- App ID bound to the current runtime key.
- App type: simple chat app, advanced workflow app, or plugin.
- Workflow ID / current workflow version.
- Whether the current API key belongs to the screenshot workflow.
- Whether multiple runtime keys exist and point to different apps.

## 5. Role Of `datasetId` In The Workflow

Current project behavior:

1. `MessagePipeline.process()` resolves the PDD shop.
2. It reads `shops.fastgpt_dataset_id`.
3. Missing dataset ID triggers transfer-to-human and skips FastGPT.
4. Present dataset ID is passed to `FastGPTHandler.call()` as `datasetId`.

What is confirmed:

- Each currently enabled PDD shop has a non-empty `shops.fastgpt_dataset_id`.
- T088-A read-only API confirmed those dataset IDs exist in FastGPT.
- T083-C synthetic QA showed store-specific answers, which suggests the per-shop dataset is participating in some way.

What is not confirmed:

- Whether FastGPT's `/v1/chat/completions` endpoint officially treats `datasetId` as a standard selector for this app/workflow path.
- Whether a workflow Knowledge Base Search node dynamically uses the incoming `datasetId`.
- Whether the workflow instead has a fixed linked dataset and ignores the request-level `datasetId`.
- Whether the dataset search node can filter by collection in the current workflow.

Required verification:

| Verification item | Why it matters |
| --- | --- |
| Knowledge Base Search node linked datasets | Confirms fixed dataset vs dynamic dataset. |
| Node input variables | Confirms whether runtime `datasetId` is referenced. |
| Node search parameters | Confirms recall behavior and business-domain routing. |
| `detail=true` synthetic trace | Shows actual datasetSearchNode / AI Chat node execution and quoted dataset IDs. |

Architecture implication:

- If workflow uses fixed datasets, runtime `datasetId` may be inert and per-shop isolation depends on API key/app configuration instead.
- If workflow uses incoming `datasetId`, current per-shop dataset design is viable.
- If collection-level routing is not available, use domain-separated collections plus naming/metadata discipline, or split datasets by business domain.

## 6. Workflow Node Information Or Required Export Checklist

Node-level workflow information was not obtained by API in this audit.

Required FastGPT console export / screenshot:

| Needed artifact | Required details |
| --- | --- |
| Workflow canvas full view | App name, app type, current workflow graph, node IDs if visible. |
| Start / input node | Available variables, whether request variables include dataset ID or shop fields. |
| Classifier nodes | Labels, descriptions, branch conditions, fallback behavior. |
| Knowledge Base Search nodes | Linked datasets, dynamic variable references, search mode, limit/reference token, similarity, rerank, query extension. |
| AI Chat nodes | Prompt, model, temperature, max response length, history count, context input, quote handling. |
| Specified Reply nodes | Fixed replies, redline replies, no-answer replies. |
| Human service / escalation nodes | Whether true transfer exists or only wording-level escalation. |
| Plugin / HTTP nodes | Any external business logic, order lookup, or notification side effects. |

Branch coverage to inspect against T083-E:

| Required branch | Current proof | Status |
| --- | --- | --- |
| `product_basic` | Synthetic QA mostly passes. | partially proven |
| `logistics_policy` | Generic logistics answers exist. | partially proven |
| `logistics_order_status` | No-order "not arrived" cases failed. | needs workflow guardrail |
| `promotion_policy` | Mostly acceptable, one timeout case. | partially proven |
| `after_sales_evidence_collection` | Damaged / missing / wrong item cases failed or unstable. | needs workflow branch and KB support |
| `human_escalation_redline` | Fake-product case failed for one shop. | needs deterministic workflow escalation |
| `explicit_human_request` | Synthetic QA passed. | partially proven |
| `fallback` | Runtime fallback exists in code; workflow fallback unknown. | unknown |

## 7. Knowledge Base Search Configuration Or Required Export Checklist

Official FastGPT Knowledge Base Search node documentation states that the node has linked knowledge bases, search parameters, and referenced-content output. It also notes that search output can be empty while the successor path still runs.

Current local/API-known facts:

- Both shop datasets use `bge-m3` vector model metadata.
- Both shop datasets have one file collection.
- Both collections are timestamped CSV exports.
- No domain-specific collection split was observed.

Unknown Knowledge Base Search configuration:

| Config | Status |
| --- | --- |
| linked dataset mode | unknown |
| request-level `datasetId` usage | unknown |
| collection filter | unknown |
| search mode | unknown |
| reference token / limit | unknown |
| minimum relevance / similarity | unknown |
| rerank enabled/model | unknown |
| query extension | unknown |
| no-result branch behavior | unknown |
| quote injection into AI Chat node | unknown |

Required export:

- Search node settings panel for every Knowledge Base Search node.
- Any variable mapping panel that references runtime inputs.
- Any collection/tag filtering settings.
- Search test result for synthetic non-private questions, with raw knowledge text kept out of public docs.

## 8. Embedding / Retrieval Configuration

Confirmed from T088-A read-only dataset metadata:

| Item | Current value |
| --- | --- |
| vector model | `bge-m3` |
| vector display name | `ollama bge-m3` |
| vector max token | 2048 |
| vector default token | 512 |
| vector batch size | 5 |
| collection training type | `chunk` |
| active external embedding API | not observed |

Unknown:

- Rerank model and whether rerank is enabled.
- Hybrid search vs semantic search vs full-text search.
- Minimum relevance threshold.
- Query extension.
- Reference token limit.
- Chunk size and overlap.

Architecture judgment:

- Keep local/Ollama `bge-m3` for now.
- Do not switch embedding provider before retrieval tests prove a recall problem or operational need.
- Any embedding model switch should be treated as re-indexing/re-training work and followed by T083-C style synthetic QA.

## 9. Current Knowledge Base Structure Judgment

Current structure:

| Shop | Dataset | Collections | Structure judgment |
| --- | --- | --- | --- |
| Shop A | `6a08***6dcd` | one timestamped CSV file collection | product-export oriented; no domain split |
| Shop B | `6a08***77b4` | one timestamped CSV file collection | product-export oriented; no domain split |

What appears true:

- One dataset per shop is currently in use.
- Current FastGPT knowledge is mostly derived from exported product/shop rows.
- The current dataset structure is not yet organized by business domain.

What is missing or unproven:

- Dedicated logistics policy collection.
- Dedicated after-sales evidence collection.
- Dedicated promotion / discount boundary collection.
- Dedicated redline / complaint / compensation / fake-product collection.
- Dedicated sensitive-user safety collection.
- SOP versioning.
- Collection naming discipline beyond export timestamp.

Recommended target shape:

- Keep one dataset per shop for isolation.
- Add business-domain collections inside each dataset:
  - `product_catalog_vYYYYMMDD`
  - `logistics_policy_vYYYYMMDD`
  - `promotion_policy_vYYYYMMDD`
  - `after_sales_evidence_vYYYYMMDD`
  - `redline_human_escalation_vYYYYMMDD`
  - `sensitive_user_safety_vYYYYMMDD`
- Treat merchant SOP as source of truth.
- Treat FastGPT dataset/collections as derived artifacts from reviewed SOP/product data.

## 10. Architecture Conclusion

1. Current runtime uses FastGPT's app/agent chat endpoint.
2. Local code does not explicitly pass `FASTGPT_APP_ID`, `appId`, `workflowId`, or `agentId`.
3. Exact app/workflow selection is most likely server-side through the configured FastGPT application key.
4. Runtime workflow execution is likely if the configured key belongs to a workflow/advanced app, but the exact app/workflow/node graph is not yet proven.
5. Runtime sends `datasetId`, and synthetic QA plus dataset inventory suggest per-shop datasets affect responses, but the node-level mechanism is unverified.
6. The screenshot workflow should not be treated as production-bound until the API key-to-app binding and node trace are verified.
7. There is no need to immediately change runtime to read `FASTGPT_APP_ID`; first confirm current app-key binding and workflow behavior.
8. Per-shop datasets should continue, but each dataset should evolve from one CSV collection into domain-specific collections.
9. Merchant SOP should be the source of truth; FastGPT dataset should be a generated/synchronized delivery artifact.
10. Knowledge sync implementation should wait until workflow node design and SOP versioning are decided.

## 11. Decisions Required From You

| Decision | Options | Recommended direction |
| --- | --- | --- |
| How to prove runtime workflow binding | console export / synthetic `detail=true` trace / both | use both; console first, synthetic trace second |
| Is the screenshot workflow production-bound | yes / no / unknown | unknown until key-to-app binding is shown |
| Runtime app selection | keep app-key binding / add explicit `FASTGPT_APP_ID` route | keep current runtime until binding proof says otherwise |
| Dataset isolation | one dataset per shop / shared dataset | keep one dataset per shop |
| Collection design | one CSV / domain collections | move to domain collections |
| SOP ownership | FastGPT-only / external reviewed SOP | external reviewed SOP as source of truth |
| Retrieval testing | raw user logs / synthetic cases | synthetic non-private cases only |
| Embedding provider | keep local bge-m3 / external embedding API | keep local bge-m3 for phase one |

## 12. Implementations Not Recommended Now

Do not implement these until workflow binding is proven:

- Do not make `FASTGPT_APP_ID` mandatory in runtime.
- Do not rewrite runtime to a different FastGPT endpoint.
- Do not implement dataset synchronization or `pushData`.
- Do not create/delete/update datasets or collections.
- Do not change FastGPT workflow or prompt from code.
- Do not switch embedding provider.
- Do not merge shop datasets into one shared dataset.
- Do not use production buyer messages for retrieval QA.

Recommended next read-only steps:

1. Export or screenshot the FastGPT app API key page showing which app owns the runtime key.
2. Export or screenshot the workflow canvas for that app.
3. Export Knowledge Base Search node settings.
4. Run a controlled synthetic `detail=true` request in a dedicated acceptance chat ID, then record only node names/types and masked dataset IDs.
5. Reconcile observed node trace with T083-E required branches before doing workflow changes.

