# T089-D FastGPT Dataset Isolation Gap Report

Date: 2026-05-21 01:41:18 +08:00

Scope: architecture evidence report based on the FastGPT console screenshots provided by the user. This document does not modify code, database rows, `.env`, Docker, FastGPT workflow, prompts, datasets, collections, or data. It does not call FastGPT write APIs and does not store raw retrieved chunks.

## 1. 背景

当前目标架构原本假设：

```text
refactor-v3 runtime
  -> FastGPT /chat/completions
  -> payload includes datasetId / chatId / messages
  -> FastGPT workflow
  -> KB Search dynamically uses runtime datasetId
  -> each shop searches only its own dataset
```

T089-A / T089-B / T089-C 已指出该假设缺控制台证据。用户随后提供了 FastGPT 控制台 KB Search 节点截图，用于进一步判断当前 workflow 是否支持店铺知识隔离。

## 2. 已收到的控制台证据

| evidence | status | observation |
| --- | --- | --- |
| KB Search node screenshot | received | Node is named "知识库搜索". |
| Knowledge selector area | received | Selector mode displays "手动选择". |
| Selected knowledge bases | received | Two knowledge bases are visibly selected: `美肌萌主驿站`, `佳琪如梦`. |
| User question input | received | Input is variable-bound to `流程开始 > 用户问题`. |
| Global variables panel | received | Includes 使用者 ID, 应用 ID, 当前对话 ID, AI 回复的 ID, 当前时间. |
| Runtime `datasetId` variable | not observed | No visible global variable named `datasetId` or equivalent. |
| Collection filter configuration | not observed | No visible domain collection filter in the screenshots. |
| detail trace | not provided | No selected dataset / selected collection trace available. |

## 3. 当前 KB Search 节点判断

From the screenshots, the KB Search node currently appears to be configured as:

```text
选择知识库 = 手动选择
selected datasets / knowledge bases = 美肌萌主驿站 + 佳琪如梦
用户问题 = 流程开始 > 用户问题
```

Interpretation:

- The user question is dynamic.
- The knowledge base selection is currently manual / fixed.
- The node does not visibly reference runtime `datasetId`.
- The global variable list shown in the screenshot does not expose `datasetId`.
- The current setup appears to search the manually selected knowledge bases rather than a per-request shop dataset.

## 4. datasetId 动态绑定结论

Verdict: **not supported by current visible configuration**.

Reasoning:

1. `refactor-v3` sends `datasetId` in the chat payload, but the FastGPT node UI shown here does not expose that field.
2. KB Search "选择知识库" is set to "手动选择", not variable binding.
3. The selected knowledge bases are fixed in the node.
4. The visible "全局变量" list does not include `datasetId`.
5. No trace proves selected dataset changes when runtime `datasetId` changes.

Therefore, based on current evidence, runtime `datasetId` should be treated as **not consumed by this KB Search node** unless another hidden mechanism or API behavior is proven separately.

## 5. 多店铺隔离风险

Current risk:

```text
Shop A message
  -> runtime sends datasetId A
  -> FastGPT workflow KB Search ignores datasetId
  -> searches fixed knowledge bases: 美肌萌主驿站 + 佳琪如梦

Shop B message
  -> runtime sends datasetId B
  -> FastGPT workflow KB Search ignores datasetId
  -> searches same fixed knowledge bases: 美肌萌主驿站 + 佳琪如梦
```

This means:

- Cross-shop retrieval is possible.
- One shop may answer with another shop's product or policy knowledge.
- The "one shop one dataset" runtime model is not enforced by this workflow node.
- Option A cannot be considered valid in the current configuration.

## 6. collection filter 结论

Verdict: **not proven / not configured**.

The screenshots show:

- selected knowledge bases,
- user question variable binding,
- general search parameters,
- global variables.

They do not show:

- collection domain filter,
- `collectionFilterMatch` configured value,
- metadata filter using `domain=...`,
- selected collection trace.

Therefore, domain collection routing is also not currently proven.

## 7. 对方案 A 的影响

方案 A required:

1. one dataset per shop,
2. shared workflow,
3. runtime `datasetId` selects the shop dataset,
4. workflow branch collection filter selects the domain collection.

Current evidence:

| requirement | current status |
| --- | --- |
| runtime sends `datasetId` | yes, local code does this |
| KB Search consumes `datasetId` | not observed |
| selected dataset changes per request | not proven |
| collection filter routes domain | not observed |
| shared workflow supports multi-shop isolation | not proven |

Conclusion:

- 方案 A is still a target architecture, not a verified architecture.
- In current visible FastGPT configuration,方案 A should be considered blocked.
- Do not proceed to multi-shop SOP import or API sync based on current workflow.

## 8. 可与 GPT 讨论的架构选项

### Option 1: Find a FastGPT-native dynamic dataset selector

Question for GPT / FastGPT expert:

- Does FastGPT KB Search support selecting datasets from request body fields such as `datasetId`?
- Can "选择知识库" switch from "手动选择" to variable binding?
- Can the workflow start node define custom input variables beyond user question?
- Can API payload fields be mapped into workflow variables?

If yes:

- Configure KB Search to use runtime `datasetId`.
- Validate with two-shop `detail=true` trace.
- Then revisit collection filter.

If no:

- Option A cannot be implemented with current FastGPT node behavior.

### Option 2: One workflow per shop

Design:

- Each shop has a dedicated FastGPT app/workflow/API key.
- Each workflow manually selects that shop's dataset.
- Runtime chooses API key/app by shop.

Pros:

- Strong isolation by app/key/workflow.
- Works with manual KB selection.

Cons:

- Operationally heavy for many shops.
- Workflow updates must be replicated per shop.
- More configuration drift.

### Option 3: One shared dataset with strict shop metadata filtering

Design:

- Put all shop knowledge into one dataset.
- Add shop metadata to every collection/chunk.
- KB Search filters by shop metadata.

Pros:

- Single workflow easier to maintain.

Cons:

- Requires proven metadata filter.
- Higher blast radius if filtering fails.
- More dangerous than per-shop dataset isolation.

### Option 4: Use an external knowledge-routing service before FastGPT

Design:

- refactor-v3 or a knowledge gateway selects shop/domain knowledge.
- FastGPT receives only retrieved context or calls a controlled tool/API.

Pros:

- Full control over tenant isolation and domain filters.
- Easier to test deterministically.

Cons:

- More engineering work.
- Moves part of retrieval outside FastGPT low-code workflow.

### Option 5: Keep FastGPT for generation, move retrieval outside FastGPT

Design:

- App handles dataset/domain retrieval.
- FastGPT workflow only performs classification, wording, and generation.

Pros:

- Strong runtime isolation.
- More observable.

Cons:

- Larger architecture change.
- Requires new retrieval service and QA gates.

## 9. 当前建议

Near-term recommendation:

1. Do not proceed with multi-shop方案 A rollout.
2. Do not start SOP API sync.
3. Ask FastGPT / GPT specifically whether KB Search can bind "选择知识库" to request payload `datasetId`.
4. If FastGPT supports it, run a two-shop dynamic dataset trace.
5. If FastGPT does not support it, choose between one workflow per shop or external retrieval.

Safe next experiment:

- A single-shop, single-dataset manual SOP experiment remains possible.
- It must be documented as a single-dataset quality test, not multi-shop isolation proof.

## 10. 仍需补证据

To close this decision, collect:

1. Screenshot of the "选择知识库" dropdown options.
2. Confirmation whether "手动选择" can switch to variable binding.
3. Documentation or support answer for request payload field access in workflow nodes.
4. `detail=true` trace using two different datasetIds.
5. Collection filter configuration screenshot if domain collection routing is still desired.

## 11. 结论

Based on the provided screenshots, current FastGPT KB Search is configured with manually selected knowledge bases and does not visibly consume runtime `datasetId`.

The current workflow should be treated as **not providing reliable per-shop dataset isolation**.

方案 A is blocked until FastGPT proves either:

- KB Search can dynamically bind to runtime `datasetId`, or
- an equivalent tenant-safe dataset/filter mechanism exists and passes trace validation.

