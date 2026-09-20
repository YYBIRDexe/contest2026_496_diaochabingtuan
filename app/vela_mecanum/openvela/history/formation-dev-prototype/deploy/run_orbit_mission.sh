#!/usr/bin/env bash
set -euo pipefail

# Lidar-hold orbit around one obstacle.
#
# The mission follows a single lidar contact, holds it at a fixed range and
# bearing and keeps driving forward, which traces a circle around that contact.
# Only the laser odometry pair is started: the circle is defined against the
# obstacle, not against a map, so the control loop needs a fresh scan and fresh
# laser odometry but no occupancy grid.  The guards in orbit_obstacle - contact
# range envelope, travel-direction clearance, surrounding clearance, fresh scan,
# fresh odometry and a yaw-jump limit - are what stop the car.

turns=${1:-1.0}
target_range=${2:-0.70}
extra=${3:-}
source /etc/default/openvela-formation

exec docker exec \
  --user "$MENTORPI_CONTAINER_USER" \
  --workdir "$MENTORPI_CONTAINER_HOME" \
  --env ORBIT_TURNS="$turns" \
  --env ORBIT_TARGET_RANGE="$target_range" \
  --env ORBIT_EXTRA="$extra" \
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
    cleanup() {
      set +e
      timeout 2 ros2 topic pub --rate 20 --times 10 /controller/cmd_vel \
        geometry_msgs/msg/Twist "{}" >/dev/null 2>&1
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

    # Always start a fresh odometry pair.  The vendor rf2o launch feeds rf2o
    # straight from /scan_raw, whose 0 ... 2*pi beam ordering rf2o reads half a
    # turn off (it ignores angle_min); odometry.launch.py inserts the
    # scan_symmetric relay in front of it and keeps the vendor parameters.
    for pattern in \
      "^/home/ubuntu/third_party_ros2/third_party_ws/install/rf2o_laser_odometry/lib/rf2o_laser_odometry/rf2o_laser_odometry_node " \
      "^/usr/bin/python3 /home/ubuntu/ros2_ws/install/mentorpi_formation_bringup/lib/mentorpi_formation_bringup/scan_symmetric( |$)"; do
      pgrep -f "$pattern" | xargs -r kill -9 2>/dev/null || true
    done
    sleep 1

    setsid ros2 launch mentorpi_formation_bringup odometry.launch.py \
      scan_topic:=/scan_raw symmetric_scan_topic:=/scan_symmetric \
      odom_topic:=/odom_rf2o base_frame:=base_footprint odom_frame:=odom \
      >/home/ubuntu/shared/rf2o-orbit-mission.log 2>&1 &
    rf2o_pid=$!
    sleep 6
    ros2 run mentorpi_formation_bringup orbit_obstacle \
      --turns "$ORBIT_TURNS" --target-range "$ORBIT_TARGET_RANGE" \
      --max-speed 0.08 --timeout 240 $ORBIT_EXTRA \
      2>&1 | tee /home/ubuntu/shared/orbit-mission.log
  '
