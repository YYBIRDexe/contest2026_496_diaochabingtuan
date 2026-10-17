#!/usr/bin/env bash
set -euo pipefail
source /etc/default/openvela-formation

docker exec --user "$MENTORPI_CONTAINER_USER" "$MENTORPI_CONTAINER" /bin/bash -lc '
  set +e
  source /opt/ros/humble/setup.bash
  # A ROS node name never reaches the process command line, so match the
  # installed executable path instead. The anchored pattern also stops pkill
  # from matching this very shell, whose -c argument quotes this script.
  pkill -TERM -f "^/usr/bin/python3 /home/ubuntu/ros2_ws/install/mentorpi_formation_bringup/lib/mentorpi_formation_bringup/drive_distance( |$)"
  timeout 2 ros2 topic pub --rate 20 --times 10 /controller/cmd_vel \
    geometry_msgs/msg/Twist "{}" >/dev/null 2>&1
  pkill -CONT -f /home/ubuntu/ros2_ws/install/app/lib/app/lidar_controller
  pkill -CONT -f /home/ubuntu/ros2_ws/install/app/lib/app/line_following
  pkill -CONT -f /home/ubuntu/ros2_ws/install/app/lib/app/object_tracking
  pkill -CONT -f /home/ubuntu/ros2_ws/install/app/lib/app/hand_gesture
  pkill -CONT -f /home/ubuntu/ros2_ws/install/peripherals/lib/peripherals/joystick_control
  exit 0
' || true
