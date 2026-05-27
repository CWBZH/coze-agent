# T101-E Internal vs FastGPT Comparison Harness

## Purpose

`scripts/acceptance/compare_internal_fastgpt.py` compares an existing internal JSON report with an existing FastGPT JSON report. It is an offline acceptance helper only.

The harness does not call FastGPT, does not read buyer data, does not import channel senders, and does not output full buyer messages or full AI replies.

For the T101-H one-command no-send artifact contract, see
`docs/acceptance/T101H_INTERNAL_ENGINE_ACCEPTANCE_ARTIFACTS.md`.

## Usage

Internal baseline only:

```bash
python scripts/acceptance/compare_internal_fastgpt.py \
  --internal-report path/to/internal_report.json \
  --internal-only \
  --json-only
```

Internal report plus an existing FastGPT or fake FastGPT report:

```bash
python scripts/acceptance/compare_internal_fastgpt.py \
  --internal-report path/to/internal_report.json \
  --fastgpt-report path/to/fastgpt_report.json \
  --json-only
```

Optional file output:

```bash
python scripts/acceptance/compare_internal_fastgpt.py \
  --internal-report path/to/internal_report.json \
  --fastgpt-report path/to/fastgpt_report.json \
  --output reports/internal_vs_fastgpt.json
```

Optional pass-rate gate:

```bash
python scripts/acceptance/compare_internal_fastgpt.py \
  --internal-report path/to/internal_report.json \
  --fastgpt-report path/to/fastgpt_report.json \
  --min-pass-rate 0.8 \
  --json-only
```

When `--min-pass-rate` is provided, the script still writes parseable JSON. It exits with code `1` when the computed pass rate is below the threshold.

Expected T101-H one-command wrapper examples:

```bash
python scripts/acceptance/internal_engine_acceptance.py --sop-file docs/acceptance/fixtures/internal_sop_example.md
python scripts/acceptance/internal_engine_acceptance.py --sop-file docs/acceptance/fixtures/internal_sop_example.md --json-only
python scripts/acceptance/internal_engine_acceptance.py --sop-file docs/acceptance/fixtures/internal_sop_example.md --dry-run --json-only
python scripts/acceptance/internal_engine_acceptance.py --sop-file docs/acceptance/fixtures/internal_sop_example.md --no-write --json-only
```

If `--fastgpt-report` is missing or points to a missing file, the script does not crash. Rows are marked `unclear` unless `--internal-only` is provided to explicitly request a baseline.

## Supported Inputs

The internal report may be:

- An object with `cases`.
- An object with `results`.
- A single JSON object from a dry-run style report.
- A top-level list of case objects.

Internal fields read:

- `case_id` or `id`
- `actual_action`, `action`, or `internal_action`
- `actual_intent`, `intent`, or `internal_intent`
- `status` or `verdict`
- `workflow_version`
- `sop_version`
- `knowledge_version`
- `sop_domain`
- `sop_domains`
- `knowledge_source`
- `risk_status` or `risk`
- `knowledge_status` or `knowledge`

The FastGPT report may be:

- An object with `cases`.
- An object with `results`.
- A top-level list of case objects.

FastGPT fields read:

- `case_id` or `id`
- `status` or `verdict`
- `label`, `fastgpt_label`, `classification`, or `action`
- `actual_intent`, `intent`, or `fastgpt_intent`
- `risk_status` or `risk`
- `knowledge_status` or `knowledge`

## Output Fields

Each comparison row contains only:

- `case_id`
- `internal_action`
- `internal_intent`
- `workflow_version`
- `sop_version`
- `knowledge_version`
- `sop_domain`
- `sop_domains`
- `knowledge_source`
- `version_status`
- `fastgpt_status`
- `fastgpt_label`
- `intent_match`
- `action_match`
- `risk_status`
- `knowledge_status`
- `verdict`

`verdict` is one of:

- `pass`
- `fail`
- `unclear`

The per-row comparison dimensions are:

- `version_status`: `pass` when `workflow_version`, `sop_version`, and `knowledge_version` are present; `missing` when one or more version fields are absent.
- `intent_match`: compares internal intent with FastGPT intent when both are available.
- `action_match`: compares internal action with FastGPT label/action, allowing known equivalent labels such as transfer-human aliases.
- `risk_status`: compares normalized risk status and fails on unsafe/failing values.
- `knowledge_status`: compares normalized knowledge grounding/support status and fails on unsupported/failing values.

Overall `verdict` is `fail` if any dimension fails, `unclear` if no dimension fails but at least one is unclear, otherwise `pass`.

When `--min-pass-rate` is set, `summary` also includes:

- `pass_rate`
- `min_pass_rate`
- `pass_rate_met`

The JSON also includes a summary and explicit offline constraints:

- `calls_fastgpt: false`
- `uses_existing_fastgpt_report_only`
- `reads_buyer_data: false`
- `outputs_full_reply_text: false`

## Privacy Boundary

The harness intentionally does not copy these fields into output:

- `reply`
- `reply_text`
- `actual_reply`
- `content`
- buyer message text
- product private detail fields

It only emits summary fields needed for pass/fail/unclear comparison.

## Acceptance Commands

```bash
python -m py_compile scripts/acceptance/compare_internal_fastgpt.py
python scripts/acceptance/compare_internal_fastgpt.py --help
python -m pytest tests/test_compare_internal_fastgpt.py -q
git diff --check
```

## T101-H Artifact and Pass Criteria

In a T101-H bundle, this harness feeds `comparison_report.json`. It may compare
against an existing FastGPT or fake FastGPT report, or run `--internal-only` to
produce an internal baseline when no existing report is available. It must never
make a live FastGPT request.

The comparison artifact passes only when:

- `summary.fail == 0`.
- `constraints.calls_fastgpt == false`.
- No full buyer message or full reply text is copied into comparison rows.
- Version, risk, knowledge, intent, and action dimensions are present or marked
  `unclear` rather than omitted silently.
- Schema validation passes when the report is normalized into the internal
  acceptance report schema.

## T101-G Extension Notes

This harness remains offline by design. It compares internal reports, including versioned workflow/SOP/knowledge metadata, with an existing FastGPT or fake FastGPT report. It does not instantiate `FastGPTHandler` and does not make real FastGPT calls.

Versioned internal reports can expose:

- `workflow_version`
- `sop_version`
- `knowledge_version`
- `sop_domain`
- `knowledge_source`

Missing version fields do not crash the comparison and do not leak full replies. They are surfaced as `version_status: "missing"` so acceptance output can distinguish absent version metadata from populated version metadata.
