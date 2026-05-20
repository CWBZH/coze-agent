# T066 systemd Validation Report

Status: accepted on Tencent Cloud Ubuntu.

This report records the Linux/systemd real-machine validation result for the headless worker deployment skeleton.

## 1. Verification Environment

```text
Host: Tencent Cloud Ubuntu
Project path: /opt/customer-agent-refactor-v3
Installed service: /etc/systemd/system/customer-agent-worker.service
APP_ENV: linux
Python: /opt/customer-agent-refactor-v3/.venv/bin/python
Worker command: python -m runtime.worker --all-enabled --status-interval 5 --stop-file /opt/customer-agent-refactor-v3/runtime.stop
Status file: /opt/customer-agent-refactor-v3/temp/runtime/worker_status.json
```

The service was validated with two candidate PDD accounts loaded by `--all-enabled`.

## 2. Playwright Browser Strategy

Real-machine checks confirmed:

```text
Playwright package: 1.55.0
Chromium revision: chromium-1187
Headless shell revision: chromium_headless_shell-1187
FFmpeg revision: ffmpeg-1011
Removed temporary compatibility path: chromium-1223
```

Decision:

- Pin `playwright==1.55.0` for the first Linux/systemd delivery line.
- Install browsers with the same venv Python and `PLAYWRIGHT_BROWSERS_PATH=/opt/customer-agent-refactor-v3/.browsers`.
- Do not rely on symlinks that make `chromium-1187` appear as `chromium-1223`.
- If upgrading Playwright later, first prove that the matching Chromium revision can be downloaded or manually supplied.

Accepted install command for Tencent Cloud / domestic servers:

```bash
cd /opt/customer-agent-refactor-v3
source .venv/bin/activate

export PLAYWRIGHT_BROWSERS_PATH=/opt/customer-agent-refactor-v3/.browsers
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
python -m playwright install chromium
sudo .venv/bin/python -m playwright install-deps chromium
```

Required `.env` setting:

```env
PLAYWRIGHT_BROWSERS_PATH=/opt/customer-agent-refactor-v3/.browsers
```

## 3. Single-Account Smoke

Command shape:

```bash
python -m runtime.worker --shop-id 323473738 --user-id 163349769 --run-seconds 60 --status-interval 2
```

Result:

- WebSocket startup path completed.
- MessageConsumer worker pool started.
- Graceful shutdown completed after `--run-seconds 60`.
- `worker.shutdown.completed` was logged.
- `worker.exiting code=0` was logged.
- Final snapshot had `connected_count=0`.
- Final snapshot had `exit_reason=run_seconds_elapsed`.

## 4. systemd Start / Stop

Start validation:

- `systemctl start` / `systemctl restart` succeeded.
- Service reached active/running state.
- `--all-enabled` started two candidate accounts.
- Runtime status reported `connected_count=2`.
- Healthcheck returned `health_status=healthy`.

Stop validation:

- `systemctl stop customer-agent-worker` succeeded.
- Worker entered graceful shutdown.
- `worker.shutdown.completed` was logged.
- `worker.exiting code=0` was logged.
- Final snapshot had `connected_count=0`.
- Final snapshot had `stopped_accounts=2`.
- systemd reported deactivation successfully.

Observed final stop reason:

```text
exit_reason=SIGTERM
```

This is accepted. It means the SIGTERM graceful shutdown path passed. The stop-file mechanism remains available for manual/helper-script shutdown, but systemd stop does not need to produce `exit_reason=stop_file_detected`.

## 5. Suspicious Log Check

The final accepted run did not show:

- `Executable doesn't exist`
- `chromium-1223`
- `Exception ignored`
- `BaseSubprocessTransport`
- `RuntimeError: Event loop is closed`
- `Traceback`
- `pending task destroyed`
- `attached to a different loop`

## 6. Diagnose Package

The diagnose flow was verified with:

```bash
sh deploy/linux/diagnose.sh --no-zip --include-git-status
```

Result:

- Diagnose directory was generated.
- Package excludes `.env`.
- Package excludes database files.
- Package excludes browser caches.
- Package excludes full runtime message history.
- Package redaction strategy is documented in `docs/runtime/DIAGNOSE_PACKAGE.md`.

## 7. Final Conclusion

Linux/systemd first engineering deployment validation is accepted.

Accepted capabilities:

- Headless worker starts on Linux.
- systemd can run the worker.
- `--all-enabled` can orchestrate two accounts with one `PDDChannel` per account.
- Runtime status file is written.
- `--status` and `--healthcheck` work.
- systemd stop enters graceful shutdown.
- Final snapshot normalizes `connected_count=0`.
- Diagnose package can be exported.
- Playwright package/browser revision is pinned and no longer depends on `chromium-1223` symlink workarounds.

Remaining risks before production handoff:

1. FastGPT business workflow has not yet been accepted end-to-end in the Linux deployment shape.
2. Docker Compose is not implemented.
3. Long-duration multi-account soak testing is still recommended.
4. Durable account auto-start selection is still based on `channel_name == "pinduoduo"` and `status == 1`, not a dedicated `auto_reply_enabled` flag.

Recommended next stage:

- Validate FastGPT reply workflow on Linux, or proceed to Docker Compose only after explicitly accepting the remaining business workflow risk.
