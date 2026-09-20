#!/usr/bin/env bash
set -euo pipefail

prefix="${1:-$HOME/maps/classroom}"
mkdir -p "$(dirname "$prefix")"
ros2 run nav2_map_server map_saver_cli -f "$prefix" --ros-args -p map_subscribe_transient_local:=true
echo "Saved ${prefix}.yaml and ${prefix}.pgm"
echo "If using slam_toolbox localization later, serialize its pose graph separately:"
echo "  ros2 service call /slam_toolbox/serialize_map slam_toolbox/srv/SerializePoseGraph \"{filename: '${prefix}.posegraph'}\""
