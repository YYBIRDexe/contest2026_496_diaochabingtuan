#!/usr/bin/env bash
set -euo pipefail

source /etc/default/openvela-formation

exec docker exec \
  --user "$MENTORPI_CONTAINER_USER" \
  --workdir "$MENTORPI_CONTAINER_HOME" \
  --env ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
  --env ROS_LOCALHOST_ONLY="$ROS_LOCALHOST_ONLY" \
  --env MENTORPI_VENDOR_WS="$MENTORPI_VENDOR_WS" \
  --env ROBOT_NAMESPACE="$ROBOT_NAMESPACE" \
  --env MAP_YAML="$MAP_YAML" \
  "$MENTORPI_CONTAINER" /bin/bash -lc '
    set -eo pipefail
    source /opt/ros/humble/setup.bash
    if [ -f /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash ]; then
      source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash
    fi
    source "$MENTORPI_VENDOR_WS/install/setup.bash"
    test -f "$MAP_YAML"
    exec ros2 launch mentorpi_formation_bringup localization.launch.py \
      namespace:="$ROBOT_NAMESPACE" \
      map:="$MAP_YAML" \
      scan_topic:=scan_raw \
      odom_frame:="$ROBOT_NAMESPACE/odom" \
      base_frame:="$ROBOT_NAMESPACE/base_link"
  '

