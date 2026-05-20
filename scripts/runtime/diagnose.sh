#!/usr/bin/env sh
set -eu

OUTPUT_DIR=""
STATUS_FILE=""
LOG_LINES=2000
MAX_LOG_KB=0
NO_ZIP=0
INCLUDE_GIT_STATUS=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    --status-file)
      STATUS_FILE="${2:-}"
      shift 2
      ;;
    --log-lines)
      LOG_LINES="${2:-2000}"
      shift 2
      ;;
    --max-log-kb)
      MAX_LOG_KB="${2:-0}"
      shift 2
      ;;
    --no-zip)
      NO_ZIP=1
      shift
      ;;
    --include-git-status)
      INCLUDE_GIT_STATUS=1
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 64
      ;;
  esac
done

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

python_value() {
  python -c "$1" 2>/dev/null || true
}

if [ -z "$OUTPUT_DIR" ]; then
  OUTPUT_DIR=$(python_value "from core import settings; print(settings.data_dir() / 'diagnostics')")
  if [ -z "$OUTPUT_DIR" ]; then
    OUTPUT_DIR="$REPO_ROOT/temp/diagnostics"
  fi
fi

if [ -z "$STATUS_FILE" ]; then
  STATUS_FILE=$(python_value "from core import settings; print(settings.worker_status_path())")
fi

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
DIAGNOSE_DIR="$OUTPUT_DIR/diagnose-$TIMESTAMP"
mkdir -p "$DIAGNOSE_DIR"

redact_file() {
  src="$1"
  dst="$2"
  mkdir -p "$(dirname "$dst")"
  python - "$src" "$dst" <<'PY'
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
text = src.read_text(encoding="utf-8", errors="replace") if src.exists() else ""
patterns = [
    (r'(?i)("(?:access_token|authorization|api_key|password|cookie|secret|token)"\s*:\s*")[^"]*(")', r'\1***REDACTED***\2'),
    (r"(?i)('(?:access_token|authorization|api_key|password|cookie|secret|token)'\s*:\s*')[^']*(')", r'\1***REDACTED***\2'),
    (r'(?i)\b(access_token|authorization|api_key|password|cookie|secret|token)\b(\s*[:=]\s*)("[^"]*"|'"'"'[^'"'"']*'"'"'|[^\s,;}]+)', r'\1\2***REDACTED***'),
    (r'(?i)\bBearer\s+[A-Za-z0-9._~+\-/=]+', 'Bearer ***REDACTED***'),
    (r'(?i)\bark-[A-Za-z0-9._-]+', '***REDACTED***'),
    (r'(?i)\bfastgpt-[A-Za-z0-9._-]+', '***REDACTED***'),
    (r'(?i)access_token|authorization|api_key|password|cookie|secret|token', '***REDACTED***'),
]
for pattern, replacement in patterns:
    text = re.sub(pattern, replacement, text)
dst.write_text(text, encoding="utf-8")
PY
}

write_redacted_text() {
  rel="$1"
  tmp="$DIAGNOSE_DIR/.tmp-redact"
  mkdir -p "$(dirname "$DIAGNOSE_DIR/$rel")"
  cat > "$tmp"
  redact_file "$tmp" "$DIAGNOSE_DIR/$rel"
  rm -f "$tmp"
}

capture_command() {
  name="$1"
  rel="$2"
  shift 2
  set +e
  output=$("$@" 2>&1)
  code=$?
  set -e
  printf '%s\n' "$output" | write_redacted_text "$rel"
  printf '%s=%s\n' "$name" "$code" >> "$DIAGNOSE_DIR/metadata/command_exit_codes.txt"
}

mkdir -p "$DIAGNOSE_DIR/metadata"

python - <<'PY' | write_redacted_text "metadata/runtime_paths.txt"
from core import settings
print(f"APP_ENV={settings.APP_ENV}")
print(f"DATA_DIR={settings.data_dir()}")
print(f"LOG_DIR={settings.log_dir()}")
print(f"DB_PATH={settings.db_path()}")
print(f"WORKER_STATUS_PATH={settings.worker_status_path()}")
PY

python --version 2>&1 | write_redacted_text "metadata/python_version.txt"
python -m pip freeze 2>&1 | write_redacted_text "metadata/pip_freeze.txt"
{
  uname -a 2>/dev/null || true
  printf 'SHELL=%s\n' "${SHELL:-}"
} | write_redacted_text "metadata/os_info.txt"

if [ -n "$STATUS_FILE" ] && [ -f "$STATUS_FILE" ]; then
  redact_file "$STATUS_FILE" "$DIAGNOSE_DIR/runtime/worker_status.json"
fi

STATUS_ARGS="-m runtime.worker --status --json"
HEALTH_ARGS="-m runtime.worker --healthcheck --json"
if [ -n "$STATUS_FILE" ]; then
  STATUS_ARGS="$STATUS_ARGS --status-file $STATUS_FILE"
  HEALTH_ARGS="$HEALTH_ARGS --status-file $STATUS_FILE"
fi
capture_command "runtime_status_json" "runtime/status.json" python $STATUS_ARGS
capture_command "runtime_healthcheck_json" "runtime/healthcheck.json" python $HEALTH_ARGS

[ -f ".env.example" ] && redact_file ".env.example" "$DIAGNOSE_DIR/config/.env.example"
[ -f "docs/config/ENVIRONMENT_VARIABLES.md" ] && redact_file "docs/config/ENVIRONMENT_VARIABLES.md" "$DIAGNOSE_DIR/docs/ENVIRONMENT_VARIABLES.md"
[ -f "docs/runtime/HEADLESS_WORKER_RUNBOOK.md" ] && redact_file "docs/runtime/HEADLESS_WORKER_RUNBOOK.md" "$DIAGNOSE_DIR/docs/HEADLESS_WORKER_RUNBOOK.md"
[ -f "docs/runtime/DIAGNOSE_PACKAGE.md" ] && redact_file "docs/runtime/DIAGNOSE_PACKAGE.md" "$DIAGNOSE_DIR/docs/DIAGNOSE_PACKAGE.md"

LOG_DIR=$(python_value "from core import settings; print(settings.log_dir())")
if [ -n "$LOG_DIR" ] && [ -d "$LOG_DIR" ]; then
  find "$LOG_DIR" -type f -name '*.log' 2>/dev/null | sort | tail -n 3 | while IFS= read -r log_file; do
    safe_name=$(basename "$log_file")
    tmp="$DIAGNOSE_DIR/.tmp-log"
    if [ "$MAX_LOG_KB" -gt 0 ]; then
      tail -c "$((MAX_LOG_KB * 1024))" "$log_file" > "$tmp" 2>/dev/null || true
    else
      tail -n "$LOG_LINES" "$log_file" > "$tmp" 2>/dev/null || true
    fi
    redact_file "$tmp" "$DIAGNOSE_DIR/logs/$safe_name"
    rm -f "$tmp"
  done
fi

if [ "$INCLUDE_GIT_STATUS" -eq 1 ]; then
  capture_command "git_status_short" "git/status_short.txt" git status --short
  capture_command "git_diff_name_only" "git/diff_name_only.txt" git diff --name-only
fi

cat > "$DIAGNOSE_DIR/manifest.json" <<EOF
{
  "schema_version": 1,
  "created_at": "$(date -Iseconds)",
  "repo_root": "$REPO_ROOT",
  "diagnose_dir": "$DIAGNOSE_DIR",
  "status_file": "$STATUS_FILE",
  "log_lines": $LOG_LINES,
  "max_log_kb": $MAX_LOG_KB,
  "include_git_status": $INCLUDE_GIT_STATUS
}
EOF

if [ "$NO_ZIP" -eq 0 ]; then
  if command -v zip >/dev/null 2>&1; then
    (cd "$DIAGNOSE_DIR" && zip -qr "../$(basename "$DIAGNOSE_DIR").zip" .)
    echo "diagnose_zip=$DIAGNOSE_DIR.zip"
  else
    echo "zip_unavailable=true"
  fi
fi

echo "diagnose_dir=$DIAGNOSE_DIR"
