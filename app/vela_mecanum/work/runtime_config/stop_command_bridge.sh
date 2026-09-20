#!/usr/bin/env bash
set -euo pipefail

robot=${1:?robot id required}
source /etc/default/openvela-formation
test "$robot" = "$ROBOT_ID"
armed=0
if docker exec MentorPi test -f /run/openvela-formation/command-arm.json; then armed=1; fi
docker exec MentorPi rm -f /run/openvela-formation/command-arm.json || true
docker exec MentorPi pkill -f "^python3 command_bridge.py --robot $robot( |$)" || true
if [ "$armed" -eq 1 ]; then
  docker exec --user ubuntu --env ROS_DOMAIN_ID="$VENDOR_ROS_DOMAIN_ID" MentorPi /bin/bash -lc '
    source /opt/ros/humble/setup.bash
    timeout 3 ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{}" >/dev/null
  ' || true
fi
