#!/usr/bin/env bash
set -euo pipefail

robot=${1:?robot id required}
source /etc/default/openvela-formation
test "$robot" = "$ROBOT_ID"
test -n "${VENDOR_ROS_DOMAIN_ID:-}"
exec docker exec --env FASTRTPS_DEFAULT_PROFILES_FILE=/home/ubuntu/shared/fleet_udp_unicast.xml --user ubuntu MentorPi /bin/bash -lc '
  source /opt/ros/humble/setup.bash
  source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash
  source /home/ubuntu/ros2_ws/install/setup.bash
  cd /opt/openvela-formation/formation_lab
  exec python3 command_bridge.py \
    --robot '"$robot"' \
    --local-domain '"$VENDOR_ROS_DOMAIN_ID"' \
    --fleet-domain '"$ROS_DOMAIN_ID"'
'
