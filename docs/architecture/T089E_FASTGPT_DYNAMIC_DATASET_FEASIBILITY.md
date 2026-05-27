# T089-E FastGPT Dynamic Dataset Feasibility

Date: 2026-05-21

Scope: short feasibility record for FastGPT dynamic dataset selection and the temporary isolation decision. This document does not modify `customer-agent-refactor-v3` code, database rows, `.env`, Docker, FastGPT workflow, prompts, datasets, collections, or data. It does not call FastGPT write APIs and does not store raw retrieved chunks.

## 1. 验证时间

| item | value |
| --- | --- |
| record date | 2026-05-21 |
| evidence source | user-provided FastGPT KB Search screenshots, T089-A, T089-D |
| console write performed by this task | none |
| synthetic request executed by this task | none |
| PDD message sent | none |
| raw chunks saved | none |

## 2. FastGPT KB Search 是否支持变量选择知识库

Current conclusion: **未找到 / 未证明支持**.

Observed evidence:

| observation | result |
| --- | --- |
| KB Search "选择知识库" mode | shows `手动选择` |
| selected knowledge bases | two shop knowledge bases are selected: `美肌萌主驿站`, `佳琪如梦` |
| user question input | variable-bound to `流程开始 > 用户问题` |
| global variables shown | 使用者 ID, 应用 ID, 当前对话 ID, AI 回复的 ID, 当前时间 |
| `datasetId` in visible variables | not observed |
| request-body `datasetId` binding in KB Search | not observed |
| custom workflow input `datasetId` | not observed |

Interpretation:

- The user question field supports variables.
- The knowledge base selector is currently manual / fixed.
- The screenshots do not show a way to bind "选择知识库" to runtime `datasetId`.
- The visible global variables do not include `datasetId`.

Result:

- Treat FastGPT KB Search dynamic dataset selection as **not available in current visible configuration**.
- Do not assume hidden support unless FastGPT console or documentation proves that "选择知识库" can switch to variable binding.

## 3. datasetId 动态绑定验证结果

Required validation:

| test | pass condition |
| --- | --- |
| dataset A + "为什么还没到" | trace selected dataset == dataset A |
| dataset B + "为什么还没到" | trace selected dataset == dataset B |
| A/B comparison | selected datasets are different |

Actual result:

| item | result |
| --- | --- |
| runtime sends `datasetId` | yes, proven by refactor-v3 code audit |
| KB Search consumes `datasetId` | not proven |
| two-dataset `detail=true` trace | not available |
| selected dataset changes by request | not proven |
| current fixed multi-knowledge selection risk | present |

Verdict: **failed / blocked for方案 A**.

Reason:

- A runtime payload field is not enough. The KB Search node itself must consume it.
- Current visible KB Search config uses manual knowledge selection.
- The current manual selection includes two shop knowledge bases, creating cross-shop recall risk.

## 4. 如果失败，临时隔离方案建议

Recommended immediate containment:

1. **Do not run multi-shop production traffic through a workflow that manually selects multiple shop knowledge bases.**
2. Use only one shop's knowledge base in any active workflow that handles that shop.
3. If multiple shops must be served before dynamic dataset support is proven, use one of the isolation options below.

Temporary isolation options:

| option | recommendation | notes |
| --- | --- | --- |
| A. One workflow/app/API key per shop | preferred short-term isolation | Each app manually selects only that shop's dataset. Requires runtime/deployment strategy to route each shop to the correct app/key. |
| B. External retrieval gateway | preferred long-term if FastGPT lacks dynamic dataset | Gateway filters by shop_id/domain, then passes controlled context to FastGPT. More engineering work. |
| C. Upgrade/adjust FastGPT for variable dataset | best if supported by platform | Must prove KB Search can bind request `datasetId`. |
| D. Single-shop only on current workflow | safest immediate fallback | Current workflow can be used only when the selected knowledge base belongs to the single active shop. |

Not recommended:

- Keeping both `美肌萌主驿站` and `佳琪如梦` selected in the same production KB Search node for multi-shop traffic.
- Relying on final answer quality to infer tenant isolation.
- Adding SOP knowledge for multiple shops before isolation is proven.

## 5. 当前是否允许多店铺共用 workflow

Decision: **not allowed with current visible configuration**.

Reason:

- KB Search appears to use fixed manual knowledge selection.
- The same node currently includes knowledge bases for more than one shop.
- Runtime `datasetId` is not visible in KB Search variable selection.
- No trace proves selected dataset differs by request.

Allowed only after:

1. "选择知识库" supports variable binding or an equivalent tenant-safe selector.
2. `detail=true` trace proves selected dataset follows runtime `datasetId`.
3. Cross-shop recall test passes.

## 6. 当前是否允许继续方案 A

Decision: **pause方案 A implementation**.

Allowed next work:

- Continue evidence collection.
- Test a copied workflow or test app if available.
- Ask FastGPT/GPT whether KB Search can bind request-body `datasetId`.
- If supported, run two-dataset trace.

Not allowed:

- Multi-shop SOP import.
- API sync implementation.
- Domain collection routing implementation.
- Treating current manual multi-knowledge config as production-safe.

## 7. 下一步建议

Recommended next actions:

1. In FastGPT console, open the `手动选择` dropdown in KB Search and confirm whether it has `变量选择` or equivalent.
2. If variable selection exists, try binding it to a workflow input named `datasetId` in a copied workflow.
3. If request-body fields cannot be mapped into workflow variables, ask FastGPT support/GPT whether `/chat/completions` payload fields can be referenced by workflow nodes.
4. If dynamic dataset binding is impossible, choose temporary isolation:
   - short term: one workflow/app/API key per shop, or single-shop-only workflow usage;
   - long term: external retrieval gateway or retrieval outside FastGPT.
5. Defer collection filter validation until shop-level dataset isolation is solved.

Final current decision:

```text
datasetId variable binding feasible: not proven / currently not found
continue Option A: no
multi-shop shared workflow: no
recommended temporary isolation: one shop per workflow/app/API key, or single-shop-only usage until dynamic dataset is proven
```

