#!/usr/bin/env bash
set -euo pipefail

robot_id=${1:?robot id required}
source /etc/default/openvela-formation
test "$robot_id" = "$ROBOT_ID"

if [ "$(docker inspect -f '{{.State.Running}}' "$MENTORPI_CONTAINER" 2>/dev/null || true)" != "true" ]; then
  exit 0
fi

exec docker exec -i "$MENTORPI_CONTAINER" /bin/bash -s -- "$robot_id" <<'INNER'
set -euo pipefail

robot_id=${1:?robot id required}
expected="python3 /opt/openvela-formation/formation_lab/reconfiguration_agent.py --robot-id ${robot_id}"

matching_pids() {
  local process command
  for process in /proc/[0-9]*; do
    [ -r "$process/cmdline" ] || continue
    command=$(tr '\0' ' ' <"$process/cmdline")
    command=${command% }
    if [ "$command" = "$expected" ]; then
      printf '%s\n' "${process#/proc/}"
    fi
  done
}

signal_and_wait() {
  local signal=$1
  local attempts=$2
  local pids
  pids=$(matching_pids)
  if [ -z "$pids" ]; then
    return 0
  fi
  kill "-$signal" $pids 2>/dev/null || true
  for ((attempt = 0; attempt < attempts; attempt++)); do
    [ -z "$(matching_pids)" ] && return 0
    sleep 0.1
  done
  return 1
}

signal_and_wait INT 50 || signal_and_wait TERM 30 || signal_and_wait KILL 10 || true

if [ -n "$(matching_pids)" ]; then
  echo "formation agent processes remain for $robot_id" >&2
  exit 1
fi
INNER
