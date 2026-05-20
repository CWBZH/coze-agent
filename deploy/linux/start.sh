#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DETECTED_REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
REPO_ROOT="${REPO_ROOT:-$DETECTED_REPO_ROOT}"
SERVICE_NAME="${SERVICE_NAME:-customer-agent-worker}"
STOP_FILE="${STOP_FILE:-$REPO_ROOT/runtime.stop}"
STATUS_INTERVAL="${STATUS_INTERVAL:-5}"

if command -v systemctl >/dev/null 2>&1; then
  exec systemctl start "$SERVICE_NAME"
fi

cd "$REPO_ROOT"
rm -f "$STOP_FILE"
exec python -m runtime.worker --all-enabled --status-interval "$STATUS_INTERVAL" --stop-file "$STOP_FILE"
