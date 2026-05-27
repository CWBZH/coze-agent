# T088-D FastGPT Dataset Filter And Knowledge Import Inventory

Date: 2026-05-20

Scope: read-only inventory for FastGPT `datasetId` / filter semantics, `chatId` isolation, product knowledge export, Ollama bge-m3 embedding, and future merchant SOP synchronization inputs. This report does not modify code, database rows, `.env`, Docker, FastGPT workflow, prompts, datasets, collections, or data.

## 1. 调查范围

Read-only sources checked:

| Area | Files / source |
| --- | --- |
| FastGPT architecture reports | `docs/architecture/T088A_FASTGPT_RUNTIME_INVENTORY.md`, `T088B_FASTGPT_AGENT_WORKFLOW_BINDING_AUDIT.md`, `T088C_CUSTOMER_AGENT_COZE_FASTGPT_TRACE.md` |
| Business policy docs | `docs/acceptance/T083E_WORKFLOW_KB_POLICY_DECISIONS.md`, `T083F_KNOWLEDGE_BASE_SUPPLEMENT_PLAN.md` |
| FastGPT request code | `Message/handlers/fastgpt_handler.py`, `Message/core/pipeline.py` |
| Data model / DB access | `database/models.py`, `database/db_manager.py` |
| Product export | `Knowledge/csv_exporter.py`, current local SQLite schema and counts |
| Coze proxy / tools | `E:\develop\customer-agent-coze\ollama_proxy.py`, `projects/src/tools/knowledge_tool.py`, `projects/src/tools/product_tool.py` |
| Coze deployment docs | `projects/FASTGPT_DEPLOY.md`, `docs/fastgpt-ollama-embedding-fix.md` |

## 2. 已确认业务事实

The following facts are accepted as business-side confirmation for this report:

1. The current FastGPT API key is bound to the screenshot workflow.
2. Each shop has one `datasetId` corresponding to one independent FastGPT dataset.
3. refactor-v3 sends `datasetId` to FastGPT; the workflow uses it as the shop knowledge isolation selector.
4. `chatId` combines shop, buyer, and local session information for conversation isolation.
5. Current FastGPT datasets contain only per-shop product knowledge exports.
6. Logistics, after-sales, promotion, red-line escalation, and sensitive-user SOP are not yet systematically imported into each shop dataset.
7. Current embedding/indexing uses local Ollama bge-m3, supported by `customer-agent-coze/ollama_proxy.py`.
8. Current knowledge import and embedding/indexing are manual FastGPT console operations. Merchants cannot directly operate the console.

Terminology clarification:

- `FastGPT Agent API` refers to the Docker-hosted FastGPT low-code app/workflow API on port 3000.
- `customer-agent-coze/projects/src/main.py` on port 8000 is a separate local `/ask` FastAPI service and is not the FastGPT Agent API.
- The `datasetId`, `chatId`, and workflow filter semantics described below belong to the Docker FastGPT workflow path.

## 3. datasetId / filter 传递链

### Local source

`shops.fastgpt_dataset_id` is defined in the local SQLite model:

| Table | Field | Purpose |
| --- | --- | --- |
| `shops` | `fastgpt_dataset_id` | Per-shop FastGPT dataset ID used by the auto-reply path |

Current local DB read-only summary:

| shop_id_masked | dataset_id_masked | product_count | knowledge_status |
| --- | --- | ---: | --- |
| `3234***3738` | `6a08***6dcd` | 36 | 36 `synced` |
| `565***617` | `6a08***77b4` | 46 | 39 `synced`, 7 `edited` |

### Pipeline validation

`MessagePipeline.process()` performs this sequence:

1. Resolve PDD shop by `channel_name=pinduoduo` and `shop_platform_id`.
2. Read `shop["fastgpt_dataset_id"]`.
3. Strip and validate the value.
4. If missing, skip FastGPT and transfer to human with reason `missing_fastgpt_dataset_id`.
5. If present, pass it to `FastGPTHandler.call()` as `dataset_id`.

Missing dataset behavior:

- FastGPT is not called.
- Session is set to `pending_human`.
- Transfer-human notification is triggered.
- Trace action is `missing_fastgpt_dataset_id`.

### FastGPT payload

`FastGPTHandler.call()` sends `dataset_id` as request field `datasetId`.

Redacted request shape:

```json
{
  "model": "doubao-seed-2-0-lite-260215",
  "messages": [
    {
      "role": "system",
      "content": "<session system context redacted>"
    },
    {
      "role": "user",
      "content": "<buyer message redacted>"
    }
  ],
  "datasetId": "6a08***6dcd",
  "chatId": "3234***3738_<buyer_id_redacted>_<session_uuid>",
  "temperature": 0.7,
  "max_tokens": 120,
  "stream": false
}
```

Important implementation detail:

- The current Python request body does not contain a separate field named `filter`.
- The only explicit shop knowledge selector in local code is `datasetId`.
- Therefore, current "filter" behavior is a FastGPT workflow / Knowledge Base Search node semantic, not a separate refactor-v3 payload field.

Current isolation level:

| Isolation target | Current mechanism | Confirmed? |
| --- | --- | --- |
| Shop dataset | `datasetId` from `shops.fastgpt_dataset_id` | Yes, business-confirmed |
| Other shops' datasets | FastGPT workflow uses request `datasetId` as selector | Yes, business-confirmed |
| Collection inside a dataset | No explicit collection filter in local payload | Not confirmed |
| Metadata-level document filter | No explicit metadata filter in local payload | Not implemented in refactor-v3 |

## 4. chatId 组合逻辑

`MessagePipeline` builds:

```text
chat_id = f"{shop_platform_id}_{buyer_id}_{session_id}"
```

Field meaning:

| Component | Source | Isolation effect |
| --- | --- | --- |
| `shop_platform_id` | PDD shop ID from incoming message / resolved shop | Prevents cross-shop collision |
| `buyer_id` | PDD buyer / customer UID | Prevents cross-buyer collision within a shop |
| `session_id` | Local UUID in `conversations.session_id` | Separates local conversation lifecycle |

Conversation creation:

- `DatabaseManager.get_or_create_conversation(shop_db_id, buyer_id, user_id)` reuses the latest `active` or `pending_human` conversation for the same local shop DB ID and buyer.
- If no active/pending conversation exists, it creates a new UUID `session_id`.

Implications:

1. `chatId` should not collide across shops because `shop_platform_id` is included.
2. `chatId` should not collide across buyers because `buyer_id` is included.
3. `chatId` changes when the local conversation is closed and a new `session_id` is created.
4. FastGPT conversation history is scoped to the generated `chatId` under the API-key-selected app.
5. The current norm should be documented and kept stable: `{shop_platform_id}_{buyer_id}_{session_uuid}`.

Potential edge cases:

- If PDD sends an empty or inconsistent `buyer_id`, pipeline validation prevents normal processing.
- If a conversation remains `pending_human`, the same `session_id` may continue to be reused and automatic replies may be skipped depending on human-lock state.
- `user_id` is stored in the local conversation but is not part of the current `chatId`.

## 5. workflow 使用 datasetId/filter 的方式

Business-confirmed current state:

- The current API key is bound to the screenshot workflow.
- The workflow uses the incoming `datasetId` / filter semantics to isolate per-shop knowledge.
- Each shop has one dataset; the request chooses the shop dataset.

Still recommended console checks:

| FastGPT console field | Why it matters |
| --- | --- |
| Knowledge Base Search node dataset setting | Proves the node uses an incoming variable instead of a fixed dataset |
| Variable name / expression | Confirms whether the node consumes request `datasetId` directly or via a workflow variable |
| Collection filter support | Determines whether logistics / after-sales / promotion can share one dataset safely |
| Fixed dataset fallback | Ensures a misconfigured node cannot ignore the runtime selector |
| Query rewrite setting | Affects whether buyer wording is normalized before retrieval |
| Rerank setting | Affects recall quality and latency |
| Similarity / score threshold | Affects hallucination vs missing-knowledge behavior |
| Reference token / context limit | Affects how much product/SOP text reaches the chat node |
| Debug trace / detail result | Confirms actual node execution and selected dataset during a synthetic request |

Current architecture interpretation:

- `datasetId` is the shop-level isolation selector.
- There is no local collection-level filter yet.
- If workflow cannot filter by collection, future SOP import should use either separate datasets by domain or strict collection naming plus prompt/query discipline.

## 6. 当前产品知识导出链

Local product knowledge source:

| Table | Key fields |
| --- | --- |
| `product_knowledge` | `shop_id`, `goods_id`, `goods_name`, `price`, `price_min`, `price_max`, `sold_quantity`, `thumb_url`, `specifications`, `raw_detail_json`, `knowledge_status` |
| `shops` | `shop_id`, `shop_name`, `fastgpt_dataset_id` |

Current exporter:

- File: `Knowledge/csv_exporter.py`
- Function: `export_fastgpt_csv(db_manager, shop_db_id, output_path=None)`
- Default output path: `settings.ensure_export_dir() / fastgpt_export_YYYYMMDD_HHMMSS.csv`
- Encoding: UTF-8 with BOM (`utf-8-sig`)
- Source rows: all `ProductKnowledge` rows for a shop.

Current exporter fieldnames:

```text
doc_id
shop_platform_id
shop_db_id
shop_name
goods_id
goods_name
price
sold_quantity
specifications
category
sku_options
sku_summary
effect
usage_method
usage_duration
suitable_age
skin_type
fragrance
ingredients
shelf_life
warnings
manual_notes
fastgpt_question
fastgpt_answer
content
metadata_json
```

The rendered `content` includes product name, product ID, price, and manual attributes such as category, SKU, effect, usage method, suitable age, skin type, ingredients, shelf life, warnings, and manual notes when available.

Read-only DB sample showed these manual attribute keys are present in current data:

```text
category, sku_options, sku_summary, effect, usage_method, usage_duration,
suitable_age, skin_type, fragrance, ingredients, shelf_life, warnings
```

Important export side effect:

- The exporter marks `pending` products as `synced` after writing the file.
- Future automation should decide whether export should remain state-mutating or split into read-only generate + explicit mark-synced steps.

Historical file note:

- Existing local file `temp/fastgpt_export_20260516_160927.csv` has legacy header `id,goods_id,goods_name,content`.
- This differs from the current exporter code and should not be treated as the final target format without checking which file was actually imported into FastGPT.

Missing from current export:

- Logistics policy.
- After-sales evidence collection SOP.
- Promotion / bargaining policy.
- High-risk complaint / redline escalation SOP.
- Sensitive-user / health wording.
- Version fields.
- Content hash fields.
- FastGPT collection ID mapping.
- Import/sync status table.

## 7. 当前 FastGPT collection 结构

From T088-A read-only FastGPT metadata:

| shop_id_masked | dataset_id_masked | collection structure |
| --- | --- | --- |
| `3234***3738` | `6a08***6dcd` | one CSV file collection |
| `565***617` | `6a08***77b4` | one CSV file collection |

Collection naming observed in T088-A:

- `fastgpt_export_20260516_192609.csv`
- `fastgpt_export_20260516_231946.csv`

Current structural limitation:

- The dataset has product knowledge but no separate business-domain collections.
- It is not currently possible from local code to tell whether the workflow can restrict retrieval to collection subsets.
- There is no local mapping table from shop/product export version to FastGPT dataset/collection/data IDs.

## 8. ollama_proxy embedding/indexing 链路

`customer-agent-coze/ollama_proxy.py` supports:

| Incoming path | Routing |
| --- | --- |
| `/v1/embeddings` | forwarded to Ollama `/v1/embeddings` |
| `/embeddings` | forwarded to Ollama `/v1/embeddings` |
| `/` without `messages` in JSON body | forwarded to Ollama `/v1/embeddings` |
| `/v1/chat/completions` | forwarded to Doubao-compatible `/chat/completions` |
| `/chat/completions` | forwarded to Doubao-compatible `/chat/completions` |
| `/` with `messages` in JSON body | forwarded to Doubao-compatible `/chat/completions` |

Embedding compatibility behavior:

- All incoming methods are normalized to `POST`.
- FastGPT root-path embedding requests can be rewritten to Ollama `/v1/embeddings`.
- The proxy forwards the JSON body unchanged.
- The embedding model name is not rewritten by the proxy; FastGPT provider config must send the desired model name, currently bge-m3 by observed dataset metadata.
- Batch behavior is pass-through; support depends on Ollama's OpenAI-compatible embedding endpoint and the model.

Failure behavior:

| Failure type | Proxy behavior |
| --- | --- |
| Upstream HTTP error | Returns upstream status and body to caller |
| Other exception | Returns HTTP 502 with JSON error |
| Unknown path | Returns HTTP 404 |

Logging:

- Proxy logs method, path, target class, and status.
- It does not log request body, authorization header, token, or embedding input content.

Chat vs embedding through proxy:

- Embedding/indexing through bge-m3 + Ollama is confirmed by dataset metadata and historical proxy documentation.
- Chat may go through the proxy only if FastGPT chat provider is configured to `host.docker.internal:11435`.
- Current Docker env and static config have mixed signals; final effective chat provider should be confirmed in FastGPT console.

External embedding API switch:

- Prefer changing FastGPT vector provider/model settings rather than changing refactor-v3.
- If the proxy remains in the middle, it could route embedding to an external provider, but that would hide provider semantics and make operations harder to audit.
- Any embedding switch requires re-indexing / re-embedding affected datasets and rerunning synthetic QA.

## 9. 当前控制台人工导入流程

Current manual process, based on local code and docs:

1. In refactor-v3, product knowledge is collected or edited into `product_knowledge`.
2. Export per-shop product knowledge to a FastGPT CSV file.
3. Open FastGPT console.
4. Select the target shop dataset.
5. Import the CSV file into the dataset, likely as a file/CSV collection.
6. FastGPT triggers chunking and embedding/indexing.
7. Wait for training/indexing to complete.
8. Validate retrieval in FastGPT console search/debug.
9. Run synthetic QA from refactor-v3 acceptance scripts.
10. If QA fails, update product knowledge, SOP, workflow, or collection structure and repeat.

Operations not currently automated:

- Creating / updating collections.
- Replacing old collection versions.
- Deleting stale product chunks.
- Recording FastGPT collection/data IDs locally.
- Recording content hash and sync version.
- Checking embedding/indexing completion automatically.
- Running `searchTest` or synthetic QA as a gate.

## 10. 商家不能直接操作的原因

Merchants should not be given direct FastGPT console access in the current architecture because:

1. Console access exposes datasets, app keys, model providers, workflow settings, and potentially cross-shop data.
2. A wrong dataset selection can pollute another shop's knowledge base.
3. Uploading unreviewed SOP can make the AI promise refunds, compensation, discounts, or legal/platform outcomes.
4. Embedding provider and model settings are operational infrastructure, not merchant-facing controls.
5. Current import flow has no built-in review, versioning, rollback, or diff approval.
6. Current FastGPT collection state is not mapped back into local DB, so merchant-side console changes are hard to audit.

Merchant-facing future workflow should be:

```text
merchant edits SOP / product policy in approved UI
 -> internal review / validation
 -> generate versioned knowledge artifact
 -> sync to FastGPT dataset / collection
 -> wait for indexing
 -> run searchTest / synthetic QA
 -> mark version active
```

## 11. 未来 SOP 同步所需最小信息

Minimum source-of-truth fields:

| Field | Purpose |
| --- | --- |
| `sop_item_id` | Stable local identifier |
| `shop_id` / `shop_db_id` | Tenant ownership |
| `category` | logistics / after_sales / promotion / redline / sensitive_user / product_policy |
| `intent_examples` | Retrieval and classifier examples |
| `approved_answer` | Text allowed to reach FastGPT |
| `forbidden_phrases` | Guardrail and review material |
| `should_transfer_human` | no / yes / maybe / after_evidence |
| `requires_evidence` | For after-sales flows |
| `risk_level` | P0 / P1 / P2 |
| `review_status` | draft / pending_review / approved / rejected / archived |
| `version` | Human-visible version |
| `content_hash` | Change detection |
| `effective_at` / `expired_at` | Policy lifecycle |
| `source_owner` | Merchant / ops / product / legal |
| `fastgpt_dataset_id` | Target dataset |
| `fastgpt_collection_id` | Target collection after sync |
| `sync_status` | not_synced / syncing / indexed / failed / rolled_back |
| `last_synced_at` | Operational tracking |
| `last_qa_status` | Synthetic QA gate result |

Recommended knowledge artifact forms:

| Knowledge type | Suggested form |
| --- | --- |
| Product rows | CSV or structured data generated from product DB |
| Store SOP / policies | Markdown document split by business domain |
| High-risk red lines | Markdown or Q&A with explicit forbidden phrases |
| Promotion rules | Structured records plus Markdown wording |
| Sensitive-user rules | Markdown policy entries |
| FAQ examples | Q&A pairs only after approved wording exists |

Recommended collection naming:

```text
{shop_id_masked_or_slug}/product/vYYYYMMDD
{shop_id_masked_or_slug}/logistics_policy/vYYYYMMDD
{shop_id_masked_or_slug}/after_sales/vYYYYMMDD
{shop_id_masked_or_slug}/promotion/vYYYYMMDD
{shop_id_masked_or_slug}/redline/vYYYYMMDD
{shop_id_masked_or_slug}/sensitive_user/vYYYYMMDD
```

Minimum sync lifecycle:

1. Draft SOP in local source-of-truth.
2. Review and approve.
3. Generate Markdown/CSV artifact.
4. Compute content hash.
5. Create or replace target FastGPT collection.
6. Wait for embedding/indexing completion.
7. Run FastGPT search test.
8. Run T083-C style synthetic QA.
9. Mark version active.
10. Keep previous active collection for rollback until new version passes.

Rollback requirement:

- Keep local version metadata and FastGPT collection IDs.
- Do not delete the previous good collection until the new version passes retrieval and QA.
- If collection filtering is unavailable, rollback may require replacing the whole dataset or using domain-specific datasets.

## 12. 当前不建议实现的内容

Do not implement yet:

1. FastGPT `pushData` or collection write automation.
2. Automatic dataset / collection creation.
3. Automatic collection deletion or replacement.
4. Embedding provider migration.
5. Workflow node mutation.
6. Prompt rewrite.
7. Merchant direct FastGPT console access.
8. Runtime payload changes beyond current `datasetId`.
9. Collection-level routing assumptions before FastGPT node config is confirmed.

## 13. 需要你进一步确认的问题

FastGPT console:

1. Knowledge Base Search node uses request `datasetId`: exact variable name and expression.
2. Whether the node can filter by collection.
3. Whether there is any fixed dataset fallback in the workflow.
4. Current search mode, similarity threshold, reference token limit, rerank, and query rewrite settings.
5. Whether chat model calls go through `ollama_proxy.py` or directly to the provider.
6. Whether workflow debug trace can return selected dataset/collection IDs without exposing buyer content.

Business / product:

1. Which SOP categories must be merchant-editable.
2. Which SOP categories require internal approval.
3. Whether merchants may edit price/promotion wording or only product facts.
4. Whether after-sales evidence requests can ask for order screenshots or only order information.
5. Whether logistics general time ranges are allowed per shop.
6. Which policy versions must be retained for audit.

Architecture:

1. Whether to keep one dataset per shop and multiple domain collections.
2. Whether to split high-risk/redline knowledge into a separate dataset.
3. Whether to introduce a local `knowledge_sync_jobs` / `knowledge_versions` table.
4. Whether to run synthetic QA automatically after every sync.
5. Whether to keep Ollama bge-m3 as the default embedding model for the first SOP sync release.
