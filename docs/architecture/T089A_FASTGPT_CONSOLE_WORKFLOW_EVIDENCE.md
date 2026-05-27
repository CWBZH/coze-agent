# T089-A FastGPT Console Workflow Evidence

Date: 2026-05-21

Scope: read-only consolidation of the FastGPT workflow export provided by the user. This report does not modify code, database rows, `.env`, Docker, FastGPT workflow, prompts, datasets, collections, or data.

Source material:

- `D:/问题分类 + 知识库.json`
- Existing architecture and acceptance documents from T088 / T083.

Sensitive handling:

- No real API key, credential header, provider secret, buyer message, or raw retrieved chunk is stored here.
- Dataset IDs are masked.
- Prompt content is summarized only; raw prompt text from the workflow export is not copied into this report.

## 1. 已收到的证据材料清单

| Evidence | Received | Notes |
| --- | --- | --- |
| API key所属 app 截图 | no | Not included in the provided JSON. |
| Workflow canvas export | yes | `问题分类 + 知识库.json` contains nodes and edges. |
| Knowledge Base Search node config | yes | Three `datasetSearchNode` nodes are present. |
| AI Chat node config | yes | Three `chatNode` nodes are present. |
| Classifier node config | yes | One `classifyQuestion` node is present. |
| Human / fixed reply node config | partial | One `answerNode` returns a human-service handoff sentence. |
| `detail=true` synthetic trace | no | No trace summary was provided. |
| Raw retrieved chunks | no | Not needed and should not be stored in this report. |

## 2. API key -> app/workflow 绑定结论

Current conclusion:

| Item | Status | Evidence |
| --- | --- | --- |
| Runtime endpoint | confirmed from prior code audit | refactor-v3 posts to Docker FastGPT `/api/v1/chat/completions`. |
| Runtime explicit app ID | absent from runtime code | refactor-v3 does not send `appId`, `workflowId`, or `agentId`. |
| Provided workflow graph | confirmed | JSON contains a workflow with start, classifier, KB search, chat, and fixed reply nodes. |
| API key belongs to this app | not technically proven by this JSON | Need API key owner page / app settings screenshot. |
| Business confirmation | yes | Earlier T088-C / T088-D notes say the runtime key is business-confirmed to bind this workflow. |
| App ID | partially visible | `chatConfig._id` is present as `6a05***40e`, but this does not prove key ownership. |
| App type | inferred workflow app | Presence of `workflowStart`, `classifyQuestion`, `datasetSearchNode`, and `chatNode` indicates a workflow-style app. |

Decision:

- Treat "API key binds this workflow" as business-confirmed but still missing console evidence.
- Before production SOP rollout, capture the FastGPT app key page with the key value redacted and the app ID/name visible.

## 3. Workflow 节点总览

Workflow nodes from the export:

| Node name | Type | Node ID masked | Role |
| --- | --- | --- | --- |
| 系统配置 | `userGuide` | `userGuide` | App/system configuration helper node. |
| 流程开始 | `workflowStart` | `workflowStartNodeId` | Receives `userChatInput`. |
| 问题分类 | `classifyQuestion` | `fnbI***YMsc` | Classifies the user question into four broad categories. |
| 知识库搜索 | `datasetSearchNode` | `MNMM***WyMU` | Product/general knowledge retrieval. |
| 物流知识库检索 | `datasetSearchNode` | `jfqN***ImZ` | Logistics retrieval. |
| 售后知识库检索 | `datasetSearchNode` | `w1sj***BqV` | After-sales retrieval. |
| AI 对话 | `chatNode` | `7Bdo***IQw` | Product/general final answer generation. |
| AI 对话#2 | `chatNode` | `bH2i***fgw` | Logistics final answer generation. |
| AI 对话#3 | `chatNode` | `dG6a***X4W` | After-sales final answer generation. |
| 指定回复 | `answerNode` | `zoVc***ISz5Z` | Fixed human-service handoff response. |

Observed routing:

```text
流程开始
 -> 问题分类
    -> 商品咨询 -> 知识库搜索 -> AI 对话
    -> 物流查询 -> 物流知识库检索 -> AI 对话#2
    -> 售后问题 -> 售后知识库检索 -> AI 对话#3
    -> 人工服务 -> 指定回复
```

## 4. 分类器节点配置

Classifier node:

| Field | Value |
| --- | --- |
| Node name | 问题分类 |
| Node type | `classifyQuestion` |
| Model | `doubao-seed-2-0-mini-260215` |
| History window | 6 rounds |
| Input | `workflowStartNodeId.userChatInput` |
| Output | classification result |

Configured labels:

| Label | Route | Current T083-E coverage |
| --- | --- | --- |
| 商品咨询 | product/general KB search | Covers part of `product_basic`; also likely absorbs promotion/bargaining today. |
| 物流查询 | logistics KB search | Covers broad logistics, but does not separate policy vs specific order status. |
| 售后问题 | after-sales KB search | Covers broad after-sales, but does not separately identify evidence collection vs redline escalation. |
| 人工服务 | fixed handoff reply | Covers explicit human request only if classifier chooses this label. |

Gap against T083-E:

| T083-E desired branch | Current classifier support |
| --- | --- |
| `product_basic` | partially covered by 商品咨询 |
| `logistics_policy` | not separated; grouped into 物流查询 |
| `logistics_order_status` | not separated; grouped into 物流查询 |
| `promotion_policy` | not separated; likely grouped into 商品咨询 |
| `after_sales_evidence_collection` | not separated; grouped into 售后问题 |
| `human_escalation_redline` | not separated; no dedicated fake/complaint/compensation/media label |
| `sensitive_user_safety` | not present |
| `explicit_human_request` | partially covered by 人工服务 |
| `fallback` | no explicit fallback node observed beyond classification behavior |

## 5. Knowledge Base Search datasetId 使用结论

Observed in all three Knowledge Base Search nodes:

| Node | Dataset selector in export | Dynamic runtime `datasetId` reference | Conclusion |
| --- | --- | --- | --- |
| 知识库搜索 | `value` is empty; `valueDesc` displays dataset `6693***d9b0` | not observed | Static or UI-described dataset is present; dynamic binding not proven. |
| 物流知识库检索 | `value` is empty; `valueDesc` displays dataset `6693***d9b0` | not observed | Same as above. |
| 售后知识库检索 | `value` is empty; `valueDesc` displays dataset `6693***d9b0` | not observed | Same as above. |

Important conclusion:

- refactor-v3 definitely sends `datasetId` in the runtime payload.
- The provided FastGPT workflow export does not show a reference from KB Search `datasets` input to runtime `datasetId`.
- The export instead shows the same masked dataset description on all three KB Search nodes.
- Therefore this JSON does **not** technically confirm that Knowledge Base Search uses the runtime-provided shop `datasetId`.

Risk:

- If the workflow is actually fixed to dataset `6693***d9b0`, runtime per-shop `datasetId` may be ignored by these nodes.
- This would weaken the "one dataset per shop" isolation assumption for the current workflow.

Required follow-up evidence:

1. FastGPT UI screenshot of the KB Search "选择知识库" field.
2. Runtime-shaped synthetic request with `detail=true`, recording selected dataset ID masked.
3. Test two shops with different `datasetId` values and confirm KB Search selects different datasets.

## 6. Collection filter 可用性结论

Observed field:

| Field | Present | Configured value | Meaning |
| --- | --- | --- | --- |
| `collectionFilterMatch` | yes | empty / not configured | The node exposes a collection metadata filter input, but it is not currently used. |

Conclusion:

- The workflow export indicates a filter input exists: `workflow:collection_metadata_filter`.
- It does not prove collection-by-ID routing is available or enabled.
- Current workflow does not configure this filter.
- Current refactor-v3 payload does not send collection filter values.

Decision impact:

- It is too early to rely on collection filter for SOP domain routing.
- Domain collections can be piloted manually, but workflow routing by collection must be proven before production rollout.

## 7. Search 参数记录

All three Knowledge Base Search nodes share the same visible parameters:

| Parameter | Value |
| --- | --- |
| search mode | `mixedRecall` |
| similarity threshold | `0.4` |
| limit / reference token field | `5000` |
| embedding weight | `0.5` |
| rerank | disabled |
| rerank model | empty |
| rerank weight | `0.5`, but inactive because rerank is disabled |
| query extension | disabled |
| query extension model | empty |
| auth team member ID | false |
| collection metadata filter | field exists but empty |

Search risk notes:

- `mixedRecall` is appropriate as a broad first-pass mode, but can retrieve mixed product/SOP text if collections are not separated or filtered.
- Similarity `0.4` is permissive; SOP redline and after-sales evidence should be tested for false positives.
- Rerank is off; if SOP collections are added, retrieval quality should be measured before enabling rerank.
- Query extension is off; intent routing relies primarily on classifier and original user question.

## 8. AI Chat 节点配置摘要

Observed AI Chat settings:

| Node | Model | Temperature | Max response | History | Quote source | Prompt coverage summary |
| --- | --- | ---: | ---: | ---: | --- | --- |
| AI 对话 | `doubao-seed-2-0-mini-260215` | 3 | 1950 | 6 | 知识库搜索 | Product/general客服 prompt. Includes "knowledge-based answer" and "unknown -> transfer human"; lacks explicit redline terms. |
| AI 对话#2 | `doubao-seed-2-0-mini-260215` | unset/default | unset/default | 6 | 物流知识库检索 | After-sales-style empathetic prompt is reused for logistics path; lacks explicit logistics order-status boundary in the summarized evidence. |
| AI 对话#3 | `doubao-seed-2-0-mini-260215` | unset/default | unset/default | 6 | 售后知识库检索 | After-sales-style empathetic prompt; asks to use retrieved policies, but lacks explicit fake/complaint/compensation redline terms in the summarized evidence. |

Other visible settings:

- `aiChatQuoteRole=system`
- `isResponseAnswerText=true`
- vision input enabled
- reasoning enabled
- file input references workflow start user files where applicable

Prompt coverage against T083-E:

| Boundary | Current prompt coverage |
| --- | --- |
| Unknown knowledge -> transfer human | present in all summarized prompts |
| Product facts based on knowledge | present |
| Logistics general vs specific order state | not explicitly proven |
| Damaged/missing/wrong evidence request | not explicitly proven |
| Fake product / complaint / 12315 / compensation / media redline | not explicitly present in prompt keyword scan |
| Promotion/private discount no-promise | not explicitly proven |
| Sensitive-user safety | not explicitly proven |

## 9. Synthetic trace 摘要

No `detail=true` synthetic trace was provided in this input package.

Required trace cases remain:

| Synthetic question | Expected branch | Required evidence |
| --- | --- | --- |
| 为什么还没到 | 物流查询 or future `logistics_order_status` | selected dataset ID masked, retrieved domain, final boundary answer summary |
| 收到破损了 | 售后问题 or future `after_sales_evidence_collection` | evidence-request answer summary, no refund/reissue promise |
| 少发了怎么办 | 售后问题 or future `after_sales_evidence_collection` | package/item evidence request summary |
| 你们是假货吧 | future `human_escalation_redline` | direct human/fixed reply or redline branch |
| 能不能便宜点 | 商品咨询 or future `promotion_policy` | page/platform price boundary summary |

Trace storage rule:

- Store only branch name, node name, masked dataset/collection ID, and final answer summary.
- Do not store raw retrieved chunks or full model answer.

## 10. 当前 workflow 与 T083-E 策略差距

| Area | Current workflow evidence | Gap |
| --- | --- | --- |
| Intent taxonomy | Four broad labels: 商品咨询 / 物流查询 / 售后问题 / 人工服务 | T083-E needs finer branches for logistics order status, promotion, after-sales evidence, redline, and sensitive-user safety. |
| Dataset isolation | Export shows fixed-looking dataset description `6693***d9b0`; no dynamic variable reference observed | Runtime `datasetId` usage by KB Search is not proven. |
| Collection routing | Filter input exists but is empty | No current collection routing. |
| Logistics | Has dedicated logistics KB search path | Does not explicitly separate general policy from specific order status. |
| After-sales | Has dedicated after-sales KB search path | Does not explicitly separate evidence collection from refund/compensation/redline. |
| Redline escalation | Only broad 人工服务 label and fixed reply | No dedicated fake/complaint/12315/compensation/media branch observed. |
| Sensitive users | Not represented | Pregnancy/children/allergy/medical boundary still missing. |
| Promotion | No dedicated branch | Likely handled by 商品咨询; private-discount boundary not node-proven. |
| Search params | mixedRecall, similarity 0.4, limit 5000, rerank off | Need QA before adding SOP domains. |

## 11. 是否允许进入 SOP 手动导入试点

Recommendation: allow only a **single-dataset manual SOP experiment**, not a multi-shop production SOP pilot yet.

Allowed narrow pilot:

1. Pick one shop / one FastGPT dataset intentionally.
2. Manually add SOP documents for logistics, after-sales evidence, promotion, redline, and sensitive-user boundaries.
3. Do not change runtime code.
4. Do not automate sync.
5. Run searchTest and T083-C synthetic QA.
6. Record whether the current broad classifier can route questions acceptably after SOP import.

Not allowed yet:

- Multi-shop SOP rollout.
- Assuming runtime `datasetId` dynamically changes KB Search selection.
- Assuming collection filter is enabled.
- Automating `pushData` or collection replacement.
- Publishing SOP updates without trace evidence and synthetic QA.

Why:

- The workflow export does not prove dynamic `datasetId`.
- Collection metadata filter exists but is empty.
- Current classifier taxonomy is too coarse for T083-E's policy design.

## 12. 仍需补证据项

High-priority evidence:

1. API key owner page showing this workflow app, with secret value redacted.
2. KB Search node screenshot showing whether `datasets` is fixed, variable-bound, or request-bound.
3. `detail=true` synthetic trace proving selected dataset ID for two different shop `datasetId` values.
4. Collection filter UI screenshot and a trace proving whether collection filtering works.
5. AI Chat node full settings screenshot with prompt redacted to summary level in public docs.
6. SearchTest for product, logistics, after-sales, promotion, redline, and sensitive-user questions after SOP import.

Decision evidence still missing:

- Whether one dataset per shop is technically enforced by workflow.
- Whether domain collections can be reliably targeted.
- Whether redline cases can bypass AI Chat and go directly to fixed/human reply.
- Whether current `temperature=3` on the product/general AI node is intentional.

## 13. 不建议立即实现的内容

Do not implement yet:

1. FastGPT dataset / collection write automation.
2. Runtime endpoint or payload changes.
3. Mandatory `FASTGPT_APP_ID` handling.
4. Workflow or prompt mutation from code.
5. Multi-shop SOP rollout.
6. Collection-filter-dependent routing.
7. Embedding provider switch.
8. customer-agent-coze `/ask` integration into the PDD reply path.

