# T100-G Internal Engine Synthetic QA

Date: 2026-05-21

## Scope

`scripts/acceptance/internal_engine_synthetic_qa.py` runs offline synthetic QA against `InternalWorkflowEngine`.

The runner is intended for deterministic acceptance checks of the internal engine only. It does not send platform replies, does not start channel runtime, does not read the database, and does not use real buyer messages.

## Usage

This runner is one part of the internal backend acceptance surface. For the
SQLite product repository smoke check and no-send dry-run command, see
`docs/acceptance/T101D_INTERNAL_BACKEND_DRY_RUN.md`.
For the one-command no-send acceptance artifact contract, see
`docs/acceptance/T101H_INTERNAL_ENGINE_ACCEPTANCE_ARTIFACTS.md`.

Run the full synthetic suite and write a JSON report:

```powershell
python scripts\acceptance\internal_engine_synthetic_qa.py --output temp\internal_engine_synthetic_qa.json
```

Run a bounded smoke sample:

```powershell
python scripts\acceptance\internal_engine_synthetic_qa.py --limit 3 --output temp\internal_engine_synthetic_qa_smoke.json
```

List cases without executing `InternalWorkflowEngine`:

```powershell
python scripts\acceptance\internal_engine_synthetic_qa.py --dry-run
```

Emit JSON only to stdout:

```powershell
python scripts\acceptance\internal_engine_synthetic_qa.py --json-only
```

Run the suite with a reviewed SOP fixture summarized in the report:

```powershell
python scripts\acceptance\internal_engine_synthetic_qa.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --json-only
```

Expected T101-H one-command wrapper usage:

```powershell
python scripts\acceptance\internal_engine_acceptance.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --json-only
python scripts\acceptance\internal_engine_acceptance.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --dry-run --json-only
python scripts\acceptance\internal_engine_acceptance.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --no-write --json-only
```

List case context and SOP fixture summary without executing
`InternalWorkflowEngine`:

```powershell
python scripts\acceptance\internal_engine_synthetic_qa.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --dry-run --json-only
```

Exit code semantics:

- `0`: all required synthetic cases passed.
- `1`: at least one required synthetic case failed.

## JSON Report

The report includes:

- `summary.total`
- `summary.passed`
- `summary.failed`
- `summary.unclear`
- `offline_constraints`
- `sop_record_count`
- `sop_domains`
- `sop_version`
- `sop_error_count`
- `cases`
- `offline_constraints.calls_fastgpt`
- `offline_constraints.calls_llm`
- `offline_constraints.calls_pdd`
- `offline_constraints.sends_messages`

Case rows include hashed content and hashed reply text only. They do not include raw buyer messages or raw reply text.

Each executed case row also includes:

- `knowledge_hit_count`
- `knowledge_source`
- `intent`
- `action`

Product knowledge references are summarized only. The report does not include full synthetic product detail fields such as price, specifications, usage method, ingredients, shelf life, warnings, or manual notes.

SOP fixtures are summarized only. The report must not include full SOP
Markdown, approved answers, forbidden phrases, or stable SOP item ids.
Malformed or unreadable SOP files are non-fatal and should be reflected by
`sop_error_count` with `sop_record_count == 0` when no valid records are loaded.

## Offline Constraints

The runner must remain offline and synthetic:

- No real buyer data.
- No secrets, cookies, tokens, passwords, or access keys.
- No DB access required.
- No platform send calls.
- No PDD message sending.
- No channel runtime startup.
- No network-backed AI provider calls.
- `--sop-file` only loads a local Markdown fixture through the read-only SOP
  loader and adds summary metadata to the acceptance report.
- `calls_fastgpt`, `calls_llm`, `calls_pdd`, and `sends_messages` must remain
  false in the synthetic QA report.

The script is intentionally limited to `InternalWorkflowEngine`, `ProductKnowledgeRepository`, `ProductKnowledgeRetriever`, and fake repository-backed synthetic product records.

## Limitations

Synthetic QA does not prove real LLM behavior, real FastGPT behavior, PDD send
behavior, production default routing, or automatic knowledge synchronization.
It only proves deterministic internal engine behavior over synthetic cases and
local SOP fixture summaries.

## Artifact and Pass Criteria

In T101-H artifact bundles, this runner feeds `synthetic_report.json`.
Acceptance requires `summary.failed == 0`, `offline_constraints.calls_fastgpt ==
false`, `offline_constraints.calls_llm == false`, no platform send activity,
and schema-safe output without raw buyer text or raw reply text.

## Coverage Notes

Current synthetic cases cover:

- Redline complaint transfer.
- Explicit human request transfer.
- After-sales evidence request.
- Logistics boundary reply.
- Promotion boundary reply.
- Sensitive user safety reply.
- Product price reply from fake repository-backed product data.
- Product usage reply from fake repository-backed product data.
- Product ingredients reply from fake repository-backed product data.
- Product shelf-life reply from fake repository-backed product data.
- Product specification reply from fake repository-backed product data.
- Product suitability reply from fake repository-backed product data.
- Product basic fallback/no-match behavior.

The current suite has 13 cases. Six product cases use the fake repository-backed product record path and are expected to produce `knowledge_hit_count > 0` with `knowledge_source == "synthetic_product_record"`.

The synthetic inputs are derived from the current deterministic engine rule constants where practical, so the runner checks the behavior implemented by the internal engine without changing business logic.
