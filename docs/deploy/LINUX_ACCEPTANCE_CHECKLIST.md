# Linux Acceptance Checklist

This checklist verifies the Linux headless worker deployment before a private delivery handoff. It assumes the headless worker, status file, healthcheck, diagnose package, and systemd skeleton are already present.

Do not commit `.env`, `runtime.stop`, `worker_status.json`, logs, diagnostics packages, database files, or browser caches.

## 1. Environment Preparation

### Python runtime

- [ ] Confirm Python version:

```bash
python --version
```

- [ ] Confirm the chosen runtime is documented: system Python, venv, or conda.
- [ ] Confirm the runtime can import the project:

```bash
python -m runtime.worker --status
```

Expected first-run result may be `worker_status=missing` with exit code `2`.

### Virtual environment / conda

- [ ] Create and activate the selected environment.
- [ ] Install project dependencies using the project-approved dependency flow.
- [ ] Record the Python executable used by systemd, for example:

```bash
which python
```

- [ ] Update `deploy/linux/customer-agent-worker.service.example` after copying if the Python path is not `/usr/bin/python3`.

### Playwright browser path

- [ ] Confirm the active Playwright package is pinned to the accepted Linux delivery version:

```bash
python -m pip show playwright
```

Expected:

```text
Version: 1.55.0
```

- [ ] Confirm browser path variables are set when needed:

```env
PLAYWRIGHT_BROWSERS_PATH=/opt/customer-agent-refactor-v3/.browsers
BROWSER_CACHE_DIR=/opt/customer-agent-refactor-v3/.browsers
```

- [ ] Confirm the browser directory is readable by the service user.
- [ ] Confirm Linux browser dependencies are installed on the host.
- [ ] On Tencent Cloud or domestic servers, install the matching browser revision with the mirror:

```bash
cd /opt/customer-agent-refactor-v3
source .venv/bin/activate

export PLAYWRIGHT_BROWSERS_PATH=/opt/customer-agent-refactor-v3/.browsers
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
python -m playwright install chromium
sudo .venv/bin/python -m playwright install-deps chromium
```

- [ ] Confirm the accepted Chromium revision exists and no temporary `chromium-1223` symlink workaround remains:

```bash
find /opt/customer-agent-refactor-v3/.browsers -maxdepth 2 -type d | sort
test -d /opt/customer-agent-refactor-v3/.browsers/chromium-1187
test ! -e /opt/customer-agent-refactor-v3/.browsers/chromium-1223
```

### Runtime configuration

- [ ] Copy `.env.example` to `.env`:

```bash
cp .env.example .env
chmod 600 .env
```

- [ ] Confirm `.env` is not tracked by Git.
- [ ] Configure at minimum:

```env
APP_ENV=linux
DATA_DIR=/var/lib/customer-agent
LOG_DIR=/var/log/customer-agent
DB_PATH=/var/lib/customer-agent/channel_shop.db
WORKER_STATUS_PATH=/var/lib/customer-agent/runtime/worker_status.json
```

- [ ] Confirm directories exist and are writable by the service user:

```bash
sudo mkdir -p /var/lib/customer-agent/runtime /var/log/customer-agent
sudo chown -R customer-agent:customer-agent /var/lib/customer-agent /var/log/customer-agent
```

## 2. Pre-Start Checks

- [ ] Ensure no stale stop file exists:

```bash
rm -f runtime.stop
```

- [ ] Check status:

```bash
python -m runtime.worker --status
```

Expected before first start:

- `worker_status=missing`, exit code `2`, or
- a previous final snapshot with `computed_status=stopped`.

- [ ] Check healthcheck:

```bash
python -m runtime.worker --healthcheck
```

Expected before first start:

- `missing=2`, or
- `stopped=5` if a previous final snapshot exists.

- [ ] Confirm status parent directory is writable:

```bash
python - <<'PY'
from core import settings
path = settings.worker_status_path()
path.parent.mkdir(parents=True, exist_ok=True)
probe = path.parent / ".write_probe"
probe.write_text("ok", encoding="utf-8")
probe.unlink()
print(path)
PY
```

- [ ] Confirm log directory is writable:

```bash
python - <<'PY'
from core import settings
path = settings.log_dir()
path.mkdir(parents=True, exist_ok=True)
probe = path / ".write_probe"
probe.write_text("ok", encoding="utf-8")
probe.unlink()
print(path)
PY
```

## 3. Single Account Smoke Test

Use one known valid account.

```bash
python -m runtime.worker --shop-id <shop_id> --user-id <user_id> --run-seconds 60 --status-interval 2
```

Acceptance checks:

- [ ] Log contains worker account start:

```text
worker.account.starting
```

- [ ] Log indicates PDD WebSocket connected.
- [ ] Log indicates heartbeat task started.
- [ ] Log indicates message receive loop started.
- [ ] Log indicates MessageConsumer workers started and includes `worker_count`.
- [ ] Log contains shutdown completion:

```text
worker.shutdown.completed
worker.exiting
```

- [ ] Final status shows stopped and no active connection:

```bash
python -m runtime.worker --status --json | python -m json.tool
```

Expected:

```json
{
  "snapshot_phase": "final",
  "worker_state": "stopped",
  "connected_count": 0,
  "exit_reason": "run_seconds_elapsed"
}
```

- [ ] No shutdown errors:

```bash
journalctl -u customer-agent-worker --since "10 minutes ago" | grep -E "pending task destroyed|Event loop is closed|attached to a different loop" || true
```

## 4. Stop-File Shutdown

Start with stop-file:

```bash
rm -f runtime.stop
python -m runtime.worker --shop-id <shop_id> --user-id <user_id> --stop-file runtime.stop --status-interval 2
```

From another terminal:

```bash
touch runtime.stop
```

Acceptance checks:

- [ ] Log contains:

```text
worker.stop_file.detected
worker.shutdown.requested reason=stop_file_detected
worker.shutdown.completed
```

- [ ] Final status:

```bash
python -m runtime.worker --status --json | python -m json.tool
```

Expected:

- `snapshot_phase=final`
- `worker_state=stopped`
- `connected_count=0`
- `exit_reason=stop_file_detected`

## 5. systemd Verification

### Install service

- [ ] Copy service file:

```bash
sudo cp deploy/linux/customer-agent-worker.service.example /etc/systemd/system/customer-agent-worker.service
```

- [ ] Edit path, user, group, Python executable, and environment file if different:

```text
WorkingDirectory=/opt/customer-agent-refactor-v3
EnvironmentFile=/opt/customer-agent-refactor-v3/.env
ExecStartPre=/usr/bin/rm -f /opt/customer-agent-refactor-v3/runtime.stop
ExecStart=/usr/bin/python3 -m runtime.worker --all-enabled --status-interval 5 --stop-file /opt/customer-agent-refactor-v3/runtime.stop
ExecStop=/usr/bin/touch /opt/customer-agent-refactor-v3/runtime.stop
```

- [ ] Reload systemd:

```bash
sudo systemctl daemon-reload
```

### Start

```bash
sudo systemctl start customer-agent-worker
sudo systemctl status customer-agent-worker --no-pager
```

Acceptance checks:

- [ ] systemd service is active or running.
- [ ] `runtime.stop` was removed before start.
- [ ] worker writes `worker_status.json`.
- [ ] status command works:

```bash
sh deploy/linux/status.sh
```

### Healthcheck

```bash
sh deploy/linux/healthcheck.sh
echo $?
```

Expected for live service:

- `0` healthy, or
- `1` degraded if some accounts failed but worker is still running.

`5` means stopped and is not acceptable for a live service.

### Stop

```bash
sudo systemctl stop customer-agent-worker
sudo systemctl status customer-agent-worker --no-pager
```

Acceptance checks:

- [ ] Worker receives a graceful stop request from systemd.
- [ ] Worker logs show graceful shutdown.
- [ ] Final status has `connected_count=0`.
- [ ] Final status may show `exit_reason=SIGTERM`; this is accepted for systemd stop.
- [ ] `exit_reason=stop_file_detected` is only required when explicitly testing the stop-file helper path.
- [ ] systemd reports deactivation successfully.
- [ ] No `pending task destroyed`.
- [ ] No `Event loop is closed`.
- [ ] No `BaseSubprocessTransport` cleanup noise.
- [ ] No `Executable doesn't exist` or `chromium-1223` browser revision mismatch.

### Logs

```bash
journalctl -u customer-agent-worker -n 200 --no-pager
journalctl -u customer-agent-worker -f
```

### Diagnose

```bash
sh deploy/linux/diagnose.sh --no-zip --include-git-status
```

Acceptance checks:

- [ ] Diagnose package is created.
- [ ] Package does not include `.env`.
- [ ] Package does not include database files.
- [ ] Package does not include browser caches.
- [ ] Package does not include full message history.
- [ ] Package status and healthcheck JSON parse successfully.

## 6. Failure Scenario Checks

### Status file missing

Command:

```bash
python -m runtime.worker --status --status-file /tmp/not-exist-worker-status.json
```

Expected:

- exit code `2`
- output indicates `missing`

### Stale status

Create or keep a status file with old `updated_at` and no `shutdown_completed_at`.

Expected:

- `--status` exit code `4`
- `--healthcheck` exit code `4`
- output indicates `stale`

### Invalid status

Command:

```bash
printf 'not-json' > /tmp/invalid-worker-status.json
python -m runtime.worker --status --status-file /tmp/invalid-worker-status.json
```

Expected:

- exit code `3`
- output indicates `invalid`

### stopped=5

After a clean bounded run or stop-file shutdown:

```bash
python -m runtime.worker --healthcheck
echo $?
```

Expected:

- exit code `5`
- output indicates `stopped`
- means worker is not running

### Redis unavailable

Expected behavior:

- Worker should not crash during startup solely because optional Redis is unavailable if fail-safe behavior is active.
- Logs should identify Redis connection failure without leaking secrets.
- Human lock / inference lock behavior should be reviewed before production acceptance.

### FastGPT unavailable

Expected behavior:

- WebSocket connection can still start.
- Message processing should log AI/pipeline failure with trace IDs.
- No full buyer message or full AI reply appears in logs.

### PDD login expired

Expected behavior:

- Account start should fail or reconnect should fail with clear account-level error.
- Worker should record failed account state without killing other accounts.
- Diagnose package should include account error summary, not cookies or credentials.

### WebSocket disconnect / reconnect

Expected behavior:

- Reconnect lifecycle lock and generation prevent overlapping cleanup.
- Old generation does not clear new connection.
- No duplicate consumer is created for the same queue.
- No `attached to a different loop` error appears.

## 7. Pass Criteria

Deployment can be accepted when all required checks pass:

- [ ] Worker starts from CLI.
- [ ] Worker starts from systemd.
- [ ] Worker stops through systemd SIGTERM graceful shutdown.
- [ ] Stop-file graceful shutdown works as a manual/helper-script path.
- [ ] `python -m runtime.worker --status` reports correct state.
- [ ] `python -m runtime.worker --healthcheck` exit codes match documented semantics.
- [ ] `worker_status.json` is written and final snapshot has `connected_count=0`.
- [ ] Diagnose package exports successfully.
- [ ] Diagnose package does not contain `.env`, database files, browser caches, cookies, tokens, passwords, access tokens, authorization headers, or full message history.
- [ ] Logs do not show `pending task destroyed`.
- [ ] Logs do not show `Event loop is closed`.
- [ ] Logs do not show `BaseSubprocessTransport`.
- [ ] Logs do not show `attached to a different loop`.
- [ ] Logs do not show `Executable doesn't exist` or `chromium-1223` after Playwright browser pinning.
- [ ] Logs do not show repeated consumer creation for the same queue during normal start/stop.
- [ ] FastGPT business workflow has been separately verified before production handoff.

## 8. Evidence to Save

Save these files or command outputs outside Git:

- `python --version`
- Dependency install command and result
- `.env` variable names only, not values
- `python -m runtime.worker --status --json`
- `python -m runtime.worker --healthcheck --json`
- `journalctl -u customer-agent-worker -n 200 --no-pager`
- diagnose package path

Do not paste secrets, cookies, full messages, or full replies into acceptance notes.
