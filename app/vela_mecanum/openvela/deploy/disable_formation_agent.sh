#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "run with sudo" >&2; exit 2; fi
source /etc/default/openvela-formation
robot_id=$(cat /etc/openvela-formation-robot-id)
systemctl disable --now "formation-agent@$robot_id.service" >/dev/null 2>&1 || true

docker exec "$MENTORPI_CONTAINER" sed -i \
  's/"hardware_output_enabled": true/"hardware_output_enabled": false/' \
  "$MENTORPI_FORMATION_ROOT/config/mentorpi.json"

docker exec \
  --user "$MENTORPI_CONTAINER_USER" \
  --workdir "$MENTORPI_CONTAINER_HOME" \
  --env ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
  --env ROS_LOCALHOST_ONLY="$ROS_LOCALHOST_ONLY" \
  --env MENTORPI_VENDOR_WS="$MENTORPI_VENDOR_WS" \
  --env ROBOT_NAMESPACE="$ROBOT_NAMESPACE" \
  "$MENTORPI_CONTAINER" /bin/bash -lc '
    set -eo pipefail
    source /opt/ros/humble/setup.bash
    source "$MENTORPI_VENDOR_WS/install/setup.bash"
    timeout 2s ros2 topic pub --once /controller/cmd_vel geometry_msgs/msg/Twist "{}" >/dev/null 2>&1 || true
    timeout 2s ros2 topic pub --once "/$ROBOT_NAMESPACE/controller/cmd_vel" geometry_msgs/msg/Twist "{}" >/dev/null 2>&1 || true
  '
echo "$robot_id formation output disabled and zero command sent"

