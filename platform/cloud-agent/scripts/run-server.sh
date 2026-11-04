#!/bin/sh
# Run the cloud agent from a release directory.  Invoked by the installer or by
# an operator; it does not read secrets itself beyond CLOUD_AGENT_ENV_FILE.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

HOST=${CLOUD_AGENT_HOST:-0.0.0.0}
PORT=${CLOUD_AGENT_PORT:-8130}
STATE_DIR=${CLOUD_AGENT_STATE_DIR:-$HOME/.local/state/cloud-agent}
ENV_FILE=${CLOUD_AGENT_ENV_FILE:-$HOME/.config/velaguard-cloud-agent/cloud-agent.env}

export CLOUD_AGENT_STATE_DIR="$STATE_DIR"
if [ -f "$ENV_FILE" ]; then
  export CLOUD_AGENT_ENV_FILE="$ENV_FILE"
fi

mkdir -p "$STATE_DIR"
cd "$APP_DIR"
exec python3 "$APP_DIR/app.py" --host "$HOST" --port "$PORT" "$@"
