#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <shop_id> <user_id> [run_seconds]" >&2
  exit 64
fi

SHOP_ID="$1"
USER_ID="$2"
RUN_SECONDS="${3:-30}"
STOP_FILE="$REPO_ROOT/runtime.stop"

cd "$REPO_ROOT"

rm -f "$STOP_FILE"

python -m runtime.worker --shop-id "$SHOP_ID" --user-id "$USER_ID" --run-seconds "$RUN_SECONDS" --status-interval 2
python -m runtime.worker --status

set +e
python -m runtime.worker --healthcheck
HEALTH_EXIT=$?
set -e
if [ "$HEALTH_EXIT" -ne 5 ]; then
  echo "healthcheck_exit=$HEALTH_EXIT expected=5" >&2
  exit 10
fi

STATUS_FILE=$(python - <<'PY'
from core import settings
print(settings.worker_status_path())
PY
)

if [ ! -f "$STATUS_FILE" ]; then
  echo "status_file_missing=$STATUS_FILE" >&2
  exit 11
fi

python - "$STATUS_FILE" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

checks = {
    "snapshot_phase": data.get("snapshot_phase") == "final",
    "worker_state": data.get("worker_state") == "stopped",
    "connected_count": data.get("connected_count") == 0,
    "exit_reason": data.get("exit_reason") == "run_seconds_elapsed",
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    print("snapshot_invalid " + " ".join(failed), file=sys.stderr)
    sys.exit(12)
PY

echo "smoke_worker=passed status_file=$STATUS_FILE"
