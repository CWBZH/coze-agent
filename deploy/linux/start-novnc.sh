#!/usr/bin/env bash
set -euo pipefail

DISPLAY_NUM="${DISPLAY_NUM:-99}"
DISPLAY_VALUE=":${DISPLAY_NUM}"
VNC_PORT="${VNC_PORT:-5901}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
CHROME_DEBUG_PORT="${CHROME_DEBUG_PORT:-9222}"
PDD_LOGIN_URL="${PDD_LOGIN_URL:-https://mms.pinduoduo.com/login}"
PROFILE_DIR="${PROFILE_DIR:-${HOME}/remote-browser/chrome-profile}"

pkill -f "Xvfb ${DISPLAY_VALUE}" || true
pkill -f "x11vnc.*${VNC_PORT}" || true
pkill -f "websockify.*${NOVNC_PORT}" || true
pkill -f "chromium.*${PROFILE_DIR}" || true

mkdir -p "${PROFILE_DIR}"

Xvfb "${DISPLAY_VALUE}" -screen 0 1366x768x24 -ac +extension GLX +render -noreset &
sleep 2

export DISPLAY="${DISPLAY_VALUE}"

x11vnc -display "${DISPLAY_VALUE}" -rfbport "${VNC_PORT}" -forever -shared -nopw -quiet &
sleep 1

websockify --web=/usr/share/novnc/ "${NOVNC_PORT}" "localhost:${VNC_PORT}" &
sleep 1

CHROME_BIN="$(command -v chromium || command -v chromium-browser || true)"
if [ -z "${CHROME_BIN}" ]; then
  echo "chromium not found"
  exit 1
fi

"${CHROME_BIN}" \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --disable-software-rasterizer \
  --password-store=basic \
  --window-size=1366,768 \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="${CHROME_DEBUG_PORT}" \
  --remote-allow-origins="*" \
  --user-data-dir="${PROFILE_DIR}" \
  "${PDD_LOGIN_URL}" &

echo "noVNC ready: http://127.0.0.1:${NOVNC_PORT}/vnc.html"
echo "Chrome CDP ready: http://127.0.0.1:${CHROME_DEBUG_PORT}/json/list"

wait
