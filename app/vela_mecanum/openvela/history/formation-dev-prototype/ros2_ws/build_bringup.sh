#!/usr/bin/env bash
set -o pipefail

log=/home/vela/mentorpi-ros2-bringup-build.log
echo "=== mentorpi_formation_bringup build $(date -Is) ===" | tee -a "$log"
{
  source /opt/ros/humble/setup.bash
  cd /home/vela/formation-lab/ros2_ws || exit 125
  colcon build --symlink-install --packages-select mentorpi_formation_bringup
} 2>&1 | tee -a "$log"
rc=${PIPESTATUS[0]}
echo "=== ROS2_BRINGUP_BUILD_EXIT_${rc} ===" | tee -a "$log"
exit "$rc"
