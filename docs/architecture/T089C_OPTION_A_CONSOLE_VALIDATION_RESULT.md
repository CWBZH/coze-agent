# T089-C Option A Console Validation Result

Validation time: 2026-05-21 01:33:17 +08:00

Scope: record of the minimum FastGPT console validation status for Option A. This
document does not modify `customer-agent-refactor-v3` code, database rows, `.env`,
Docker, FastGPT workflow, prompts, datasets, collections, or data. It does not call
FastGPT write APIs and does not store raw retrieved chunks.

## 1. 验证时间

| item | value |
| --- | --- |
| validation record time | 2026-05-21 01:33:17 +08:00 |
| execution type | evidence record / console validation status |
| write operations performed by this task | none |
| PDD messages sent | none |
| real buyer messages used | none |
| raw retrieved chunks stored | none |

## 2. 验证环境

| item | value |
| --- | --- |
| project | `customer-agent-refactor-v3` |
| FastGPT role | Docker-hosted low-code workflow / app chat endpoint |
| runtime request shape | `datasetId` + `chatId` + `messages` |
| workflow evidence source | T089-A workflow JSON export |
| API key binding evidence | business-confirmed, but app/key screenshot still missing |
| detail trace evidence | not provided / not executed in this record |
| collection filter trace evidence | not provided / not executed in this record |

Sensitive handling:

- API key, token, cookie, authorization, provider secrets, and raw chunks are not recorded.
- Dataset and collection identifiers must remain masked in future trace records.
- Only synthetic questions may be used for future validation.

## 3. datasetId 动态绑定结果

Planned validation:

| request | question | expected evidence |
| --- | --- | --- |
| dataset A | 为什么还没到 | selected datasetId equals dataset A |
| dataset B | 为什么还没到 | selected datasetId equals dataset B |

Actual result in this record:

| check | result | evidence |
| --- | --- | --- |
| two different runtime datasetIds tested | no | No `detail=true` trace was provided for dataset A/B. |
| selected datasetId differs between A and B | not verified | No node-level execution trace available. |
| selected datasetId equals runtime `datasetId` | not verified | T089-A workflow export does not show a runtime `datasetId` reference. |
| fixed dataset avoided | not verified | T089-A shows all three KB Search nodes displaying the same masked dataset `6693***d9b0`. |

Verdict: **not passed / not proven**.

Reason:

- The workflow export proves that `refactor-v3` sends `datasetId`, but does not prove that FastGPT KB Search consumes it.
- The current console export shows a fixed-looking dataset description on all three KB Search nodes.
- Without a `detail=true` trace for two different datasetIds, Option A dataset isolation is not established.

## 4. collection filter 结果

Planned validation:

| question | expected domain |
| --- | --- |
| 这个多少钱 | `product_catalog` |
| 为什么还没到 | `logistics_policy` |
| 收到破损了 | `after_sales_evidence` |
| 少发了怎么办 | `after_sales_evidence` |
| 你们是假货吧 | `redline_escalation` |
| 我要12315投诉 | `redline_escalation` |
| 能不能便宜点 | `promotion_policy` |
| 孕妇能用吗 | `sensitive_user_safety` |

Actual result in this record:

| check | result | evidence |
| --- | --- | --- |
| domain collections confirmed | no | No console collection list / domain metadata trace was provided. |
| `collectionFilterMatch` configured | no | T089-A shows the field exists but is empty. |
| branch-specific collection routing tested | no | No `detail=true` trace for selected collection/domain. |
| cross-domain retrieval excluded | not verified | No selected collection/domain evidence. |
| cross-shop retrieval excluded | not verified | Dynamic datasetId is not proven. |

Verdict: **not passed / not proven**.

Reason:

- The workflow export indicates a collection metadata filter input exists.
- It is currently empty and not configured.
- There is no trace proving collection-by-name, collection-by-ID, metadata, or tag matching.

## 5. 失败项

| failure item | status | impact |
| --- | --- | --- |
| API key -> app/workflow screenshot missing | open | Binding is business-confirmed but not independently evidenced. |
| Dynamic `datasetId` trace missing | blocking | Multi-shop dataset isolation cannot be proven. |
| KB Search shows fixed dataset `6693***d9b0` | blocking risk | Runtime `datasetId` may be ignored by workflow nodes. |
| `collectionFilterMatch` empty | blocking | Domain collection routing cannot be proven. |
| Domain collections not confirmed | blocking | Collection filter cannot be tested yet. |
| Current classifier only has four broad labels | blocking for production | Domain routing for promotion, redline, sensitive users, and evidence collection is insufficient. |
| No `detail=true` synthetic trace | blocking | Cannot verify selected dataset, selected collection, or node path. |

## 6. 是否允许进入 T089-D workflow 分支细化

Decision: **allowed as a design / console-configuration validation task, not as production rollout**.

Rationale:

- Current classifier labels are too coarse for Option A domain collection routing.
- T089-D should focus on proving and designing branch taxonomy, dataset selector, and collection filter configuration.
- T089-D must still avoid production rollout until `datasetId` dynamic binding and collection filter trace pass.

Minimum T089-D entry conditions:

1. Continue using synthetic questions only.
2. Do not send PDD messages.
3. Do not store raw chunks.
4. Document before/after workflow branch configuration.
5. Capture masked `detail=true` trace after any experimental console configuration.

## 7. 是否允许进入 T089-E 单店 SOP 手动导入

Decision: **not allowed as Option A validation yet**.

Limited exception:

- A single-dataset manual SOP experiment may proceed only if it is explicitly framed as a single-shop / single-dataset experiment, not as proof of multi-shop Option A.
- It must not claim dynamic dataset isolation or collection filter routing unless trace evidence proves both.

Not allowed:

- Multi-shop SOP rollout.
- API-based SOP sync.
- Production import across all stores.
- Interpreting final answer improvement as proof of selected dataset/domain behavior.

## 8. 仍禁止做的事情

The following remain prohibited:

- Do not modify `customer-agent-refactor-v3` Python code.
- Do not modify DB rows.
- Do not modify `.env`.
- Do not restart or reconfigure Docker.
- Do not send PDD messages.
- Do not use real buyer messages.
- Do not output API key, token, cookie, authorization, or provider secret.
- Do not save raw retrieved chunks.
- Do not start `pushData` / create / update / delete automation.
- Do not begin multi-shop production SOP import.
- Do not claim Option A is valid until datasetId and collection filter traces pass.

## 9. Next Required Evidence

Before Option A can move forward, collect these masked console artifacts:

1. API key owner page showing app/workflow binding, with secret redacted.
2. KB Search node dataset selector screenshot showing whether it uses a runtime variable.
3. Two-shop `detail=true` traces proving selected dataset differs by runtime `datasetId`.
4. Collection filter configuration screenshot showing match mode: name, metadata, ID, tag, or other.
5. Single-shop `detail=true` traces proving selected domain collection for product, logistics, after-sales, redline, promotion, and sensitive-user questions.
6. Classifier branch evidence after any workflow branch refinement.

Until these are captured, Option A remains a target architecture, not a verified architecture.

