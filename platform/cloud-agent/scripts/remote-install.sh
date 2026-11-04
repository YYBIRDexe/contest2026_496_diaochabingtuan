#!/usr/bin/env bash
# Install a staged release on the platform.  Runs on the platform as the
# unprivileged SSH user; no sudo is required.
#
# It never reads an existing key file into stdout and never overwrites an
# existing environment file.  If the environment file is absent it creates a
# mode-0600 template with no API key, so the service starts unconfigured.
#
# The service is installed as a *user* systemd unit named
# velaguard-cloud-agent.service and enabled with systemctl --user.  There is no
# nohup fallback: if the user session cannot run systemd, installation fails
# with an explicit SYSTEMD_USER_UNAVAILABLE marker instead of pretending the
# service is deployed.
set -euo pipefail

APP_DIR="${HOME}/cloud-agent"
STAGING=""
HOST="0.0.0.0"
PORT="8130"
NO_START="0"
PYTHON="${PYTHON:-python3}"

usage() {
  echo "usage: remote-install.sh --staging DIR [--app-dir DIR] [--host HOST] [--port PORT] [--no-start]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --staging) STAGING="$2"; shift 2 ;;
    --app-dir) APP_DIR="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --no-start) NO_START="1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [ -z "$STAGING" ] || [ ! -f "$STAGING/app.py" ]; then
  echo "staging directory is missing app.py: ${STAGING}" >&2
  exit 2
fi
case "$PORT" in
  ''|*[!0-9]*) echo "invalid port: $PORT" >&2; exit 2 ;;
esac

"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)' \
  || { echo "Python >= 3.8 is required" >&2; exit 2; }

CONFIG_DIR="${HOME}/.config/velaguard-cloud-agent"
ENV_FILE="${CONFIG_DIR}/cloud-agent.env"
KEY_FILE="${CONFIG_DIR}/deepseek.key"
STATE_DIR="${HOME}/.local/state/cloud-agent"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_NAME="velaguard-cloud-agent.service"
UNIT_FILE="${UNIT_DIR}/${UNIT_NAME}"
PID_FILE="${STATE_DIR}/cloud-agent.pid"
OLD_LOG_FILE="${STATE_DIR}/cloud-agent.log"

mkdir -p "$APP_DIR/releases" "$STATE_DIR" "$CONFIG_DIR" "$UNIT_DIR"
chmod 700 "$STATE_DIR" "$CONFIG_DIR" 2>/dev/null || true

RELEASE="${APP_DIR}/releases/$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$RELEASE"
cp -a "$STAGING/." "$RELEASE/"
chmod +x "$RELEASE"/scripts/*.sh 2>/dev/null || true

ENV_CREATED="0"
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  {
    echo "# Created by cloud-agent remote-install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# Keep this file mode 0600. Do not commit it or copy it to the workspace."
    echo "# The API key lives in ${KEY_FILE} and is referenced, never inlined."
    echo "CLOUD_AGENT_HOST=${HOST}"
    echo "CLOUD_AGENT_PORT=${PORT}"
    echo "CLOUD_AGENT_LLM_BASE_URL=https://api.deepseek.com"
    echo "CLOUD_AGENT_LLM_MODEL=deepseek-v4-flash"
    echo "CLOUD_AGENT_LLM_API_KEY_FILE=${KEY_FILE}"
    echo "CLOUD_AGENT_LLM_PROXY=direct"
    echo "CLOUD_AGENT_LLM_TIMEOUT_SECONDS=45"
    echo "CLOUD_AGENT_LLM_MAX_TOKENS=900"
    echo "CLOUD_AGENT_LLM_TEMPERATURE=0.1"
    echo "CLOUD_AGENT_MAX_TOOL_ITERATIONS=6"
    echo "CLOUD_AGENT_ACCESS_TOKEN="
    echo "CLOUD_AGENT_STATE_DIR=${STATE_DIR}"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ENV_CREATED="1"
else
  chmod 600 "$ENV_FILE" 2>/dev/null || true
fi

ln -sfn "$RELEASE" "${APP_DIR}/current"

if [ ! -f "$RELEASE/systemd/cloud-agent.service" ]; then
  echo "release is missing systemd/cloud-agent.service" >&2
  exit 1
fi
sed -e "s|--host 0.0.0.0|--host ${HOST}|" \
    -e "s|--port 8130|--port ${PORT}|" \
    "$RELEASE/systemd/cloud-agent.service" > "${UNIT_FILE}.tmp"
chmod 644 "${UNIT_FILE}.tmp"
mv "${UNIT_FILE}.tmp" "$UNIT_FILE"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -S "${XDG_RUNTIME_DIR}/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "SYSTEMD_USER_UNAVAILABLE=1" >&2
  echo "systemctl is not available; cannot enable ${UNIT_NAME}." >&2
  exit 1
fi
if ! systemctl --user daemon-reload; then
  echo "SYSTEMD_USER_UNAVAILABLE=1" >&2
  echo "systemctl --user cannot reach the user session; ${UNIT_NAME} was not started." >&2
  exit 1
fi

if [ "$NO_START" = "1" ]; then
  if ! systemctl --user enable "$UNIT_NAME" >/dev/null; then
    echo "SYSTEMD_ENABLE_FAILED=1" >&2
    echo "systemctl --user enable ${UNIT_NAME} failed." >&2
    exit 1
  fi
  echo "INSTALL_OK=1"
  echo "NO_START=1"
  echo "RELEASE=${RELEASE}"
  echo "ENV_FILE=${ENV_FILE}"
  echo "ENV_CREATED=${ENV_CREATED}"
  echo "SERVICE=${UNIT_NAME}"
  echo "SERVICE_ENABLED=1"
  echo "SERVICE_STARTED=0"
  exit 0
fi

# Stop a process left by the previous nohup-based deploy, if any.  The PID file
# is ours and does not name an arbitrary process.
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  case "$OLD_PID" in
    ''|*[!0-9]*) ;;
    *)
      if kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null || true
        i=0
        while kill -0 "$OLD_PID" 2>/dev/null && [ "$i" -lt 20 ]; do
          i=$((i + 1))
          sleep 0.2
        done
      fi
      ;;
  esac
  rm -f "$PID_FILE"
fi

if ! systemctl --user enable "$UNIT_NAME" >/dev/null; then
  echo "SYSTEMD_ENABLE_FAILED=1" >&2
  echo "systemctl --user enable ${UNIT_NAME} failed." >&2
  exit 1
fi
if ! systemctl --user restart "$UNIT_NAME"; then
  echo "SYSTEMD_RESTART_FAILED=1" >&2
  echo "systemctl --user restart ${UNIT_NAME} failed." >&2
  systemctl --user --no-pager --full status "$UNIT_NAME" >&2 || true
  journalctl --user -u "$UNIT_NAME" -n 30 --no-pager >&2 || true
  exit 1
fi

HEALTH=""
i=0
while [ "$i" -lt 30 ]; do
  if HEALTH=$("$PYTHON" - "$PORT" <<'PY'
import json
import sys
import urllib.request

port = sys.argv[1]
url = "http://127.0.0.1:%s/api/health" % port
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(url, timeout=2) as response:
        data = json.loads(response.read().decode("utf-8"))
except Exception as exc:
    print(json.dumps({"ok": False, "error": str(exc)}))
    raise SystemExit(1)
if data.get("service") != "velaguard-cloud-agent":
    print(json.dumps({"ok": False, "error": "unexpected service on port", "health": data}))
    raise SystemExit(2)
print(json.dumps({
    "ok": bool(data.get("ok")),
    "service": data.get("service"),
    "version": data.get("version"),
    "status": data.get("status"),
    "configured": bool((data.get("llm") or {}).get("configured")),
    "time": data.get("time"),
}, ensure_ascii=False))
PY
  ); then
    break
  fi
  HEALTH=""
  i=$((i + 1))
  sleep 1
done

if [ -z "$HEALTH" ] || ! systemctl --user is-active --quiet "$UNIT_NAME"; then
  echo "INSTALL_FAILED=1" >&2
  echo "SERVICE=${UNIT_NAME}" >&2
  echo "--- systemctl --user status (no environment contents) ---" >&2
  systemctl --user --no-pager --full status "$UNIT_NAME" >&2 || true
  echo "--- last journal lines (no environment contents) ---" >&2
  journalctl --user -u "$UNIT_NAME" -n 30 --no-pager >&2 || true
  exit 1
fi

echo "INSTALL_OK=1"
echo "RELEASE=${RELEASE}"
echo "ENV_FILE=${ENV_FILE}"
echo "ENV_CREATED=${ENV_CREATED}"
echo "SERVICE=${UNIT_NAME}"
echo "SERVICE_ENABLED=1"
echo "SERVICE_STARTED=1"
echo "OLD_LOG=${OLD_LOG_FILE}"
echo "HEALTH_JSON=${HEALTH}"
