#!/usr/bin/env bash
set -euo pipefail

distance=${1:-1.0}
source /etc/default/openvela-formation

exec docker exec \
  --user "$MENTORPI_CONTAINER_USER" \
  --workdir "$MENTORPI_CONTAINER_HOME" \
  --env MISSION_DISTANCE="$distance" \
  --env MENTORPI_VENDOR_WS="$MENTORPI_VENDOR_WS" \
  "$MENTORPI_CONTAINER" /bin/bash -lc '
    set -eo pipefail
    source /opt/ros/humble/setup.bash
    source "$MENTORPI_VENDOR_WS/install/setup.bash"
    source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash
    # Fast DDS shared-memory ports may be stale after vendor restarts. Vendor
    # participants also have UDPv4 enabled, so use it for this isolated mission.
    export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
    set -u
    paused=""
    rf2o_pid=""
    slam_pid=""
    cleanup() {
      set +e
      timeout 2 ros2 topic pub --rate 20 --times 10 /controller/cmd_vel \
        geometry_msgs/msg/Twist "{}" >/dev/null 2>&1
      [ -z "$slam_pid" ] || kill -TERM -- "-$slam_pid" 2>/dev/null
      [ -z "$rf2o_pid" ] || kill -TERM -- "-$rf2o_pid" 2>/dev/null
      for pid in $paused; do kill -CONT "$pid" 2>/dev/null; done
    }
    trap cleanup EXIT INT TERM

    patterns=(
      "/home/ubuntu/ros2_ws/install/app/lib/app/lidar_controller"
      "/home/ubuntu/ros2_ws/install/app/lib/app/line_following"
      "/home/ubuntu/ros2_ws/install/app/lib/app/object_tracking"
      "/home/ubuntu/ros2_ws/install/app/lib/app/hand_gesture"
      "/home/ubuntu/ros2_ws/install/peripherals/lib/peripherals/joystick_control"
    )
    for pattern in "${patterns[@]}"; do
      while read -r pid; do
        [ -z "$pid" ] || { kill -STOP "$pid"; paused="$paused $pid"; }
      done < <(pgrep -f "^/usr/bin/python3 $pattern( |$)" || true)
    done

    # Always start a fresh odometry/SLAM pair. A reused slam_toolbox keeps the
    # map -> odom correction it learned against the older odometry origin, so
    # the first metres of a reused pair look like a pose jump to the guards.
    # Only anchored executable paths are matched: any shorter pattern would
    # also match the command line of this very shell.
    for pattern in \
      "^/home/ubuntu/third_party_ros2/third_party_ws/install/rf2o_laser_odometry/lib/rf2o_laser_odometry/rf2o_laser_odometry_node " \
      "^/usr/bin/python3 /home/ubuntu/ros2_ws/install/mentorpi_formation_bringup/lib/mentorpi_formation_bringup/scan_symmetric( |$)" \
      "^/opt/ros/humble/lib/slam_toolbox/async_slam_toolbox_node "; do
      pgrep -f "$pattern" | xargs -r kill -9 2>/dev/null || true
    done
    sleep 1

    # The vendor rf2o launch feeds laser odometry straight from /scan_raw, whose
    # 0 ... 2*pi beam ordering rf2o reads half a turn off (it ignores angle_min),
    # which negated the odometry it published. odometry.launch.py keeps the
    # vendor parameters and inserts scan_symmetric in front of rf2o.
    setsid ros2 launch mentorpi_formation_bringup odometry.launch.py \
      scan_topic:=/scan_raw symmetric_scan_topic:=/scan_symmetric \
      odom_topic:=/odom_rf2o base_frame:=base_footprint odom_frame:=odom \
      >/home/ubuntu/shared/rf2o-distance-mission.log 2>&1 &
    rf2o_pid=$!
    setsid ros2 launch mentorpi_formation_bringup mapping.launch.py \
      base_frame:=base_footprint scan_topic:=/scan_raw \
      >/home/ubuntu/shared/slam-distance-mission.log 2>&1 &
    slam_pid=$!
    sleep 6
    ros2 run mentorpi_formation_bringup drive_distance \
      --distance "$MISSION_DISTANCE" --max-speed 0.08 --timeout 75 \
      2>&1 | tee /home/ubuntu/shared/drive-distance-mission.log
  '
