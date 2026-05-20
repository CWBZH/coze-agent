# Linux systemd Deployment Skeleton

This directory contains a systemd-oriented deployment skeleton for the headless worker. It does not install Docker and does not replace the Windows local startup flow.

For real-machine acceptance, use `docs/deploy/LINUX_ACCEPTANCE_CHECKLIST.md` after adapting paths, users, Python executable, and `.env`.

## Files

| File | Purpose |
| --- | --- |
| `customer-agent-worker.service.example` | Example systemd unit for the headless worker. |
| `start.sh` | Start the systemd service when available, otherwise run the worker in the foreground. |
| `stop.sh` | Stop the systemd service when available, otherwise create `runtime.stop`. |
| `status.sh` | Run `python -m runtime.worker --status`. |
| `healthcheck.sh` | Run `python -m runtime.worker --healthcheck`. |
| `diagnose.sh` | Run `scripts/runtime/diagnose.sh`. |

## Install

Example target directory:

```bash
sudo mkdir -p /opt/customer-agent-refactor-v3
sudo chown -R customer-agent:customer-agent /opt/customer-agent-refactor-v3
```

Copy the project into `/opt/customer-agent-refactor-v3`, then install dependencies using the project's normal Python environment process.

## Playwright Browser Pinning

Linux deployments must keep the Python Playwright package and browser cache in sync. The project pins:

```text
playwright==1.55.0
```

For this version, install browsers into the configured cache path instead of relying on a user home cache:

```bash
cd /opt/customer-agent-refactor-v3
source .venv/bin/activate

export PLAYWRIGHT_BROWSERS_PATH=/opt/customer-agent-refactor-v3/.browsers
python -m playwright install chromium
sudo .venv/bin/python -m playwright install-deps chromium
```

On Tencent Cloud or other domestic servers, use the mirror only with the pinned package version:

```bash
cd /opt/customer-agent-refactor-v3
source .venv/bin/activate

export PLAYWRIGHT_BROWSERS_PATH=/opt/customer-agent-refactor-v3/.browsers
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
python -m playwright install chromium
sudo .venv/bin/python -m playwright install-deps chromium
```

Set the same browser cache in `.env`:

```env
PLAYWRIGHT_BROWSERS_PATH=/opt/customer-agent-refactor-v3/.browsers
```

Do not keep compatibility symlinks such as `chromium-1187` masquerading as `chromium-1223`; if the browser cache and Playwright package disagree, fix the package version or install the matching browser revision. The first Linux delivery line uses `playwright==1.55.0` and Chromium revision `1187`. A later Playwright upgrade must first prove that the matching browser revision can be downloaded or manually supplied.

Copy and edit the service file:

```bash
sudo cp deploy/linux/customer-agent-worker.service.example /etc/systemd/system/customer-agent-worker.service
sudo systemctl daemon-reload
```

If your project path, Python path, user, or group differs, edit:

```text
WorkingDirectory=
EnvironmentFile=
ExecStart=
ExecStartPre=
ExecStop=
User=
Group=
```

## Configure `.env`

Create the runtime `.env` from `.env.example`:

```bash
cp .env.example .env
chmod 600 .env
```

`.env` must not be committed to Git. Put private keys, tokens, service URLs, paths, and deployment-specific values there or in the system environment.

Recommended Linux values include:

```env
APP_ENV=linux
DATA_DIR=/var/lib/customer-agent
LOG_DIR=/var/log/customer-agent
WORKER_STATUS_PATH=/var/lib/customer-agent/runtime/worker_status.json
```

## Start

With systemd:

```bash
sudo systemctl start customer-agent-worker
sudo systemctl enable customer-agent-worker
```

With the helper:

```bash
sh deploy/linux/start.sh
```

Optional helper overrides:

```bash
REPO_ROOT=/opt/customer-agent-refactor-v3 STATUS_INTERVAL=5 STOP_FILE=/opt/customer-agent-refactor-v3/runtime.stop sh deploy/linux/start.sh
```

The service runs:

```bash
python -m runtime.worker --all-enabled --status-interval 5 --stop-file /opt/customer-agent-refactor-v3/runtime.stop
```

## Stop

With systemd:

```bash
sudo systemctl stop customer-agent-worker
```

With the helper:

```bash
sh deploy/linux/stop.sh
```

Optional helper override:

```bash
REPO_ROOT=/opt/customer-agent-refactor-v3 STOP_FILE=/opt/customer-agent-refactor-v3/runtime.stop sh deploy/linux/stop.sh
```

The service example uses the stop-file mechanism:

```text
ExecStartPre=/usr/bin/rm -f /opt/customer-agent-refactor-v3/runtime.stop
ExecStart=/usr/bin/python3 -m runtime.worker --all-enabled --status-interval 5 --stop-file /opt/customer-agent-refactor-v3/runtime.stop
ExecStop=/usr/bin/touch /opt/customer-agent-refactor-v3/runtime.stop
```

The worker can shut down gracefully through either SIGTERM or stop-file detection. In real systemd validation, `systemctl stop` produced `exit_reason=SIGTERM` and completed graceful shutdown successfully. The stop-file path remains useful for helper scripts and manual shutdown. The worker must be started with the same `--stop-file` path that helper scripts touch. `ExecStartPre` removes an old stop file before startup, otherwise a stale file would cause immediate shutdown.

If `--stop-file` is omitted from `ExecStart`, helper-script stop-file shutdown will not work. systemd SIGTERM shutdown can still be graceful, but the stop-file fallback will not be available.

The helper touches the same `runtime.stop` path used by `deploy/linux/start.sh`. This requests graceful worker shutdown; it is not a direct kill.

## Status

```bash
sh deploy/linux/status.sh
python -m runtime.worker --status
python -m runtime.worker --status --json
```

The default status file is:

```text
DATA_DIR/runtime/worker_status.json
```

## Healthcheck

```bash
sh deploy/linux/healthcheck.sh
python -m runtime.worker --healthcheck
```

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | healthy |
| `1` | degraded |
| `2` | missing status file |
| `3` | invalid status JSON |
| `4` | stale running snapshot |
| `5` | stopped final snapshot |

`stopped=5` means the worker is not running. This is expected after bounded smoke tests but unhealthy for a live service.

All helper scripts detect the repository root from their own location by default. For installed deployments, `REPO_ROOT` can be overridden:

```bash
REPO_ROOT=/opt/customer-agent-refactor-v3 sh deploy/linux/status.sh
REPO_ROOT=/opt/customer-agent-refactor-v3 sh deploy/linux/healthcheck.sh
REPO_ROOT=/opt/customer-agent-refactor-v3 sh deploy/linux/diagnose.sh --no-zip
```

## Diagnose

```bash
sh deploy/linux/diagnose.sh
sh deploy/linux/diagnose.sh --no-zip
sh deploy/linux/diagnose.sh --include-git-status
```

The diagnose script calls:

```bash
sh scripts/runtime/diagnose.sh
```

The diagnostic package is redacted and does not include `.env`, databases, browser caches, full runtime directories, or message history.

## Logs

Use systemd logs:

```bash
journalctl -u customer-agent-worker -f
journalctl -u customer-agent-worker --since "1 hour ago"
```

Application logs are controlled by `LOG_DIR`.

## Common Failures

### Service exits immediately

Check:

```bash
journalctl -u customer-agent-worker -n 200
python -m runtime.worker --status --json
```

Common causes:

- `.env` missing required service URLs or keys.
- Database path not writable.
- No candidate accounts found for `--all-enabled`.

### healthcheck returns missing

The worker has not written `worker_status.json`, or `DATA_DIR` / `WORKER_STATUS_PATH` points to a different path.

### healthcheck returns stale

The worker did not complete shutdown but status updates stopped. Check the process and event loop logs.

### healthcheck returns degraded

At least one account failed or no accounts are running. Inspect `account_errors` in the status JSON.

### stop does not complete

Check:

```bash
cat runtime.stop
journalctl -u customer-agent-worker -n 200
```

If the service is stuck beyond `TimeoutStopSec`, systemd may send the configured kill signal.

## Git Hygiene

Do not commit:

- `.env`
- `runtime.stop`
- `DATA_DIR/runtime/worker_status.json`
- diagnostics packages
- logs
- browser caches
