# T088-F FastGPT SOP Sync Decision Evidence Pack

Date: 2026-05-20

Scope: architecture evidence pack for FastGPT SOP / knowledge sync decisions. This report is read-only. It does not modify code, database rows, `.env`, Docker, FastGPT workflow, prompts, datasets, collections, or data.

## 1. Fact / Assumption / Unknown Matrix

| Topic | Status | Evidence | Decision impact |
| --- | --- | --- | --- |
| API key binds workflow | Fact, business-confirmed | T088-C / T088-D clarify that the FastGPT API key selects the Docker FastGPT low-code workflow shown in the console screenshot. Local code does not pass `appId`. | Runtime can continue using the app chat endpoint, but audit still needs console evidence showing the app bound to that key. |
| `datasetId` / filter use | Fact for local payload; business-confirmed for workflow isolation | `MessagePipeline` reads `shops.fastgpt_dataset_id`; `FastGPTHandler` sends payload field `datasetId`. Business side confirms the workflow uses it to isolate per-shop knowledge. | Keep one dataset per shop as the current tenant boundary. |
| Knowledge Base Search dynamic dataset | Assumption with business confirmation, not code-proven | Local code cannot inspect workflow node expressions. T088-D says this must be confirmed in FastGPT console. | Do not automate sync until the exact workflow variable and fallback behavior are captured. |
| Collection filter availability | Unknown | Local payload has no collection filter field. Console node configuration is not yet captured. | Domain collections are preferred, but the design must include a fallback if collection filtering is unavailable. |
| `ollama_proxy` embedding effectiveness | Fact for embedding/indexing path | Dataset metadata shows vector model `bge-m3` / `ollama bge-m3`; `customer-agent-coze/ollama_proxy.py` routes embedding requests to Ollama `/v1/embeddings`. | Keep local bge-m3 for the first SOP sync release unless retrieval QA proves it insufficient. |
| Chat generation provider | Unknown / mixed evidence | `ollama_proxy.py` can route chat to Doubao; dataset metadata shows agent model `doubao-seed-2-0-mini-260215`; current FastGPT console provider binding is not exported. | Confirm AI Chat node provider before changing model, latency budget, or proxy responsibilities. |
| Product CSV current import | Fact | `Knowledge/csv_exporter.py` exports per-shop product CSV; T088-A observed one CSV file collection per shop dataset. | Product knowledge is currently an imported artifact, not a governed source of truth. |

## 2. refactor-v3 -> FastGPT Request Contract

Current runtime contract:

```text
MessagePipeline
 -> FastGPTHandler.call()
 -> POST {FASTGPT_BASE_URL}/v1/chat/completions
```

URL source:

| Field | Source |
| --- | --- |
| `FASTGPT_BASE_URL` | `core/settings.py`, default `http://localhost:3000/api` for local and `http://fastgpt:3000/api` for linux/production |
| `FASTGPT_API_KEY` | Environment / `.env`, with historical DB AppConfig fallback |
| `shops.fastgpt_dataset_id` | Local SQLite `shops` table |

Header shape, redacted:

```http
Content-Type: application/json
Credential header: <redacted FastGPT key when configured>
```

Payload shape, redacted:

```json
{
  "model": "doubao-seed-2-0-lite-260215",
  "messages": [
    {"role": "system", "content": "<system context redacted>"},
    {"role": "user", "content": "<synthetic or buyer message redacted>"}
  ],
  "datasetId": "6a08***6dcd",
  "chatId": "3234***3738_<buyer_id_redacted>_<session_uuid>",
  "temperature": 0.7,
  "max_tokens": 120,
  "stream": false
}
```

Dataset / filter fields:

- The only explicit shop knowledge selector in refactor-v3 is `datasetId`.
- There is no separate local payload field named `filter`.
- Current "filter" semantics are therefore a FastGPT workflow / Knowledge Base Search node behavior, not a refactor-v3 field.
- No local code currently sends collection-level filters or metadata filters.

Response shape expected by `FastGPTHandler`:

```json
{
  "choices": [
    {
      "message": {
        "content": "<reply text>"
      }
    }
  ],
  "usage": {
    "total_tokens": 0
  }
}
```

Error and timeout behavior:

| Condition | Runtime behavior |
| --- | --- |
| HTTP 200 with content | Return success and generated reply. |
| HTTP non-200 | Return failure with `HTTP <status>`; log response length/hash only. |
| Timeout | Retry according to handler policy, then return `timeout`. |
| Empty reply | Treated downstream as unsafe / fallback risk; should not send empty content. |
| Missing `datasetId` | MessagePipeline does not call FastGPT and routes to human fallback. |

Fields the workflow may ignore:

- `model`, `temperature`, and `max_tokens` may be ignored or overridden by the FastGPT workflow's AI Chat node.
- `datasetId` should be consumed by Knowledge Base Search, but the exact node variable must be proven in console.
- `chatId` should control FastGPT conversation memory, but workflow node history settings can affect actual context use.

## 3. chatId Isolation Analysis

Current construction:

```text
chatId = {shop_platform_id}_{buyer_id}_{session_id}
```

| Component | Source | Isolation role |
| --- | --- | --- |
| `shop_platform_id` | PDD shop platform ID | Prevents cross-shop chat history collision. |
| `buyer_id` | Buyer / customer UID from incoming message | Prevents cross-buyer collision within the same shop. |
| `session_id` | Local `conversations.session_id` UUID | Separates local conversation lifecycle and FastGPT history. |

Isolation conclusions:

- Cross-shop isolation is strong if `shop_platform_id` is stable.
- Cross-buyer isolation is strong if `buyer_id` is stable.
- A new local conversation creates a new `session_id`, therefore a new FastGPT `chatId`.
- `pending_human` conversations may keep the same `session_id`; this is intentional for human-lock continuity.
- `user_id` is not part of the current `chatId`. That is acceptable if one PDD shop platform ID maps to one seller account; if multiple seller accounts can share a platform shop ID, this should be revisited.

Recommendation:

- Freeze the current norm as `{shop_platform_id}_{buyer_id}_{session_uuid}` for phase one.
- Add this contract to future runtime / FastGPT integration docs.
- Do not change it during SOP sync work; changing it would reset FastGPT conversation memory boundaries.

## 4. FastGPT Console Evidence Checklist

Required evidence before SOP sync automation:

| Evidence item | Required proof |
| --- | --- |
| API key所属 app | Screenshot or export showing the app bound to the runtime API key, with secret value redacted. |
| Workflow canvas | Full workflow graph screenshot for the active app. |
| Classifier node | Labels, branch conditions, fallback branch, and confidence / match settings. |
| Knowledge Base Search node | Dataset selector expression, variable name, fixed fallback dataset if any. |
| Search parameters | search mode, topK / limit, similarity score, reference token limit, query rewrite, rerank settings. |
| Collection filter | Whether node can restrict by collection; if yes, exact variable or setting. |
| AI Chat node | Prompt, model provider, model name, temperature, max response, history window. |
| Human / fixed reply nodes | Which branches transfer human or return fixed wording. |
| `detail=true` trace | A synthetic request showing selected branch, selected dataset, and retrieval result metadata without sensitive user content. |

Minimum acceptable trace:

```text
synthetic question
 -> classifier branch
 -> Knowledge Base Search node
 -> selected datasetId masked
 -> selected collection masked if available
 -> AI Chat node
 -> final answer
```

## 5. Product Knowledge Export Mapping

SQLite source fields:

| Table | Relevant fields |
| --- | --- |
| `shops` | `id`, `shop_id`, `shop_name`, `fastgpt_dataset_id` |
| `product_knowledge` | `shop_id`, `goods_id`, `goods_name`, `price`, `price_min`, `price_max`, `sold_quantity`, `thumb_url`, `specifications`, `raw_detail_json`, `knowledge_status`, timestamps |
| `customer_service_knowledge` | `shop_id`, `title`, `content`, `tags`, `enabled`, timestamps; not part of current CSV exporter |

CSV export fields:

```text
doc_id, shop_platform_id, shop_db_id, shop_name, goods_id, goods_name,
price, sold_quantity, specifications, category, sku_options, sku_summary,
effect, usage_method, usage_duration, suitable_age, skin_type, fragrance,
ingredients, shelf_life, warnings, manual_notes, fastgpt_question,
fastgpt_answer, content, metadata_json
```

Rendered content:

- Product name and product ID.
- Price / sales summary where present.
- Specifications and manual product attributes.
- Usage, ingredients, shelf life, warnings, and manual notes when present.
- `metadata_json` carries structured identifiers that should ideally be preserved as metadata if the FastGPT import path supports it.

Vector retrieval suitability:

| Field group | Suitability | Notes |
| --- | --- | --- |
| `goods_name`, aliases, specs | High | Useful for product lookup and card-context questions. |
| `usage_method`, `ingredients`, `shelf_life`, `warnings` | High | Useful for direct product questions, but must be reviewed for safety wording. |
| `price`, `sold_quantity` | Medium | Useful only if freshness is controlled; price should defer to page/checkout when uncertain. |
| `metadata_json` | Metadata preferred | Better as filter/display metadata than pure retrieval text. |
| `raw_detail_json` | Not directly suitable | Needs rendering and review before embedding. |

Current missing SOP domains:

- Logistics policy.
- After-sales evidence collection.
- Promotion / discount boundary.
- Redline human escalation.
- Sensitive-user / health-related boundary.
- Store-specific approved wording.

## 6. Current-to-Target Knowledge Layout

Current state:

```text
one shop
 -> one FastGPT dataset
 -> one CSV file collection
 -> product knowledge only
```

Target phase-one layout:

| Collection domain | Source | Reviewer | Per-shop? | Shared template? | Version naming |
| --- | --- | --- | --- | --- | --- |
| `product_catalog` | `product_knowledge` CSV | Ops + merchant | Yes | No | `product/vYYYYMMDD[-hash]` |
| `logistics_policy` | Approved shop SOP | Ops + merchant | Yes | Template plus shop values | `logistics/vYYYYMMDD[-hash]` |
| `after_sales` | Approved SOP wording | Ops + product | Yes | Yes | `after_sales/vYYYYMMDD[-hash]` |
| `promotion_policy` | Shop promotion policy | Ops + merchant | Yes | Template plus shop values | `promotion/vYYYYMMDD[-hash]` |
| `redline_escalation` | Product / legal policy | Product / ops | Mostly shared with shop override | Yes | `redline/vYYYYMMDD[-hash]` |
| `sensitive_user` | Product / safety policy | Product / ops | Mostly shared with product override | Yes | `sensitive_user/vYYYYMMDD[-hash]` |

If FastGPT collection filtering is confirmed:

- Keep one dataset per shop.
- Split the dataset into domain collections.
- Workflow routes intent to the correct collection domain.

If collection filtering is not available:

- Keep one dataset per shop, but use strict headings and domain prefixes.
- Consider domain-specific datasets only for high-risk redline or after-sales branches.
- Do not assume collection-level isolation in QA.

## 7. SOP Source-of-Truth Options

| Option | Strengths | Weaknesses | Fit |
| --- | --- | --- | --- |
| Markdown | Easy review, diff, versioning, copyable to FastGPT | Hard for merchants to edit safely; needs structure conventions | Good for ops-authored phase-one policies. |
| Excel / CSV | Familiar to merchants, batch editable | Weak review semantics; easy to break wording and risk boundaries | Good for structured product/policy rows with validation. |
| SQLite + admin UI | Tenant-aware, validates fields, can drive sync status | Requires product work and UI implementation | Best long-term source of truth for merchant-facing SOP. |
| Independent knowledge service | Strong governance and audit potential | Overkill before phase-one sync proves value | Future option after workflow stabilizes. |
| FastGPT console directly | Immediate manual import | Not merchant-safe; weak versioning / rollback; risk of cross-shop pollution | Ops-only emergency path, not source of truth. |

Recommended path:

1. Short term: reviewed Markdown / CSV artifacts owned by ops and product.
2. Medium term: local SQLite source-of-truth with admin UI and approval workflow.
3. FastGPT dataset remains a derived artifact, not the authoritative editing surface.

## 8. Sync Lifecycle State Machine

Recommended lifecycle:

```text
draft
 -> submitted
 -> reviewed
 -> approved
 -> generated
 -> synced
 -> indexed
 -> search_test_passed
 -> synthetic_qa_passed
 -> published
```

Failure and rollback states:

```text
failed
 -> rollback
 -> published(previous good version)

published
 -> retired
```

State meanings:

| State | Meaning |
| --- | --- |
| `draft` | Merchant or ops edits SOP / knowledge item. |
| `submitted` | Item is ready for review. |
| `reviewed` | Reviewer has checked content and risk boundaries. |
| `approved` | Content is allowed to become a FastGPT artifact. |
| `generated` | Markdown / CSV artifact has been rendered with version and hash. |
| `synced` | Artifact has been sent to the target FastGPT dataset / collection. |
| `indexed` | FastGPT embedding/indexing has completed. |
| `search_test_passed` | Retrieval smoke test passes for expected questions. |
| `synthetic_qa_passed` | T083-C style synthetic QA passes release thresholds. |
| `published` | Version is active for runtime use. |
| `failed` | Sync, indexing, retrieval, or QA failed. |
| `rollback` | Active version is reverted to previous good collection/dataset state. |
| `retired` | Old version is intentionally archived and no longer used. |

## 9. QA Gates

SearchTest gates:

- For each domain collection, at least one representative query must retrieve the intended domain content.
- Cross-shop retrieval must be zero.
- Redline queries must retrieve redline escalation policy, not generic after-sales wording.
- Logistics order-status queries must retrieve the boundary wording that says specific order status cannot be determined without order context.

Synthetic QA gates:

- No P0 redline failure.
- No invented refund, compensation, gift, private discount, or guaranteed shipping / arrival promise.
- After-sales evidence cases must ask for evidence and defer review.
- Sensitive-user questions must avoid deterministic safety or medical claims.
- Replies must stay within runtime response length constraints and remain semantically complete after truncation.

Release thresholds:

| Gate | Suggested threshold |
| --- | --- |
| P0 fail count | 0 |
| Redline unsafe answer | 0 |
| Cross-shop knowledge leakage | 0 |
| Synthetic QA pass or acceptable transfer | 95%+ for P0/P1 cases |
| Unknown / unclear | Must be manually reviewed before publish |

Rollback conditions:

- Any redline answer promises authenticity, liability, legal/platform outcome, or compensation.
- Any QA shows cross-shop retrieval.
- New collection fails indexing.
- Health / latency regresses enough to impact runtime delivery.
- Synthetic QA reveals worse behavior than previous published version.

## 10. Observability Requirements

Minimum fields to carry through runtime, sync, QA, and notification:

| Field | Purpose |
| --- | --- |
| `trace_id` | Correlate buyer message, FastGPT call, send result, and notification. |
| `shop_id` | Tenant scope. |
| `datasetId` | FastGPT dataset selected for the request. |
| `chatId` | FastGPT conversation memory boundary. |
| `session_id` | Local conversation boundary. |
| `workflow_version` | FastGPT workflow version or manually recorded release label. |
| `sop_version` | Source-of-truth SOP version. |
| `collection_version` | FastGPT collection version / naming hash. |
| `final_status` | Runtime result such as sent, transfer, skipped, send failed, delivery unknown. |
| `notification_status` | PushPlus / external transfer-human notification outcome. |

Additional sync observability:

- `content_hash`
- `collection_id_masked`
- `sync_job_id`
- `indexed_at`
- `search_test_status`
- `synthetic_qa_status`
- `rollback_from_version`

## 11. Decisions Needed From Product / Ops / Engineering

Product:

- Which SOP categories merchants can edit directly.
- Which categories require product/legal/ops approval.
- Exact approved wording for logistics, refund, exchange, evidence request, redline escalation, and sensitive-user cases.
- Whether after-sales evidence requests may ask for order screenshot or only order information.

Ops:

- Who reviews and approves each shop SOP.
- How often product CSV and SOP collections are refreshed.
- Whether old FastGPT collections can be retained for rollback.
- Manual console evidence capture process before automation.

Engineering:

- Whether to keep one dataset per shop and add domain collections.
- Whether FastGPT collection filter is reliable enough for workflow routing.
- Whether to add local `knowledge_versions` / `knowledge_sync_jobs` tables.
- Whether bge-m3 remains the default embedding model for phase one.
- Whether SOP sync should be manual, semi-automatic, or fully automatic after QA gates.
- How publish and rollback should be represented in runtime observability.

## 12. Do Not Implement Yet

Do not implement these until evidence and decisions above are closed:

- FastGPT `pushData` or collection write automation.
- Workflow node mutation.
- Runtime endpoint or payload changes.
- Embedding provider switch.
- customer-agent-coze `/ask` integration into the PDD reply path.
- Merchant direct FastGPT console editing.
- Collection-level routing assumptions without console proof.
- Automatic deletion of old FastGPT collections.
- Fully automatic publish without searchTest and synthetic QA gates.

## 13. Minimum Viable Landing Path

Recommended smallest safe path:

1. Capture FastGPT console evidence for active app, workflow, Knowledge Base Search node, and AI Chat node.
2. Keep one dataset per shop and current `datasetId` isolation.
3. Add reviewed SOP artifacts outside code first: logistics, after-sales evidence collection, promotion boundary, redline escalation, and sensitive-user policy.
4. Manually import SOP artifacts as additional per-shop knowledge collections if collection structure is supported.
5. Run searchTest and T083-C style synthetic QA.
6. Only after QA passes, design a local source-of-truth and sync lifecycle.

This path avoids changing runtime behavior while giving enough evidence to decide whether future automation should use domain collections, domain datasets, or a stricter source-of-truth pipeline.
