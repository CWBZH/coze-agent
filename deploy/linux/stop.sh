#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DETECTED_REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
REPO_ROOT="${REPO_ROOT:-$DETECTED_REPO_ROOT}"
SERVICE_NAME="${SERVICE_NAME:-customer-agent-worker}"
STOP_FILE="${STOP_FILE:-$REPO_ROOT/runtime.stop}"

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "$SERVICE_NAME.service" >/dev/null 2>&1; then
  exec systemctl stop "$SERVICE_NAME"
fi

cd "$REPO_ROOT"
touch "$STOP_FILE"
echo "stop_file=$STOP_FILE"
echo "graceful_shutdown_requested=true"
