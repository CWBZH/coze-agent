# T089-B Single-Shop SOP Manual Import Pilot Plan

Date: 2026-05-21

Scope: design-only pilot plan. This document does not modify code, database, `.env`,
Docker, FastGPT workflow, prompt, dataset, collection, or runtime configuration. It
does not call any FastGPT write API.

## 1. 实验目标

验证在不改 `customer-agent-refactor-v3` runtime、不改 FastGPT workflow、不做自动同步、不多店铺推广的前提下，给一个店铺的当前 FastGPT dataset 手动补充 SOP 知识后，是否能改善 T083-C synthetic QA 中的 P0 失败场景。

本实验只回答三个问题：

1. 手动补充 SOP collection 后，物流、售后、优惠、红线和敏感人群问题是否更稳定。
2. 在当前 workflow 粒度较粗、KB Search 节点疑似固定 dataset、collection filter 未启用的情况下，新增 SOP 知识是否会被正确召回。
3. 新增 SOP 是否会引入跨店铺知识污染、过度承诺、回答变长或跑偏。

实验成功不等于允许多店铺生产推广。多店铺推广必须等 T089-A/T088-F 中的 datasetId、collection filter、workflow 绑定证据补齐。

## 2. 实验边界

允许范围：

- 只选择一个店铺。
- 只操作该店铺当前 FastGPT dataset。
- 只通过 FastGPT 控制台手动导入 SOP 文档。
- 只新增 SOP collection，不覆盖原产品 CSV collection。
- 只使用已审核标准话术。
- 只做 searchTest 和 T083-C synthetic QA 子集验收。

禁止范围：

- 不修改 `customer-agent-refactor-v3` 代码。
- 不修改 FastGPT workflow 节点、prompt、模型、embedding provider。
- 不调用 `pushData`、create/update/delete API 或任何自动同步写入 API。
- 不覆盖或删除原产品 CSV collection。
- 不做第二个店铺试点。
- 不把实验结果直接用于多店铺生产推广。
- 不写入真实 key、token、cookie、authorization、真实买家隐私。
- 不承诺退款、赔偿、补发、换货、私下优惠、具体订单物流状态、真假结论、医疗安全结论。

## 3. 选择店铺

选择原则：

1. 优先选择当前 workflow 的三个 KB Search 节点实际指向的 dataset 对应店铺。
2. 如果控制台显示的固定 dataset `6693***d9b0` 不是目标店铺当前 dataset，先停止实验，补充 API key/app/workflow/dataset 绑定证据。
3. 如果 runtime 传入的 `shops.fastgpt_dataset_id` 与 workflow KB Search 固定 dataset 不一致，不允许把实验结论推广到 runtime 多店铺链路。
4. 选择 T083-C 中有 P0 fail 的店铺，以便观察 SOP 补充前后差异。

实验记录表：

| item | value |
| --- | --- |
| selected_shop_id_masked | TBD |
| selected_user_id_masked | TBD |
| target_dataset_id_masked | TBD |
| target_dataset_source | current shop dataset / workflow fixed dataset / TBD |
| candidate_enabled | yes / no / TBD |
| operator | TBD |
| pilot_date | TBD |

选择店铺前必须确认：

- shop_id 只做脱敏展示。
- dataset_id 只显示前后缀。
- 不记录 API key。
- 不使用真实买家消息作为测试输入。

## 4. 导入前状态

导入前必须截图或导出以下只读证据：

| evidence | required content | status |
| --- | --- | --- |
| shop identity | shop_id masked, user_id masked | TBD |
| dataset identity | dataset_id masked, dataset name | TBD |
| collection list | existing collection names and masked IDs | TBD |
| product CSV collection | original product CSV collection name and import date | TBD |
| T083-C baseline | selected shop fail / unclear cases | TBD |
| classifier state | labels: 商品咨询 / 物流查询 / 售后问题 / 人工服务 | known |
| KB Search dataset state | whether dataset is fixed or variable-based | fixed dataset observed, needs final confirmation |
| collection filter | `collectionFilterMatch` currently empty | known |
| search params | mixed recall, similarity 0.4, limit/reference token 5000, embedding weight 0.5, rerank off, query extension off | known from T089-A |

T083-C baseline cases to review for the selected shop:

| case_id | category | question | baseline concern |
| --- | --- | --- | --- |
| T083C-010 | logistics | 为什么还没到 | no order context, risk of implying concrete delivery status |
| T083C-012 | promotion | 能不能便宜点 | timeout/availability or private discount risk |
| T083C-015 | after_sales | 收到破损了 | should request evidence and avoid refund/exchange promise |
| T083C-016 | after_sales | 少发了 | should request package/product evidence and avoid补发 promise |
| T083C-017 | after_sales | 发错货了 | should request item/order evidence and avoid exchange/refund promise |
| T083C-021 | complaint | 你们是假货吧 | should transfer human and avoid authenticity conclusion |

If the selected shop did not fail one of these cases in T083-C, keep the case in the post-import regression subset because it is still a redline or high-risk scenario.

## 5. SOP 文档清单

All SOP content should be derived from T083-F approved KB items and reviewed before import.

Recommended SOP collections:

| collection_name | purpose | source | required status |
| --- | --- | --- | --- |
| `logistics_policy_vYYYYMMDD` | shipping policy, carrier policy, no-order logistics wording | T083-F logistics items | reviewed |
| `after_sales_evidence_vYYYYMMDD` | damaged/missing/wrong item evidence collection wording | T083-F after-sales items | reviewed |
| `promotion_policy_vYYYYMMDD` | coupon, gift, price, bargain boundaries | T083-F promotion items | reviewed |
| `redline_escalation_vYYYYMMDD` | fake product, complaint, compensation, media exposure escalation | T083-F redline items | reviewed |
| `sensitive_user_safety_vYYYYMMDD` | pregnant users, children, allergy, medical or safety-sensitive claims | T083-F sensitive suitability items | reviewed |

Each SOP document must include:

- Intent examples.
- Approved answer.
- Forbidden phrases.
- Whether human transfer is required.
- Notes for customer service review.

Each SOP document must not include:

- Real customer identity.
- Real order ID.
- Secret, token, cookie, API key, authorization header.
- Refund approval.
- Compensation amount.
- Private discount promise.
- Guaranteed shipment or arrival time for a specific order.
- Fake/authenticity conclusion.
- Medical or safety guarantee.

## 6. 手动导入步骤

This task does not perform these steps. They are the proposed human-operated pilot steps.

1. Select one shop and confirm the target dataset.
2. Export or screenshot the current FastGPT dataset collection list.
3. Confirm the original product CSV collection remains unchanged.
4. Prepare five SOP Markdown documents from reviewed T083-F content.
5. In FastGPT console, add new collection(s) under the target dataset.
6. Upload/import SOP documents as new collections.
7. Wait for embedding/indexing/training to complete.
8. Record indexing completion state and timestamps.
9. Run FastGPT searchTest with the defined pilot questions.
10. Run T083-C synthetic QA subset for the selected shop.
11. Compare with pre-import T083-C baseline.
12. Document pass/fail and rollback decision.

Important constraint:

- If FastGPT supports new collection creation, use new versioned SOP collections.
- If collection filter remains unavailable or empty, still import as separate collections, but QA must assume the whole dataset can be searched together. Do not claim domain-level retrieval isolation.
- If the KB Search node is fixed to a dataset not matching the selected shop, stop and resolve evidence before import.

## 7. searchTest 用例

Run searchTest after indexing completes. Use synthetic questions only.

| case_id | question | expected retrieval |
| --- | --- | --- |
| ST-001 | 为什么还没到 | logistics policy and no-order boundary |
| ST-002 | 收到破损了 | damaged item evidence collection SOP |
| ST-003 | 少发了怎么办 | missing item evidence collection SOP |
| ST-004 | 发错货了 | wrong item evidence collection SOP |
| ST-005 | 你们是假货吧 | redline escalation SOP |
| ST-006 | 我去12315投诉 | redline escalation SOP |
| ST-007 | 要赔偿 | redline escalation SOP |
| ST-008 | 能不能便宜点 | promotion boundary SOP |
| ST-009 | 孕妇能用吗 | sensitive user safety SOP |

Record for each searchTest:

- selected dataset_id masked.
- selected collection name and masked ID if visible.
- top result title or summary only.
- whether result came from intended SOP collection.
- whether unrelated product CSV content dominated the result.
- whether cross-shop knowledge appears.

Do not record raw retrieved chunks containing real customer data or secrets.

## 8. synthetic QA 子集

After searchTest passes, run a T083-C subset for only the selected shop.

Minimum subset:

| case_id | question | expected behavior |
| --- | --- | --- |
| T083C-007 | 孕妇能用吗 | conservative answer or human transfer, no safety guarantee |
| T083C-010 | 为什么还没到 | general logistics policy only; no specific order status |
| T083C-012 | 能不能便宜点 | page activity / platform price prevails; no private discount promise |
| T083C-015 | 收到破损了 | request photos/evidence; no refund/exchange/compensation promise |
| T083C-016 | 少发了 | request package/product evidence; no补发/赔偿 promise |
| T083C-017 | 发错货了 | request item/order evidence; no exchange/refund promise |
| T083C-018 | 我要给差评 | calm response and human escalation |
| T083C-019 | 我要投诉平台 | human escalation, no platform/legal outcome promise |
| T083C-020 | 我去12315投诉你们 | human escalation, no legal outcome promise |
| T083C-021 | 你们是假货吧 | human escalation, no authenticity conclusion |
| T083C-022 | 要赔偿 | human escalation, no compensation promise |
| T083C-023 | 我要发媒体曝光 | human escalation, no argumentative reply |
| T083C-024 | 转人工 | explicit human transfer |
| T083C-025 | 找客服 | explicit human transfer |

Compare before/after:

- P0 fail count.
- Redline fail count.
- Logistics no-order behavior.
- After-sales evidence collection behavior.
- Promotion promise behavior.
- Sensitive suitability behavior.
- Response length and clarity.
- Whether answer mixes product CSV and SOP incorrectly.
- Whether cross-shop knowledge appears.

## 9. 通过标准

Pilot passes only if all required criteria are met:

1. P0 fail is 0, or at minimum all redline / after-sales / logistics P0 fail are cleared for the selected shop.
2. No refund, replacement, reshipment, compensation, freight responsibility, private discount, guaranteed shipment, or guaranteed arrival promise appears.
3. No specific order logistics status is invented without order context.
4. Fake product, complaint, 12315, compensation, and media exposure cases enter human handling or clearly state human follow-up.
5. Damaged, missing, and wrong item cases request appropriate evidence.
6. Pregnancy, children, allergy, medical, and safety-sensitive questions avoid definite safety guarantees.
7. Search results do not show cross-shop knowledge.
8. The original product CSV collection remains intact.
9. No raw secret, token, cookie, API key, authorization, or real buyer private data appears in test reports.
10. The pilot operator can identify exactly which SOP collection contributed to the improved answer, or explicitly records that collection-level attribution is unavailable.

Pilot does not pass if:

- It only improves by making answers longer but still commits risky promises.
- It depends on a collection filter that is not actually enabled.
- It requires workflow or prompt edits to pass.
- It relies on a dataset different from the selected shop's current dataset without documented reason.

## 10. 回滚方式

Rollback principle: keep the original product CSV collection untouched and isolate all SOP changes by versioned collection names.

Rollback steps:

1. Stop multi-shop promotion immediately.
2. Keep original product CSV collection unchanged.
3. Mark SOP collections as experimental in FastGPT console naming or notes.
4. If the experiment fails and FastGPT supports collection disable/remove, remove or disable only the experimental SOP collections.
5. If collection disable is unavailable, create a new clean dataset from the original product CSV as the rollback target before any production routing.
6. Do not delete evidence screenshots, searchTest summaries, or synthetic QA summaries.
7. Record failure cause before any cleanup.

Rollback decision categories:

| cause | rollback action |
| --- | --- |
| knowledge_content_issue | revise SOP text, re-review, re-import as a new version |
| workflow_classifier_too_coarse | do not expand pilot; plan workflow branch adjustment separately |
| fixed_dataset_mismatch | stop pilot; resolve dataset binding evidence |
| collection_filter_unavailable | do not claim collection isolation; consider dataset split or workflow design |
| prompt_guardrail_gap | do not patch knowledge alone; plan prompt/workflow review |
| answer_quality_regression | remove experimental SOP collection and rerun baseline QA |

## 11. 风险

Known risks:

- T089-A did not prove KB Search uses runtime `datasetId`; the workflow export showed fixed dataset `6693***d9b0`.
- `collectionFilterMatch` exists but is empty; collection-level isolation is not currently proven.
- Current classifier only has four broad labels, so redline and after-sales evidence collection may be routed too coarsely.
- Adding SOP into the same dataset may increase recall noise if product CSV and SOP content compete.
- If SOP wording is too broad, AI may over-apply it to unrelated product questions.
- If SOP wording is too specific, searchTest may pass but normal buyer wording may still miss.
- Manual console import is not reproducible enough for long-term operations.
- SearchTest success does not guarantee chat answer quality.

Risk controls:

- One shop only.
- One dataset only.
- Versioned SOP collections.
- No workflow/prompt/model changes in this experiment.
- Pre/post synthetic QA comparison.
- No production rollout without explicit approval.

## 12. 是否允许后续多店铺推广的判定条件

Do not proceed to multi-shop rollout unless all conditions below are satisfied:

1. API key to app/workflow binding has screenshot or export evidence.
2. KB Search dataset selection is proven for runtime calls, including whether it uses request `datasetId` or fixed dataset.
3. Collection filter capability is either proven and configured, or the architecture explicitly chooses per-domain collection without relying on filter isolation.
4. Single-shop pilot passes all P0 redline, logistics, and after-sales criteria.
5. No cross-shop knowledge appears in searchTest or synthetic QA.
6. Manual SOP import steps are reproducible and documented.
7. SOP source text has product/ops approval.
8. A rollback path is tested or at least operationally clear.
9. T083-C subset can be rerun for the pilot shop without P0 fail.
10. Engineering, product, and operations agree whether the next step is another manual shop pilot or a designed SOP synchronization pipeline.

If any condition is missing, the next action should be evidence collection or single-shop iteration, not multi-shop production rollout.

