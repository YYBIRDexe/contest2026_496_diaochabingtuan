#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "run with sudo" >&2; exit 2; fi
source /etc/default/openvela-formation
robot_id=$(cat /etc/openvela-formation-robot-id)

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
    if [ -f /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash ]; then
      source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash
    fi
    source "$MENTORPI_VENDOR_WS/install/setup.bash"
    ros2 run mentorpi_formation_bringup hardware_probe \
      --namespace "$ROBOT_NAMESPACE" --require-localization
    ros2 run mentorpi_formation_bringup tf_audit \
      --robots "$ROBOT_NAMESPACE" --timeout 6
  '

docker exec "$MENTORPI_CONTAINER" sed -i \
  's/"hardware_output_enabled": false/"hardware_output_enabled": true/' \
  "$MENTORPI_FORMATION_ROOT/config/mentorpi.json"
systemctl enable --now "formation-agent@$robot_id.service"
systemctl --no-pager --full status "formation-agent@$robot_id.service"

