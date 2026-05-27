# T101-D Internal Backend Dry Run Acceptance

Date: 2026-05-21

## Scope

This document links the current internal backend acceptance commands:

- offline synthetic QA for `InternalWorkflowEngine`;
- read-only SQLite smoke for product knowledge repository access;
- no-send dry-run for the internal backend route.

All commands in this document are acceptance and diagnostic commands only. They
must not send PDD messages, start PDD WebSocket runtime, mutate `.env`, mutate
SQLite rows, or require real service credentials.

## Current Internal Backend Capabilities

The internal backend currently has these acceptance-visible capabilities:

- Hard rules in `InternalWorkflowEngine` for redline human transfer, explicit
  human request, after-sales evidence request, logistics boundary reply,
  promotion boundary reply, sensitive-user safety reply, and product-basic
  routing.
- Product knowledge repository access through `ProductKnowledgeRepository`,
  backed by SQLite in the smoke command and by synthetic records in the
  synthetic QA runner.
- Product knowledge retrieval through `ProductKnowledgeRetriever` over loaded
  records.
- SOP fixture loading through the read-only `SOPProvider` path when
  `--sop-file` is supplied.
- SOP-backed domain response through `DomainPolicyResponder` for accepted
  policy domains.
- Deterministic output guardrail through `OutputGuardrail`.
- Report-safe internal result summaries with hashed identifiers, counts,
  versions, actions, risk flags, and guardrail status.
- Offline synthetic QA through
  `scripts/acceptance/internal_engine_synthetic_qa.py`.
- Read-only SQLite smoke through
  `scripts/acceptance/internal_product_repository_smoke.py`.
- No-send internal backend dry-run through
  `scripts/acceptance/internal_backend_dry_run.py`.

## Current Non-Capabilities

The internal backend is not currently accepted as having these capabilities:

- Real LLM intent classifier. The current classifier boundary and fake
  classifier are offline contracts for tests and experiments, not a live model
  integration.
- Vector retrieval. Product retrieval is record-based; no embedding search or
  vector index is accepted here.
- External SOP management. Reviewed SOP Markdown source files are local
  acceptance fixtures; this command does not fetch or synchronize SOP content
  from an external knowledge system.
- Real FastGPT execution. The dry-run route does not call FastGPT and does not
  compare against live FastGPT responses.
- PDD delivery. The dry-run route does not send PDD messages.
- Production default enablement. `Message.workflow.router.DEFAULT_BACKEND`
  remains `fastgpt`; internal backend use must be explicit.
- Automatic knowledge sync. Product records and SOP files are local inputs;
  this command does not import or refresh knowledge from external systems.

## Commands

Run internal engine synthetic QA and emit JSON only:

```powershell
python scripts\acceptance\internal_engine_synthetic_qa.py --json-only
```

Run a read-only product repository smoke check against SQLite:

```powershell
python scripts\acceptance\internal_product_repository_smoke.py --shop-id <shop_id> --query "<synthetic product query>"
```

Run internal backend no-send dry-run:

```powershell
python scripts\acceptance\internal_backend_dry_run.py --shop-id <shop_id> --message "<synthetic buyer message>"
```

Run internal backend no-send dry-run with a reviewed SOP fixture:

```powershell
python scripts\acceptance\internal_backend_dry_run.py --shop-id test-shop --message "收到破损了" --sop-file docs\acceptance\fixtures\internal_sop_example.md --json-only
```

List only the context summary without constructing or executing
`InternalWorkflowEngine`:

```powershell
python scripts\acceptance\internal_backend_dry_run.py --shop-id test-shop --message "收到破损了" --sop-file docs\acceptance\fixtures\internal_sop_example.md --dry-run --json-only
```

Expected T101-H one-command wrapper examples:

```powershell
python scripts\acceptance\internal_engine_acceptance.py --sop-file docs\acceptance\fixtures\internal_sop_example.md
python scripts\acceptance\internal_engine_acceptance.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --json-only
python scripts\acceptance\internal_engine_acceptance.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --dry-run --json-only
python scripts\acceptance\internal_engine_acceptance.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --no-write --json-only
```

Use synthetic, non-private messages for all examples. Do not paste real buyer
content, cookies, credentials, or live API keys into commands or reports.

## No-Send Contract

The scripts above are acceptance tools, not delivery tools:

- They do not call `SendMessage`.
- They do not send PDD messages.
- They do not start `PDDChannel` or open PDD WebSocket connections.
- They do not require live PDD credentials.
- They should report summaries, hashes, counts, status values, and actions
  rather than raw buyer content or raw reply text.
- `--sop-file` reports only SOP summary fields: `sop_record_count`,
  `sop_domains`, `sop_version`, and `sop_error_count`.
- `--sop-file` must not print complete SOP Markdown, approved answers,
  forbidden phrases, or stable SOP item ids.
- `--dry-run` must only list the context and fixture summary. It must not
  construct or execute `InternalWorkflowEngine`.
- T101-H `--no-write` mode must not create or update artifact files.

If a future dry-run command needs to show what would happen, it should report a
planned action such as `reply`, `transfer_human`, `request_evidence`, or
`fallback`; it must still avoid any platform send call.

## Dry-Run Artifact and Pass Criteria

In a T101-H bundle, this command feeds `dry_run_report.json`. The report is
acceptable only when it shows no-send behavior, hashed identifiers, SOP summary
fields, and no raw buyer or reply text.

The dry-run acceptance pass checks are:

- `no_send == true` in the dry-run evidence or manifest rollup.
- PDD send status is false.
- FastGPT call status is false.
- LLM call status is false.
- Schema validation passes for the generated report shape.
- The report contains no real cookie, key, or platform authorization value.

## Acceptance Notes

`internal_engine_synthetic_qa.py` is fully offline and uses synthetic product
records for product cases.

`internal_product_repository_smoke.py` opens SQLite in read-only mode, checks
for `shops` and `product_knowledge`, loads shop-scoped records, and returns
hashed or counted summary fields.

`internal_backend_dry_run.py` is the intended operator-facing no-send command
for checking internal backend decisions with a synthetic message. It should be
treated as unavailable for production rollout if the script is absent in a
checkout or if it attempts any platform send path.

Malformed or unreadable SOP files are non-fatal for acceptance diagnostics. The
JSON output should set `sop_record_count` to `0`, keep `sop_domains` empty, and
increase `sop_error_count` instead of crashing or printing raw SOP content.
