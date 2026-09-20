#!/usr/bin/env bash
set -euo pipefail
robot_id=${1:?robot id required}
source /etc/default/openvela-formation
test "$robot_id" = "$ROBOT_ID"
exec docker exec --env FASTRTPS_DEFAULT_PROFILES_FILE=/home/ubuntu/shared/fleet_udp_unicast.xml \
  --user "$MENTORPI_CONTAINER_USER" --workdir "$MENTORPI_CONTAINER_HOME" \
  --env ROS_DOMAIN_ID="$ROS_DOMAIN_ID" --env ROS_LOCALHOST_ONLY="$ROS_LOCALHOST_ONLY" \
  "$MENTORPI_CONTAINER" /bin/bash -lc '
    source /opt/ros/humble/setup.bash
    source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash
    source /home/ubuntu/ros2_ws/install/setup.bash
    exec python3 /opt/openvela-formation/formation_lab/reconfiguration_agent.py --robot-id '"$robot_id"'
  '
