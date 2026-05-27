# T101-I Internal Engine Local Gate

Date: 2026-05-21

## Purpose

This document fixes the local no-send gate that must be run after internal
workflow engine changes.

The gate is still offline-only. It does not call FastGPT, does not call a real
LLM, does not send PDD messages, and does not change the production default
backend.

## Command

Run the gate before merging internal engine changes:

```powershell
python scripts\acceptance\run_internal_engine_gate.py
```

Machine-readable output:

```powershell
python scripts\acceptance\run_internal_engine_gate.py --json-only
```

Plan only, without executing the engine:

```powershell
python scripts\acceptance\run_internal_engine_gate.py --dry-run --json-only
```

Run without writing artifacts:

```powershell
python scripts\acceptance\run_internal_engine_gate.py --no-write --json-only
```

Manual artifact directory:

```powershell
python scripts\acceptance\run_internal_engine_gate.py --output-dir temp\acceptance\internal-engine\manual-run
```

## Pass Criteria

The gate passes only when:

- `failed=0`
- schema validation passes
- artifact scan passes
- `no_send=true`
- `calls_fastgpt=false`
- `calls_llm=false`
- `sends_pdd=false`

Any schema validation error or artifact scan error must fail the gate.

## Artifact Retention

Acceptance artifacts are written under:

```text
temp/acceptance/internal-engine/run-YYYYMMDD-HHMMSS
```

Keep the newest 20 runs:

```powershell
python scripts\acceptance\cleanup_internal_acceptance_artifacts.py --keep-last 20
```

Preview cleanup:

```powershell
python scripts\acceptance\cleanup_internal_acceptance_artifacts.py --keep-last 20 --dry-run --json-only
```

Cleanup only removes `run-*` directories under the internal acceptance base
directory. It does not remove logs, DB files, `.env`, or arbitrary paths.

## Artifact Scan

The gate scans JSON artifacts for forbidden raw fields:

- `content`
- `reply_text`
- `raw_prompt`
- `raw_response`
- `raw_db_row`
- `full_sop`
- `full_product_detail`
- `api_key`
- `token`
- `cookie`
- `authorization`

Scan errors report file and field path only. They must not echo sensitive
values.
