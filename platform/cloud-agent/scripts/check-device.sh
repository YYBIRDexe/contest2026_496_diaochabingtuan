#!/usr/bin/env bash
# Read-only preflight for the platform.  Prints metadata only; it never prints
# an API key or access token from the environment file.
set -euo pipefail

PYTHON="${PYTHON:-python3}"
STATE_DIR="${HOME}/.local/state/cloud-agent"
CONFIG_DIR="${HOME}/.config/velaguard-cloud-agent"
ENV_FILE="${CLOUD_AGENT_ENV_FILE:-${CONFIG_DIR}/cloud-agent.env}"
KEY_FILE="${CLOUD_AGENT_LLM_API_KEY_FILE:-${CONFIG_DIR}/deepseek.key}"

echo "USER=$(id -un)"
echo "HOSTNAME=$(hostname)"
echo "KERNEL=$(uname -srm)"
echo "PYTHON=$("$PYTHON" --version 2>&1)"
echo "HOME=${HOME}"
echo "DISK_AVAILABLE_KB=$(df -Pk "$HOME" | awk 'NR==2 {print $4}')"

for tool in bash tar ssh python3; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "HAS_${tool}=1"
  else
    echo "HAS_${tool}=0"
  fi
done

"$PYTHON" - <<'PY'
import socket
for name, port in (("8130", 8130),):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        code = sock.connect_ex(("127.0.0.1", port))
        print("PORT_%s_IN_USE=%s" % (name, "1" if code == 0 else "0"))
    finally:
        sock.close()
PY

"$PYTHON" - "$ENV_FILE" "$KEY_FILE" <<'PY'
import os
import sys

path = sys.argv[1]
key_path = sys.argv[2]
print("ENV_FILE=%s" % path)
print("ENV_FILE_PRESENT=%s" % ("1" if os.path.isfile(path) else "0"))
print("KEY_FILE=%s" % key_path)
print("KEY_FILE_PRESENT=%s" % ("1" if os.path.isfile(key_path) else "0"))
if os.path.isfile(key_path):
    print("KEY_FILE_MODE=%o" % (os.stat(key_path).st_mode & 0o777))
if os.path.isfile(path):
    mode = os.stat(path).st_mode & 0o777
    print("ENV_FILE_MODE=%o" % mode)
    values = {}
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            for line in handle:
                text = line.strip()
                if not text or text.startswith("#") or "=" not in text:
                    continue
                key, value = text.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError as exc:
        print("ENV_FILE_READ_ERROR=%s" % exc)
    print("LLM_BASE_URL_SET=%s" % ("1" if values.get("CLOUD_AGENT_LLM_BASE_URL") else "0"))
    print("LLM_MODEL_SET=%s" % ("1" if values.get("CLOUD_AGENT_LLM_MODEL") else "0"))
    print("LLM_KEY_SET=%s" % ("1" if values.get("CLOUD_AGENT_LLM_API_KEY") else "0"))
    print("LLM_KEY_FILE_SET=%s" % ("1" if values.get("CLOUD_AGENT_LLM_API_KEY_FILE") else "0"))
    print("ACCESS_TOKEN_SET=%s" % ("1" if values.get("CLOUD_AGENT_ACCESS_TOKEN") else "0"))
PY

if [ -f "${STATE_DIR}/cloud-agent.pid" ]; then
  PID="$(cat "${STATE_DIR}/cloud-agent.pid" 2>/dev/null || true)"
  echo "APP_PID=${PID}"
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo "APP_PID_RUNNING=1"
  else
    echo "APP_PID_RUNNING=0"
  fi
else
  echo "APP_PID_RUNNING=0"
fi

if [ -f "${STATE_DIR}/cloud-agent.log" ]; then
  echo "LOG_BYTES=$(wc -c < "${STATE_DIR}/cloud-agent.log" | tr -d ' ')"
fi

if command -v systemctl >/dev/null 2>&1 && [ -d "/run/user/$(id -u)" ]; then
  echo "SYSTEMD_USER_AVAILABLE=1"
  echo "SERVICE_UNIT=velaguard-cloud-agent.service"
  XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" \
    systemctl --user show velaguard-cloud-agent.service --property=LoadState --value 2>/dev/null \
    | sed 's/^/SERVICE_LOAD_STATE=/' || true
  XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" \
    systemctl --user is-active velaguard-cloud-agent.service 2>/dev/null \
    | sed 's/^/SERVICE_ACTIVE=/' || true
else
  echo "SYSTEMD_USER_AVAILABLE=0"
fi

echo "CHECK_DONE=1"
