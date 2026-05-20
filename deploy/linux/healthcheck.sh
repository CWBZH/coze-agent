#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DETECTED_REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
REPO_ROOT="${REPO_ROOT:-$DETECTED_REPO_ROOT}"

cd "$REPO_ROOT"
exec python -m runtime.worker --healthcheck "$@"
