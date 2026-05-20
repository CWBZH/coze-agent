#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

STATUS_FILE=""
STATUS_STALE_SECONDS="30"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --status-file)
      STATUS_FILE="${2:-}"
      shift 2
      ;;
    --status-stale-seconds)
      STATUS_STALE_SECONDS="${2:-30}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 64
      ;;
  esac
done

cd "$REPO_ROOT"

if [ -n "$STATUS_FILE" ]; then
  exec python -m runtime.worker --healthcheck --status-file "$STATUS_FILE" --status-stale-seconds "$STATUS_STALE_SECONDS"
fi

exec python -m runtime.worker --healthcheck --status-stale-seconds "$STATUS_STALE_SECONDS"
