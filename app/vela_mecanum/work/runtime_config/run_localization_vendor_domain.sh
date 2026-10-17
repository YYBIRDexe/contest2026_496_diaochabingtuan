#!/usr/bin/env bash
# 在厂商栈所在的 ROS domain 里跑 AMCL 定位。
#
# 为什么不直接用 run_localization.sh：
#   原脚本按多机器人方案设计 —— ROS_DOMAIN_ID=42、坐标系带 robot4/ 前缀、
#   帧名 robot4/odom 与 robot4/base_link。但本车的厂商栈跑在 domain 4、
#   坐标系无前缀（odom/base_footprint/base_link/lidar_frame），两者对不上，
#   AMCL 会一直丢帧。这里改为与厂商栈一致，实测可用。
set -euo pipefail

source /etc/default/openvela-formation

exec docker exec \
  --user "$MENTORPI_CONTAINER_USER" \
  --workdir "$MENTORPI_CONTAINER_HOME" \
  --env ROS_DOMAIN_ID="$VENDOR_ROS_DOMAIN_ID" \
  --env ROS_LOCALHOST_ONLY=0 \
  --env MENTORPI_VENDOR_WS="$MENTORPI_VENDOR_WS" \
  --env MAP_YAML="/home/ubuntu/shared/classroom.yaml" \
  "$MENTORPI_CONTAINER" /bin/bash -lc '
    set -eo pipefail
    source /opt/ros/humble/setup.bash
    source "$MENTORPI_VENDOR_WS/install/setup.bash"
    source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash
    # 避免陈旧 SHM 端口锁（README 记录过这个问题）
    export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
    test -f "$MAP_YAML"
    exec ros2 launch mentorpi_formation_bringup localization.launch.py \
      map:="$MAP_YAML" \
      scan_topic:=scan_raw \
      odom_frame:=odom \
      base_frame:=base_footprint
  '
