#!/usr/bin/env bash
set -euo pipefail

robot_id=${1:?robot id required}
source /etc/default/openvela-formation

exec docker exec --env FASTRTPS_DEFAULT_PROFILES_FILE=/home/ubuntu/shared/fleet_udp_unicast.xml \
  --user "$MENTORPI_CONTAINER_USER" \
  --workdir "$MENTORPI_CONTAINER_HOME" \
  --env ROBOT_ID="$robot_id" \
  --env ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
  --env ROS_LOCALHOST_ONLY="$ROS_LOCALHOST_ONLY" \
  --env MENTORPI_VENDOR_WS="$MENTORPI_VENDOR_WS" \
  --env MENTORPI_FORMATION_ROOT="$MENTORPI_FORMATION_ROOT" \
  "$MENTORPI_CONTAINER" /bin/bash -lc '
    set -eo pipefail
    source /opt/ros/humble/setup.bash
    if [ -f /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash ]; then
      source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash
    fi
    source "$MENTORPI_VENDOR_WS/install/setup.bash"
    export PYTHONPATH="$MENTORPI_FORMATION_ROOT${PYTHONPATH:+:$PYTHONPATH}"
    exec python3 -m formation_lab.mentorpi_agent \
      --robot-id "$ROBOT_ID" \
      --config "$MENTORPI_FORMATION_ROOT/config/mentorpi.json"
  '

