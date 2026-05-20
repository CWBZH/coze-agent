# T066 Linux systemd Run Log Template

Use this template on the real Linux server when executing T066. Do not paste secrets, cookies, full buyer messages, full AI replies, `.env` values, tokens, passwords, access tokens, or authorization headers into this file.

## 1. Server Information

```text
Hostname:
OS distribution:
Kernel:
CPU:
Memory:
Disk:
Timezone:
Operator:
Run date:
```

Commands:

```bash
hostname
cat /etc/os-release
uname -a
date
```

## 2. Python Version

```text
Python executable:
Python version:
Virtual environment / conda env:
Dependency install command:
Dependency install result:
```

Commands:

```bash
which python
python --version
python -m pip --version
```

## 3. Project Path

```text
Project path:
Git commit:
Service user:
Service group:
```

Commands:

```bash
pwd
git rev-parse --short HEAD
id customer-agent
```

## 4. `.env` Check

Do not paste `.env` values.

```text
.env exists: yes / no
.env permissions:
Required variable names present: yes / no
APP_ENV:
DATA_DIR:
LOG_DIR:
DB_PATH:
WORKER_STATUS_PATH:
```

Commands:

```bash
test -f .env && echo ".env exists"
stat -c "%a %U %G %n" .env
python - <<'PY'
from core import settings
print("APP_ENV=" + str(settings.APP_ENV))
print("DATA_DIR=" + str(settings.data_dir()))
print("LOG_DIR=" + str(settings.log_dir()))
print("DB_PATH=" + str(settings.db_path()))
print("WORKER_STATUS_PATH=" + str(settings.worker_status_path()))
PY
```

## 5. DB_PATH Check

```text
DB_PATH:
DB parent exists: yes / no
DB parent writable: yes / no
Existing DB file: yes / no
DB schema check result:
```

Commands:

```bash
python - <<'PY'
from core import settings
path = settings.db_path()
path.parent.mkdir(parents=True, exist_ok=True)
probe = path.parent / ".write_probe"
probe.write_text("ok", encoding="utf-8")
probe.unlink()
print(path)
print("db_exists=" + str(path.exists()))
PY
```

## 6. Playwright Check

```text
PLAYWRIGHT_BROWSERS_PATH:
BROWSER_CACHE_DIR:
Browser directory exists: yes / no
Browser directory readable: yes / no
Linux browser dependencies installed: yes / no
```

Commands:

```bash
python - <<'PY'
from core import settings
print("PLAYWRIGHT_BROWSERS_PATH=" + str(settings.playwright_browsers_path()))
print("BROWSER_CACHE_DIR=" + str(settings.browser_cache_dir()))
PY
```

## 7. Single Account Smoke Record

Do not paste real credentials. Record only shop_id/user_id and non-sensitive status.

```text
shop_id:
user_id:
Command:
Start time:
End time:
Exit code:
WebSocket connected: yes / no
Consumer started: yes / no
Heartbeat task created: yes / no
Message loop started: yes / no
worker.shutdown.completed: yes / no
worker.exiting code=0: yes / no
```

Command:

```bash
python -m runtime.worker --shop-id <shop_id> --user-id <user_id> --run-seconds 60 --status-interval 2
echo $?
python -m runtime.worker --status --json | python -m json.tool
```

Final snapshot summary:

```text
snapshot_phase:
worker_state:
connected_count:
exit_reason:
```

## 8. Stop-File Record

```text
Command:
Stop file path:
touch runtime.stop time:
Exit code:
worker.stop_file.detected: yes / no
worker.shutdown.requested reason=stop_file_detected: yes / no
worker.shutdown.completed: yes / no
connected_count final:
```

Commands:

```bash
rm -f runtime.stop
python -m runtime.worker --shop-id <shop_id> --user-id <user_id> --stop-file runtime.stop --status-interval 2
touch runtime.stop
python -m runtime.worker --status --json | python -m json.tool
```

## 9. systemd Start / Status / Stop Record

### Install / reload

```text
Service file copied: yes / no
Service file path:
daemon-reload result:
```

Commands:

```bash
sudo cp deploy/linux/customer-agent-worker.service.example /etc/systemd/system/customer-agent-worker.service
sudo systemctl daemon-reload
```

### Start

```text
systemctl start result:
systemctl status result:
Worker PID:
worker_status.json updating: yes / no
```

Commands:

```bash
sudo systemctl start customer-agent-worker
sudo systemctl status customer-agent-worker --no-pager
python -m runtime.worker --status --json | python -m json.tool
```

### Stop

```text
systemctl stop result:
ExecStop touched runtime.stop: yes / no
Graceful shutdown observed: yes / no
Final worker_state:
Final connected_count:
Traceback observed: yes / no
```

Commands:

```bash
sudo systemctl stop customer-agent-worker
sudo systemctl status customer-agent-worker --no-pager
python -m runtime.worker --status --json | python -m json.tool
```

## 10. Healthcheck Exit Code

```text
Command:
Exit code:
health_status:
computed_status:
Interpretation:
```

Commands:

```bash
sh deploy/linux/healthcheck.sh
echo $?
python -m runtime.worker --healthcheck --json | python -m json.tool
```

Exit code reference:

| Code | Meaning |
| --- | --- |
| `0` | healthy |
| `1` | degraded |
| `2` | missing |
| `3` | invalid |
| `4` | stale |
| `5` | stopped |

## 11. Diagnose Package Path

```text
Command:
Diagnose package path:
Package generated: yes / no
Package contains .env: yes / no
Package contains database files: yes / no
Package contains browser cache: yes / no
Package contains sensitive plaintext: yes / no
```

Commands:

```bash
sh deploy/linux/diagnose.sh --no-zip --include-git-status
```

## 12. journalctl Key Logs

Paste only non-sensitive log excerpts.

```text
worker.account.starting:
worker.account.started:
websocket connected:
consumer worker started:
heartbeat task created:
message loop started:
worker.shutdown.requested:
worker.shutdown.completed:
worker.exiting:
```

Failure pattern scan:

```bash
journalctl -u customer-agent-worker -n 500 --no-pager | grep -E "Traceback|pending task destroyed|Event loop is closed|attached to a different loop" || true
```

Scan result:

```text
Traceback:
pending task destroyed:
Event loop is closed:
attached to a different loop:
```

## 13. Failed Items

```text
Failed item 1:
Command:
Expected:
Actual:
Relevant log summary:
Risk:
Next action:

Failed item 2:
Command:
Expected:
Actual:
Relevant log summary:
Risk:
Next action:
```

## 14. Conclusion

Choose one:

```text
Conclusion: passed / failed / blocked
Reason:
Required fixes before delivery:
Recommended next task:
```

Decision guide:

- `passed`: systemd start/stop, status, healthcheck, diagnose, single-account smoke, and stop-file all passed.
- `failed`: Linux/systemd ran but one or more required acceptance criteria failed.
- `blocked`: Linux/systemd validation could not run because of missing environment, missing account, missing dependency, or unavailable server access.
