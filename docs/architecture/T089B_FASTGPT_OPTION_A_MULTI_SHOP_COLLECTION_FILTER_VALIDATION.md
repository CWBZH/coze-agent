# T089-B FastGPT Option A Multi-Shop Collection Filter Validation

Date: 2026-05-21

Scope: validation-plan only. This document does not modify code, database rows,
`.env`, Docker, FastGPT workflow, prompts, datasets, collections, or data. It
does not call any FastGPT write API.

## 1. 方案 A 目标架构

方案 A 的目标是让多店铺客服共用一个 FastGPT workflow，同时通过 runtime 传入的
`datasetId` 完成店铺知识隔离，并由 workflow 内部按业务分支配置 collection
filter。

目标形态：

```text
refactor-v3 runtime
  -> POST FastGPT /chat/completions
  -> payload: datasetId + chatId + messages
  -> one shared FastGPT workflow
  -> classifier branch
  -> branch-specific Knowledge Base Search
  -> runtime datasetId selects current shop dataset
  -> collection filter selects domain collection
  -> AI Chat / fixed reply / human escalation
```

方案 A 定义：

1. 每个店铺一个 FastGPT dataset。
2. 每个 dataset 内包含统一命名的 domain collections：
   - `product_catalog`
   - `logistics_policy`
   - `after_sales_evidence`
   - `promotion_policy`
   - `redline_escalation`
   - `sensitive_user_safety`
3. FastGPT workflow 是通用模板。
4. `refactor-v3` runtime 不传 collection filter。
5. workflow 每个业务分支的 Knowledge Base Search 节点自己配置 collection filter。
6. workflow 使用 runtime payload 的 `datasetId` 选择当前店铺 dataset。
7. 不同店铺使用同一 workflow，但检索不同 dataset 下的同名 domain collections。

## 2. 当前阻塞点

T089-A 已固定的当前证据显示：

| blocker | current evidence | impact |
| --- | --- | --- |
| API key -> workflow 绑定 | 业务确认，但还缺 app/key 截图 | 需要补证据，但不阻止设计验证 |
| dynamic `datasetId` | workflow export 未显示 KB Search 引用 runtime `datasetId` | 方案 A 的第一硬门槛 |
| fixed dataset risk | 三个 KB Search 节点均显示同一 dataset `6693***d9b0` | 若为固定 dataset，多店铺隔离不成立 |
| collection filter | `collectionFilterMatch` 字段存在但为空 | domain collection 路由未被证明 |
| classifier granularity | 只有 商品咨询 / 物流查询 / 售后问题 / 人工服务 | 红线、促销、敏感人群、售后凭证粒度不足 |
| current knowledge shape | 主要是每店铺产品 CSV | SOP 域知识不足 |

因此，本轮不能直接进入多店铺生产试点，也不能开始自动 SOP 同步。必须先验证
FastGPT workflow 是否具备方案 A 所需的两个能力：

1. KB Search 能动态使用 runtime `datasetId`。
2. KB Search 能按 collection domain 过滤。

## 3. 需要验证的 FastGPT 能力

### 3.1 datasetId 动态绑定

需要验证：

- KB Search 节点是否可以读取 runtime payload 中的 `datasetId`。
- KB Search 是否可以避免固定 dataset `6693***d9b0`。
- 同一 workflow 下，用两个不同店铺 datasetId 发 synthetic 请求时，selected dataset 是否不同。
- 如果 selected dataset 不随 runtime `datasetId` 变化，方案 A 暂不成立。

验证方法：

1. 准备两个店铺 dataset：
   - Shop A dataset: masked as `dataset_A`.
   - Shop B dataset: masked as `dataset_B`.
2. 对同一个 synthetic question 分别发送请求：
   - request A: `datasetId=dataset_A`
   - request B: `datasetId=dataset_B`
3. 使用 `detail=true` 或 FastGPT 调试 trace 记录：
   - classifier branch
   - KB Search node name
   - selected datasetId masked
   - selected collection/domain if visible
   - final answer summary
4. 判断：
   - selected dataset A != selected dataset B 才算通过。
   - 两次都选择 `6693***d9b0` 或同一固定 dataset 则失败。

### 3.2 collection filter 可用性

需要验证：

- KB Search 节点是否可以配置 `collectionFilterMatch`。
- collection filter 的匹配对象是什么：
  - collection name
  - collection metadata
  - collection ID
  - tag
  - other FastGPT internal field
- 是否可以让不同业务分支只检索对应 domain collection。

最低验证目标：

| branch | expected collection domain |
| --- | --- |
| 商品咨询 | `product_catalog` |
| 物流查询 | `logistics_policy` |
| 售后问题 | `after_sales_evidence` |
| 假货 / 投诉 / 赔偿 / 媒体曝光 | `redline_escalation` |
| 优惠 / 议价 / 赠品 | `promotion_policy` |
| 孕妇 / 儿童 / 过敏 / 医疗安全 | `sensitive_user_safety` |

如果当前 workflow 分类器没有对应细分 branch，可以先做控制台实验分支或 trace
记录，但不能把结果解释为生产可用。

### 3.3 workflow 分类粒度

方案 A 最终需要更细的分类分支：

- `product_basic`
- `logistics_policy`
- `logistics_order_status`
- `promotion_policy`
- `after_sales_evidence_collection`
- `human_escalation_redline`
- `sensitive_user_safety`
- `explicit_human_request`
- `fallback`

当前四分类 workflow 可以用于能力验证，但不能作为最终方案 A 的业务验收模板。

## 4. domain collection 命名和 metadata 规范

建议 collection 命名：

| domain | collection name pattern |
| --- | --- |
| product catalog | `product_catalog__vYYYYMMDD__hash` |
| logistics policy | `logistics_policy__vYYYYMMDD__hash` |
| after-sales evidence | `after_sales_evidence__vYYYYMMDD__hash` |
| promotion policy | `promotion_policy__vYYYYMMDD__hash` |
| redline escalation | `redline_escalation__vYYYYMMDD__hash` |
| sensitive user safety | `sensitive_user_safety__vYYYYMMDD__hash` |

如果 FastGPT 支持 collection metadata，建议写入以下 metadata：

| metadata key | example | purpose |
| --- | --- | --- |
| `domain` | `logistics_policy` | collection filter target |
| `shop_id` | masked/internal shop identifier | tenant audit only, not public display |
| `version` | `20260521-ab12cd` | version tracking |
| `source_type` | `product_csv` / `sop_markdown` | source distinction |
| `review_status` | `approved` | governance gate |
| `content_hash` | short hash | rollback and diff |

If collection metadata is unavailable, use deterministic collection names and record whether
FastGPT can filter by name or ID. Do not assume metadata filter behavior without trace evidence.

## 5. 最小验证数据

Only use synthetic SOP content and reviewed wording. Do not use real buyer messages or secrets.

Select one test shop first, then optionally repeat with a second shop only for dataset isolation
verification.

Minimal domain content:

| domain | minimal test knowledge |
| --- | --- |
| `product_catalog` | one product with price boundary: page price and checkout price prevail |
| `logistics_policy` | "为什么还没到" no-order-context boundary; actual logistics page prevails |
| `after_sales_evidence` | damaged / missing / wrong item evidence request wording |
| `promotion_policy` | page activity / checkout page prevails; no private discount |
| `redline_escalation` | fake product / complaint / 12315 / compensation / media exposure -> human |
| `sensitive_user_safety` | pregnancy / children / allergy / medical safety -> conservative or human |

The minimal data must not include:

- real key, token, cookie, authorization, or credential text.
- real buyer message.
- real order number.
- refund approval.
- compensation promise.
- private discount promise.
- specific order logistics status.
- authenticity conclusion.
- medical safety guarantee.

## 6. synthetic trace 用例

### 6.1 Single-shop branch and collection validation

| case_id | question | expected branch | expected domain |
| --- | --- | --- | --- |
| OA-001 | 这个多少钱 | product / product_basic | `product_catalog` |
| OA-002 | 为什么还没到 | logistics / logistics_order_status | `logistics_policy` |
| OA-003 | 收到破损了 | after_sales / evidence collection | `after_sales_evidence` |
| OA-004 | 少发了怎么办 | after_sales / evidence collection | `after_sales_evidence` |
| OA-005 | 你们是假货吧 | redline / human escalation | `redline_escalation` |
| OA-006 | 我要12315投诉 | redline / human escalation | `redline_escalation` |
| OA-007 | 能不能便宜点 | promotion | `promotion_policy` |
| OA-008 | 孕妇能用吗 | sensitive user safety | `sensitive_user_safety` |

### 6.2 Two-shop dataset isolation validation

Use the same question against two different datasets:

| case_id | dataset | question | expected result |
| --- | --- | --- | --- |
| OA-101 | dataset A | 为什么还没到 | selected dataset = A, selected domain = `logistics_policy` |
| OA-102 | dataset B | 为什么还没到 | selected dataset = B, selected domain = `logistics_policy` |
| OA-103 | dataset A | 收到破损了 | selected dataset = A, selected domain = `after_sales_evidence` |
| OA-104 | dataset B | 收到破损了 | selected dataset = B, selected domain = `after_sales_evidence` |
| OA-105 | dataset A | 你们是假货吧 | selected dataset = A, selected domain = `redline_escalation` |
| OA-106 | dataset B | 你们是假货吧 | selected dataset = B, selected domain = `redline_escalation` |

### 6.3 detail=true trace record fields

Record only:

- question
- classifier branch
- KB Search node name
- selected datasetId masked
- selected collection or domain
- final answer summary
- verdict

Do not record:

- raw retrieved chunks
- full prompt
- real buyer messages
- API key or credential header
- provider raw response
- full model answer if it contains sensitive or private content

## 7. 通过标准

方案 A 成立必须同时满足：

1. KB Search 使用 runtime `datasetId`，不是固定 dataset。
2. 两个店铺传不同 `datasetId` 时，trace 中 selected dataset 不同。
3. `collectionFilterMatch` 或等价配置可以把不同业务分支限制到对应 domain collection。
4. `product_catalog`、`logistics_policy`、`after_sales_evidence`、`promotion_policy`、`redline_escalation`、`sensitive_user_safety` 不互相混召回。
5. T083-C P0 高风险用例在试点店铺中没有 redline unsafe answer。
6. 不出现跨店铺知识泄漏。
7. 不出现退款、补发、赔偿、私下优惠、具体订单物流状态、真假结论、医疗安全承诺。
8. SearchTest 通过后，T083-C synthetic QA 子集仍通过。
9. Trace 能证明 selected dataset 和 selected domain，而不是只看最终回答猜测。

如果只能证明最终回答改善，但不能证明 dataset/domain 选择，则不能判定方案 A 成立。

## 8. 失败后的 fallback 决策

### 8.1 datasetId 无法动态使用

Decision:

- 不进入多店铺方案 A。
- 不做 SOP 生产导入。
- 先修 FastGPT workflow dataset selector。
- 补齐 detail trace 证明后再重新验证。

Temporary fallback:

- 保留每店铺 dataset 设计。
- 仅允许单 dataset 手动实验。
- 不允许多店铺共用 workflow 上线。

### 8.2 collection filter 不可用

Decision:

- 保留每店铺一个 dataset。
- 暂不做多 collection 路由生产化。
- 不进入自动同步。

Potential fallback options:

| fallback | meaning | risk |
| --- | --- | --- |
| strict domain heading | put clear domain headers inside one collection | retrieval can still mix domains |
| separate domain datasets | one shop has multiple datasets by domain | runtime contract and workflow complexity increase |
| workflow fixed branch text | encode more boundaries in prompt | prompt bloat and lower maintainability |
| manual redline fixed reply | route redline to fixed reply / human | safest for redline, less flexible |

The target remains方案 A, but collection filter must be proven before implementation planning.

### 8.3 workflow 分类太粗

Decision:

- 需要先细化 classifier labels。
- 不要只靠新增知识库解决 redline、售后凭证和敏感人群问题。
- 不进入自动 SOP 同步。

Recommended branch additions:

- `promotion_policy`
- `after_sales_evidence_collection`
- `human_escalation_redline`
- `sensitive_user_safety`
- `logistics_order_status`

### 8.4 search params causing domain noise

Decision:

- Do not tune globally before collecting trace evidence.
- If mixed recall pulls wrong domain content, test stricter collection filter first.
- Only then consider similarity, rerank, or query rewrite changes.

## 9. 是否允许进入 SOP 手动导入试点

Allowed only after minimum evidence is captured:

| evidence | required before pilot |
| --- | --- |
| API key app binding | business-confirmed is acceptable for single-shop pilot; screenshot still required before production |
| dynamic datasetId | must be proven if pilot is framed as方案 A validation |
| collection filter | must be proven or explicitly marked as unproven experiment |
| original product CSV | must remain intact |
| SOP content | must be reviewed and versioned |
| trace storage | must exclude raw chunks and secrets |

Single-shop manual SOP import can proceed only as a controlled experiment. It cannot be used as proof of multi-shop方案 A unless dynamic dataset and collection filter are proven.

## 10. 是否允许后续 API 同步设计

Do not start API sync design until all of these are true:

1. dynamic `datasetId` selection is proven.
2. collection filter behavior is proven.
3. collection naming or metadata standard is accepted.
4. workflow branch taxonomy is approved.
5. at least one single-shop pilot passes P0 QA.
6. rollback model is documented.
7. product/ops approves SOP source-of-truth and review ownership.

If any item is missing, the next task should be evidence collection or workflow configuration review, not API sync implementation.

## 11. 不允许做的事情

Do not do the following in this validation phase:

- Do not modify `customer-agent-refactor-v3` runtime.
- Do not modify Python code.
- Do not modify database rows.
- Do not modify `.env`.
- Do not restart or reconfigure Docker.
- Do not call FastGPT write APIs.
- Do not create/update/delete datasets, collections, or data from scripts.
- Do not modify production workflow or prompt during evidence collection.
- Do not send PDD messages.
- Do not use real buyer messages.
- Do not save raw retrieved chunks.
- Do not output real API key, token, cookie, authorization, or provider secret.
- Do not interpret one-shop final answer improvement as multi-shop方案 A proof.

