# T101-H Internal Engine Acceptance Artifacts

Date: 2026-05-21

## Purpose

T101-H defines the one-command no-send acceptance shape for the internal
workflow engine and the artifacts expected from a complete run.

The acceptance target is documentation and evidence for the internal backend
only. It is not a production rollout switch and it is not a live FastGPT or PDD
delivery test.

## One-Command Usage

T102-A adds a fixed local gate wrapper. Use it for internal engine changes:

```powershell
python scripts\acceptance\run_internal_engine_gate.py
```

Expected one-command acceptance entrypoint:

```powershell
python scripts\acceptance\internal_engine_acceptance.py --sop-file docs\acceptance\fixtures\internal_sop_example.md
```

Emit machine-readable output only:

```powershell
python scripts\acceptance\internal_engine_acceptance.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --json-only
```

List acceptance context and planned artifacts without executing the engine:

```powershell
python scripts\acceptance\internal_engine_acceptance.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --dry-run --json-only
```

Run without writing artifact files:

```powershell
python scripts\acceptance\internal_engine_acceptance.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --no-write --json-only
```

Current component-level commands remain:

```powershell
python scripts\acceptance\internal_engine_synthetic_qa.py --sop-file docs\acceptance\fixtures\internal_sop_example.md --json-only
python scripts\acceptance\internal_backend_dry_run.py --shop-id test-shop --message "synthetic product question" --sop-file docs\acceptance\fixtures\internal_sop_example.md --dry-run --json-only
python scripts\acceptance\compare_internal_fastgpt.py --internal-report reports\internal\synthetic_report.json --internal-only --json-only
```

Use only synthetic, non-private message text in examples and reports.

## Current Internal Engine Capabilities

Acceptance currently covers these internal-only capabilities:

- Hard rules in `InternalWorkflowEngine` for redline transfer, explicit human
  request, after-sales evidence request, logistics boundary reply, promotion
  boundary reply, sensitive-user safety reply, and product-basic fallback.
- Product repository access through `ProductKnowledgeRepository`, including
  synthetic product records for QA and read-only SQLite smoke checks.
- SOP provider loading through `SOPProvider` from reviewed local Markdown
  fixtures, with report-safe summaries for version, domains, record count, and
  load errors.
- Domain responder behavior through `DomainPolicyResponder` for SOP-backed
  policy domains.
- Output guardrail enforcement through `OutputGuardrail`.
- Offline fake answer generator metadata when explicitly enabled for no-send
  acceptance.
- Report schema validation for internal acceptance report shapes, including
  rejection of raw buyer content and raw reply fields.
- No-send acceptance evidence from synthetic QA, internal backend dry-run, and
  internal-vs-existing-report comparison.

## Current Limitations

T101-H does not accept or imply these capabilities:

- No real LLM call is made.
- No real LLM answer generator is made available by default.
- No real FastGPT call is made; comparison uses an existing report or
  internal-only baseline.
- No PDD send is made.
- The internal backend is not the production default.
- No automatic knowledge sync is performed from external systems into the
  product repository or SOP fixture set.
- No real buyer message, live shop credential, cookie, API key, or platform
  authorization value is required.

## Artifact Files

A complete no-send acceptance run should produce or be able to emit these
artifact files:

- `manifest.json`: run manifest with timestamp, command mode, artifact paths,
  repository revision when available, and no-send/offline constraint flags.
- `synthetic_report.json`: output from internal synthetic QA, including
  `summary`, `offline_constraints`, SOP summary fields, and hashed case rows.
- `dry_run_report.json`: output from internal backend dry-run, including
  `no_send=true`, `dry_run`, hashed identifiers, action or planned action, SOP
  summary fields, and knowledge/guardrail summary fields.
- `comparison_report.json`: output from the offline internal-vs-FastGPT report
  comparison, including `summary`, `constraints.calls_fastgpt=false`, and
  per-case pass/fail/unclear dimensions.
- `summary.json`: rollup status for the acceptance run, including pass
  criteria, schema validation status, artifact paths, and a final
  pass/fail/unclear verdict.

Artifacts must avoid raw buyer content, raw reply text, private product detail,
full SOP Markdown, approved answer bodies, forbidden phrase lists, stable SOP
item ids, and any credential material.

When fake answer generation is enabled, artifacts may include
`answer_generator`, `answer_generation_source`, `answer_confidence`,
`used_history_count`, and `prompt_hash`. They must still not include full draft
text, full prompt text, raw provider response, full history, or full knowledge
content.

## Boundaries

No-send acceptance has these hard boundaries:

- `no_send` must be true for dry-run evidence.
- `calls_fastgpt` must be false.
- `calls_llm` must be false.
- `sends_pdd` or equivalent PDD send flag must be false.
- Platform senders, PDD channel runtime, FastGPT clients, queue workers, and
  network-backed AI providers must not be part of the acceptance execution.
- `--dry-run` must not execute `InternalWorkflowEngine`; it only reports
  context, fixture summaries, and planned artifact shape.
- `--no-write` must not create or update artifact files; output may still be
  printed to stdout when `--json-only` is supplied.

## Pass Criteria

T101-H passes only when all of the following are true:

- Synthetic QA has `summary.failed == 0`.
- The local gate has `failed == 0`.
- Schema validation passes for `internal-report-v1`.
- Artifact scan passes.
- No-send evidence has `no_send == true`.
- Offline constraints show `calls_fastgpt == false`.
- Offline constraints show `calls_llm == false`.
- Send constraints show `sends_pdd == false`.
- Schema validation passes for generated acceptance reports.
- Artifact files listed in `manifest.json` exist unless the run used
  `--no-write`.
- Reports contain summary fields, hashes, counts, versions, actions, and
  verdicts only; they do not contain raw buyer text, raw reply text, real
  cookies, real keys, or platform authorization values.

If any pass criterion is missing, the T101-H result should be `unclear` or
`failed`; it should not be treated as production approval.

## Retention

Acceptance artifacts are retained under:

```text
temp/acceptance/internal-engine/run-YYYYMMDD-HHMMSS
```

Clean old local runs while keeping the newest 20:

```powershell
python scripts\acceptance\cleanup_internal_acceptance_artifacts.py --keep-last 20
```

Preview cleanup without deleting:

```powershell
python scripts\acceptance\cleanup_internal_acceptance_artifacts.py --keep-last 20 --dry-run --json-only
```
