# T088-E Project Architecture Discussion Brief

Date: 2026-05-20

Purpose: concise architecture brief for discussion with GPT or another architect. This document summarizes the current confirmed architecture, unresolved decisions, and recommended discussion points. It contains no secrets.

## 1. One-Screen Summary

The project has three major parts:

1. `customer-agent-refactor-v3`: PDD customer-service runtime. It owns WebSocket intake, account lifecycle, message queue, session state, deterministic rules, transfer-human handling, safety fallback, status/health/diagnose, and PDD message sending.
2. Docker FastGPT low-code platform: AI workflow runtime. refactor-v3 calls its Agent/workflow chat API and passes `datasetId`, `chatId`, and messages. The API key is business-confirmed to bind to the screenshot workflow.
3. `customer-agent-coze`: supporting side project. Its important current role is `ollama_proxy.py`, which supports FastGPT embedding/indexing with local Ollama bge-m3. Its `projects/src/main.py` `/ask` service is a separate local FastAPI agent service and is not on the current PDD reply path.

## 2. Current Main Runtime Chain

```text
PDD WebSocket
 -> refactor-v3 PDDChannel
 -> MessageConsumer
 -> MessagePipeline
 -> deterministic keyword/media/human-lock checks
 -> FastGPTHandler
 -> POST http://localhost:3000/api/v1/chat/completions
    payload: messages + datasetId + chatId
 -> Docker FastGPT low-code workflow
 -> Knowledge Base Search using per-shop datasetId/filter
 -> AI response
 -> refactor-v3 AIReplyHandler
 -> SendMessage
 -> PDD buyer
```

## 3. Component Responsibilities

| Component | Responsibility | Should not own |
| --- | --- | --- |
| refactor-v3 runtime | PDD transport, queues, sessions, deterministic rules, safety fallback, transfer-human notification, delivery status, worker health | Business knowledge authoring, workflow node logic, embedding provider config |
| FastGPT workflow | Intent classification, retrieval, response generation, standard business wording | PDD WebSocket, SendMessage, account lifecycle, local DB ownership |
| FastGPT datasets | Per-shop knowledge artifacts | Source-of-truth review process |
| customer-agent-coze `ollama_proxy.py` | Compatibility proxy for FastGPT embedding/chat provider calls | PDD reply orchestration |
| customer-agent-coze `/ask` service | Separate local LangGraph / FastAPI agent service | Current production PDD reply chain |
| Local SQLite | Shops, accounts, product knowledge source rows, conversations, messages, keywords, config | FastGPT workflow config |

## 4. Confirmed Data And Isolation Model

| Item | Current model |
| --- | --- |
| Shop knowledge isolation | One FastGPT dataset per shop |
| Dataset selector | `shops.fastgpt_dataset_id` sent as payload field `datasetId` |
| Workflow binding | FastGPT API key binds to the screenshot workflow |
| Current filter semantics | Workflow uses incoming `datasetId` / filter semantics for per-shop knowledge isolation |
| Collection-level filter | Not confirmed from local code |
| Chat history isolation | `chatId = {shop_platform_id}_{buyer_id}_{session_id}` |
| Current knowledge content | Product CSV only |
| Missing knowledge domains | Logistics, after-sales, promotion, redline escalation, sensitive-user SOP |

## 5. Current Knowledge Import Model

Product knowledge source:

```text
SQLite product_knowledge
 -> Knowledge/csv_exporter.py
 -> per-shop FastGPT CSV
 -> manual FastGPT console upload
 -> embedding/indexing
 -> manual verification / synthetic QA
```

Current exporter supports fields such as:

- goods ID/name,
- price,
- sold quantity,
- specifications,
- category,
- SKU options and summary,
- effect,
- usage method/duration,
- suitable age,
- skin type / audience,
- fragrance,
- ingredients,
- shelf life,
- warnings,
- manual notes,
- rendered `content`,
- `metadata_json`.

Known gap:

- Existing FastGPT datasets are still effectively product-knowledge collections. SOP and policy domains are not systematically imported.

## 6. Embedding / Model Infrastructure

Current embedding:

```text
FastGPT indexing
 -> provider endpoint / proxy config
 -> customer-agent-coze/ollama_proxy.py on 11435
 -> Ollama /v1/embeddings
 -> bge-m3 vectors
```

Confirmed dataset metadata:

- vector model: `bge-m3`
- display name: `ollama bge-m3`

Important decision:

- If moving to external embedding API, change FastGPT vector provider config and re-index affected datasets. Do not treat this as a refactor-v3 runtime change.

## 7. Business Policy Direction

Phase-one accepted policy:

- FastGPT workflow should own intent routing and standard wording.
- Code should stay as safety fallback and deterministic guardrail.
- Damaged/missing/wrong item can first request evidence through workflow, then human reviews evidence.
- Fake product, complaint, 12315, compensation, and media exposure should route to human escalation.
- Logistics may answer general shop policy, but must not claim specific order state without order context.
- Promotion answers must not invent discounts, coupons, gifts, or private price changes.
- Sensitive-user or health questions must avoid deterministic safety claims.

## 8. Main Architecture Decisions To Discuss

### Decision 1: Source Of Truth

Should merchant SOP live in:

1. local SQLite tables managed by refactor-v3 admin UI,
2. Markdown files reviewed by ops/product,
3. FastGPT console directly,
4. a separate knowledge management service?

Current recommendation:

- Use a local reviewed source-of-truth, then sync to FastGPT as derived artifacts.
- Do not make FastGPT console the merchant-facing editing surface.

### Decision 2: Dataset And Collection Layout

Options:

1. one dataset per shop, multiple domain collections,
2. one dataset per shop per domain,
3. shared template dataset plus per-shop override dataset,
4. one global workflow with dynamic dataset routing.

Current recommendation:

- Keep one dataset per shop for tenant isolation.
- Add domain collections if FastGPT Knowledge Base Search supports collection filtering.
- If collection filtering is weak, consider domain-specific datasets or strict document headings.

### Decision 3: Workflow Ownership

Should workflow classification live in:

1. FastGPT classifier nodes,
2. code-level deterministic rules,
3. hybrid: code only for safety and media, FastGPT for business intents?

Current recommendation:

- Hybrid.
- Keep media, missing dataset, send failure, unsafe reply, and infra fallback in code.
- Keep business intent routing in FastGPT workflow.

### Decision 4: SOP Sync Automation

When to automate FastGPT dataset writes:

- Only after source-of-truth model, review workflow, versioning, rollback, and QA gates exist.
- Avoid immediate `pushData` automation without lifecycle metadata.

Minimum sync metadata:

- `sop_item_id`,
- `shop_id`,
- `category`,
- `approved_answer`,
- `forbidden_phrases`,
- `should_transfer_human`,
- `review_status`,
- `version`,
- `content_hash`,
- `fastgpt_dataset_id`,
- `fastgpt_collection_id`,
- `sync_status`,
- `last_qa_status`.

### Decision 5: Embedding Strategy

Options:

1. keep local Ollama bge-m3,
2. switch to external embedding API,
3. support both by environment.

Current recommendation:

- Keep bge-m3 until retrieval quality tests prove a need to switch.
- Any switch requires re-indexing and synthetic QA.

## 9. Open Technical Questions

Need FastGPT console or trace confirmation:

1. Which Knowledge Base Search node consumes `datasetId`?
2. Is `datasetId` consumed directly from request body or through a workflow variable?
3. Can the workflow filter by collection?
4. Are there fixed datasets configured as fallback?
5. What are similarity threshold, rerank, query rewrite, and reference-token settings?
6. Does chat generation go through `ollama_proxy.py` or directly to the provider?
7. Can workflow debug trace expose selected dataset/collection IDs without exposing user content?

## 10. Suggested GPT Discussion Prompt

Use this prompt for architecture discussion:

```text
We have a PDD customer-service system.

Current architecture:
- refactor-v3 owns PDD WebSocket intake, queueing, session state, deterministic safety rules, transfer-human notification, worker health/status/diagnose, and SendMessage.
- refactor-v3 calls Docker FastGPT low-code workflow API: POST /api/v1/chat/completions.
- The request includes messages, datasetId, and chatId.
- The FastGPT API key is bound to the active workflow.
- Each shop has one FastGPT dataset. datasetId isolates shop knowledge.
- chatId is {shop_platform_id}_{buyer_id}_{session_id}.
- Current datasets only contain product CSV knowledge.
- Logistics, after-sales, promotion, redline escalation, and sensitive-user SOP are not yet systematically imported.
- Embedding is local Ollama bge-m3 through customer-agent-coze/ollama_proxy.
- customer-agent-coze /ask service is not in the current PDD reply path.

We need to decide the next architecture for merchant SOP, knowledge versioning, FastGPT dataset/collection layout, workflow ownership, and future sync automation.

Please discuss:
1. Where should merchant SOP source-of-truth live?
2. Should we keep one dataset per shop and add domain collections, or split datasets by domain?
3. What should remain deterministic in code vs handled by FastGPT workflow?
4. What metadata is needed before automating FastGPT collection sync?
5. How should QA gates work before a new knowledge version becomes active?
6. Should embedding remain Ollama bge-m3 for now or be moved to an external API later?
```

## 11. Not Recommended Immediately

Do not immediately implement:

1. FastGPT write automation.
2. Workflow prompt/node changes without node export.
3. Embedding provider migration.
4. Merchant direct FastGPT console access.
5. Collection-level routing assumptions before console proof.
6. Direct refactor-v3 integration with customer-agent-coze `/ask`.
