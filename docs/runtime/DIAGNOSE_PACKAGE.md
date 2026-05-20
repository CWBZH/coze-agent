# Diagnose Package

The diagnose scripts export a redacted runtime package for private deployment troubleshooting. They do not start or stop the worker.

## Commands

PowerShell:

```powershell
.\scripts\runtime\diagnose.ps1 --no-zip
.\scripts\runtime\diagnose.ps1 --output-dir .\temp\diagnostics --status-file .\temp\runtime\worker_status.json --include-git-status
```

Linux shell:

```bash
sh scripts/runtime/diagnose.sh --no-zip
sh scripts/runtime/diagnose.sh --output-dir ./temp/diagnostics --status-file ./temp/runtime/worker_status.json --include-git-status
```

## Output

Default output directory:

```text
DATA_DIR/diagnostics/diagnose-YYYYMMDD-HHMMSS
```

PowerShell creates a zip file by default:

```text
DATA_DIR/diagnostics/diagnose-YYYYMMDD-HHMMSS.zip
```

Linux creates a zip file only when the `zip` command is available. Use `--no-zip` to keep only the directory.

## Arguments

| Argument | Meaning |
| --- | --- |
| `--output-dir PATH` | Diagnostic output parent directory. |
| `--status-file PATH` | Worker status JSON path. Defaults to `WORKER_STATUS_PATH` or `DATA_DIR/runtime/worker_status.json`. |
| `--log-lines N` | Include the last N lines from recent log files. Default: `2000`. |
| `--max-log-kb N` | Include the last N KB from recent log files. Overrides line tail behavior when greater than zero. |
| `--no-zip` | Keep the diagnostic directory without creating an archive. |
| `--include-git-status` | Include `git status --short` and `git diff --name-only` output when the checkout is a Git repository. |

## Package Contents

The package may contain:

- `runtime/worker_status.json`
- `runtime/status.json`
- `runtime/healthcheck.json`
- `logs/*.log` redacted tail snippets from recent logs
- `config/.env.example`
- `docs/ENVIRONMENT_VARIABLES.md`
- `docs/HEADLESS_WORKER_RUNBOOK.md`
- `docs/DIAGNOSE_PACKAGE.md`
- `git/status_short.txt` when enabled
- `git/diff_name_only.txt` when enabled
- `metadata/python_version.txt`
- `metadata/pip_freeze.txt`
- `metadata/os_info.txt`
- `metadata/runtime_paths.txt`
- `manifest.json`

The scripts do not copy `.env`, `runtime.stop`, browser caches, database files, or full runtime directories.

## Redaction

The scripts redact common sensitive fields and values before writing package files. The mask format is:

```text
***REDACTED***
```

Redacted terms include credential, session, API key, token-like, and authorization fields. Logs are copied only as tail snippets and are redacted before they enter the diagnostic directory.

## Validation

After creating a package, validate:

```powershell
Get-ChildItem -Recurse .\temp\diagnostics\diagnose-* -Force | Where-Object { $_.Name -in @('.env', 'runtime.stop') }
```

Expected result: no files.

To inspect status:

```powershell
python -m json.tool .\temp\diagnostics\diagnose-YYYYMMDD-HHMMSS\runtime\status.json
python -m json.tool .\temp\diagnostics\diagnose-YYYYMMDD-HHMMSS\runtime\healthcheck.json
```

## Known Limits

Redaction is best-effort string masking. If a new log format embeds sensitive values without recognizable field names, the value may require a new redaction rule.

The package is intended for operational diagnosis. It is not a backup and does not include databases, browser profiles, cookies, or message history.
