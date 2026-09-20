#!/usr/bin/env bash
set -euo pipefail

robot_id=${1:?}
stage=${2:?}
planner_hash=${3:?}
session_hash=${4:?}
agent_hash=${5:?}
endpoint_hash=${6:?}
localize_hash=${7:?}
scan_hash=${8:?}
bridge_hash=${9:?}
gate_hash=${10:?}
source /etc/default/openvela-formation
test "$robot_id" = "$ROBOT_ID"
case "$stage" in
  /home/pi/formation-install-*) ;;
  *) exit 1 ;;
esac
test ! -e /run/openvela-formation/command-arm.json
test "$(systemctl is-active "formation-agent@$robot_id.service")" = active
test "$(systemctl is-active "formation-command-bridge@$robot_id.service")" = active
test "$(docker exec MentorPi pgrep -fc "^python3 /opt/openvela-formation/formation_lab/reconfiguration_agent[.]py --robot-id ${robot_id}$")" -eq 1

remote_root=/opt/openvela-formation/formation_lab
config=/opt/openvela-formation/config/mentorpi.json
backup=/opt/openvela-formation/backups/formation-install-$(basename "$stage")
docker exec MentorPi test -f "$config"
for name in formation_planner.py reconfiguration_session.py reconfiguration_agent.py fleet_endpoint.py auto_localize.py scan_localizer.py command_bridge.py command_gate.py; do
  docker exec MentorPi test -f "$remote_root/$name"
done
docker exec MentorPi sha256sum "$remote_root/formation_planner.py" "$remote_root/reconfiguration_session.py" "$remote_root/reconfiguration_agent.py" "$remote_root/fleet_endpoint.py" "$remote_root/auto_localize.py" "$remote_root/scan_localizer.py" "$remote_root/command_bridge.py" "$remote_root/command_gate.py" "$config"
docker exec MentorPi mkdir -p "$backup"
docker exec MentorPi cp -a "$remote_root/formation_planner.py" "$remote_root/reconfiguration_session.py" "$remote_root/reconfiguration_agent.py" "$remote_root/fleet_endpoint.py" "$remote_root/auto_localize.py" "$remote_root/scan_localizer.py" "$remote_root/command_bridge.py" "$remote_root/command_gate.py" "$config" "$backup/"

for name in formation_planner.py reconfiguration_session.py reconfiguration_agent.py fleet_endpoint.py auto_localize.py scan_localizer.py command_bridge.py command_gate.py; do
  docker cp "$stage/$name" "MentorPi:$remote_root/$name"
done
docker exec -i MentorPi python3 - "$config" < "$stage/update_formation_limits.py"
docker exec MentorPi python3 -m py_compile "$remote_root/formation_planner.py" "$remote_root/reconfiguration_session.py" "$remote_root/reconfiguration_agent.py" "$remote_root/fleet_endpoint.py" "$remote_root/auto_localize.py" "$remote_root/scan_localizer.py" "$remote_root/command_bridge.py" "$remote_root/command_gate.py"

test "$(docker exec MentorPi sha256sum "$remote_root/formation_planner.py" | awk '{print $1}')" = "$planner_hash"
test "$(docker exec MentorPi sha256sum "$remote_root/reconfiguration_session.py" | awk '{print $1}')" = "$session_hash"
test "$(docker exec MentorPi sha256sum "$remote_root/reconfiguration_agent.py" | awk '{print $1}')" = "$agent_hash"
test "$(docker exec MentorPi sha256sum "$remote_root/fleet_endpoint.py" | awk '{print $1}')" = "$endpoint_hash"
test "$(docker exec MentorPi sha256sum "$remote_root/auto_localize.py" | awk '{print $1}')" = "$localize_hash"
test "$(docker exec MentorPi sha256sum "$remote_root/scan_localizer.py" | awk '{print $1}')" = "$scan_hash"
test "$(docker exec MentorPi sha256sum "$remote_root/command_bridge.py" | awk '{print $1}')" = "$bridge_hash"
test "$(docker exec MentorPi sha256sum "$remote_root/command_gate.py" | awk '{print $1}')" = "$gate_hash"
test ! -e /run/openvela-formation/command-arm.json

systemctl restart "formation-agent@$robot_id.service"
systemctl restart "formation-command-bridge@$robot_id.service"
sleep 3
test "$(systemctl is-active "formation-agent@$robot_id.service")" = active
test "$(systemctl is-active "formation-command-bridge@$robot_id.service")" = active
test "$(docker exec MentorPi pgrep -fc "^python3 /opt/openvela-formation/formation_lab/reconfiguration_agent[.]py --robot-id ${robot_id}$")" -eq 1
test ! -e /run/openvela-formation/command-arm.json
docker exec -i MentorPi python3 - "$config" --verify < "$stage/update_formation_limits.py"
echo "INSTALL_OK robot=$robot_id backup=$backup agent_count=1 lease=absent"
