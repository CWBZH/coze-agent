# Headless Worker Runbook

This runbook covers local and Linux pre-deployment checks for the headless PDD WebSocket worker.

Run commands from the repository root unless using the scripts under `scripts/runtime`, which change into the repository root automatically.

## Single Account Start

```bash
python -m runtime.worker --shop-id <shop_id> --user-id <user_id>
```

PowerShell:

```powershell
python -m runtime.worker --shop-id 323473738 --user-id 163349769
```

## All Enabled Start

The current candidate rule is:

- `channel_name == "pinduoduo"`
- `status == 1`

`status == 1` is only a candidate-startable flag. It is not yet a durable `auto_reply_enabled` flag.

```bash
python -m runtime.worker --all-enabled
```

Dry run:

```bash
python -m runtime.worker --all-enabled --dry-run
```

## Playwright Browser Installation

The Linux worker uses Playwright for PDD login or cookie refresh paths. Keep the Python package and downloaded browser revision aligned.

Current deployment pin:

```text
playwright==1.55.0
```

Install the matching browser cache:

```bash
cd /opt/customer-agent-refactor-v3
source .venv/bin/activate

export PLAYWRIGHT_BROWSERS_PATH=/opt/customer-agent-refactor-v3/.browsers
python -m playwright install chromium
sudo .venv/bin/python -m playwright install-deps chromium
```

On Tencent Cloud or other domestic servers, use the mirror with the pinned package version:

```bash
cd /opt/customer-agent-refactor-v3
source .venv/bin/activate

export PLAYWRIGHT_BROWSERS_PATH=/opt/customer-agent-refactor-v3/.browsers
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
python -m playwright install chromium
sudo .venv/bin/python -m playwright install-deps chromium
```

Set the same cache path in `.env`:

```env
PLAYWRIGHT_BROWSERS_PATH=/opt/customer-agent-refactor-v3/.browsers
```

Do not use symlinks to make one browser revision appear as another revision. If Playwright reports `Executable doesn't exist`, inspect the active package and required revisions:

```bash
python -m pip show playwright
python - <<'PY'
import json
from pathlib import Path
import playwright

p = Path(playwright.__file__).resolve().parent / "driver/package/browsers.json"
data = json.loads(p.read_text())
for item in data["browsers"]:
    if item["name"] in {"chromium", "chromium-headless-shell", "ffmpeg"}:
        print(item["name"], item.get("revision"), item.get("browserVersion"))
PY
```

## Run-Seconds Smoke Test

Run for a bounded period and then perform graceful shutdown:

```bash
python -m runtime.worker --shop-id <shop_id> --user-id <user_id> --run-seconds 30 --status-interval 2
```

PowerShell smoke script:

```powershell
.\scripts\runtime\smoke_worker.ps1 -ShopId 323473738 -UserId 163349769 -RunSeconds 30
```

Linux shell smoke script:

```bash
sh scripts/runtime/smoke_worker.sh 323473738 163349769 30
```

The smoke scripts verify that the final snapshot contains:

- `snapshot_phase=final`
- `worker_state=stopped`
- `connected_count=0`
- `exit_reason=run_seconds_elapsed`

## Stop-File Shutdown

Start the worker with a stop-file path:

```bash
python -m runtime.worker --shop-id <shop_id> --user-id <user_id> --stop-file runtime.stop
```

Request shutdown from another terminal:

PowerShell:

```powershell
New-Item -ItemType File -Path .\runtime.stop -Force
```

Linux shell:

```bash
touch runtime.stop
```

The worker checks the stop file once per second. The file is not deleted automatically.

## Status

`--status` reads `WORKER_STATUS_PATH`, defaulting to:

```text
DATA_DIR/runtime/worker_status.json
```

Default local path:

```text
./temp/runtime/worker_status.json
```

Human-readable status:

```bash
python -m runtime.worker --status
```

JSON status:

```bash
python -m runtime.worker --status --json
```

Custom status file:

```bash
python -m runtime.worker --status --status-file /app/data/runtime/worker_status.json
```

## Healthcheck

PowerShell:

```powershell
.\scripts\runtime\healthcheck.ps1
.\scripts\runtime\healthcheck.ps1 -StatusFile .\temp\runtime\worker_status.json -StatusStaleSeconds 30
```

Linux shell:

```bash
sh scripts/runtime/healthcheck.sh
sh scripts/runtime/healthcheck.sh --status-file ./temp/runtime/worker_status.json --status-stale-seconds 30
```

Direct CLI:

```bash
python -m runtime.worker --healthcheck
python -m runtime.worker --healthcheck --json
```

## Healthcheck Exit Codes

| Exit code | Status | Meaning |
| --- | --- | --- |
| `0` | `healthy` | Worker is running, status is fresh, at least one account is running, and no accounts failed. |
| `1` | `degraded` | Worker is running but at least one account failed, or no running accounts are present. |
| `2` | `missing` | Status file does not exist. |
| `3` | `invalid` | Status file is not valid JSON. |
| `4` | `stale` | Worker has not completed shutdown, but `updated_at` is older than the stale threshold. |
| `5` | `stopped` | Final snapshot exists and worker shutdown completed. |

## Diagnose Package

Use the diagnose scripts to export a redacted troubleshooting package. The scripts do not start or stop the worker.

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

Default package location:

```text
DATA_DIR/diagnostics/diagnose-YYYYMMDD-HHMMSS
```

PowerShell creates a `.zip` archive by default. Linux creates a `.zip` archive only when the `zip` command is available. Use `--no-zip` to keep only the directory.

The package includes redacted worker status, `--status --json`, `--healthcheck --json`, recent log tails, environment variable documentation, runtime runbook, Python and OS metadata, and optional Git status. It does not include `.env`, `runtime.stop`, database files, browser profiles, cookies, or full message history.

See [DIAGNOSE_PACKAGE.md](DIAGNOSE_PACKAGE.md) for the full package contract and redaction notes.

## Common Failures

### missing

The status file is absent. Check:

- Worker was started at least once.
- `DATA_DIR` and `WORKER_STATUS_PATH` point to the expected location.
- The process has permission to create the parent directory.

### invalid

The status file is not valid JSON. Check:

- The file was not edited manually.
- The disk is not full.
- The status file was not replaced by another process.

### stale

The worker appears running but the status file is no longer updating. Check:

- The worker process is still alive.
- The event loop is not blocked.
- The account task is not stuck during startup or shutdown.

### stopped

The worker exited cleanly and wrote a final snapshot. This is expected after `--run-seconds`, `--stop-file`, SIGINT, or SIGTERM. In systemd validation, `systemctl stop` produced `exit_reason=SIGTERM`; this is a valid graceful shutdown result. It is unhealthy for Docker healthcheck semantics because the worker is no longer running.

### degraded

The worker is running but one or more accounts failed, or no accounts are currently running. Check account-specific errors in `account_errors`.

## Git Hygiene

Do not commit runtime state files:

- `runtime.stop`
- `temp/runtime/worker_status.json`
- `temp/diagnostics/`
- `logs/`
- `*.log`

The status file is operational state, not source code.
