#!/usr/bin/env bash
set -eo pipefail

lab_root=${LAB_ROOT:-/home/vela/formation-lab}
workspace="$lab_root/ros2_ws"
log=${ACCEPTANCE_LOG:-/home/vela/mentorpi-ros2-virtual-acceptance.log}
exec > >(tee -a "$log") 2>&1

source /opt/ros/humble/setup.bash
source "$workspace/install/setup.bash"
export PYTHONPATH="$lab_root${PYTHONPATH:+:$PYTHONPATH}"
set -u

cleanup() {
  for robot in Robot01 Robot02 Robot03 Robot04; do
    systemctl --user stop "mentorpi-agent-$robot.service" >/dev/null 2>&1 || true
  done
  systemctl --user stop mentorpi-virtual-fleet.service >/dev/null 2>&1 || true
}
trap cleanup EXIT

start_fleet() {
  systemctl --user stop mentorpi-virtual-fleet.service >/dev/null 2>&1 || true
  systemd-run --user --unit=mentorpi-virtual-fleet --collect \
    /bin/bash -lc "source /opt/ros/humble/setup.bash; source '$workspace/install/setup.bash'; exec ros2 run mentorpi_formation_bringup virtual_fleet"
  sleep 2
}

config=/tmp/mentorpi-virtual-acceptance.json
cp "$lab_root/config/mentorpi.json" "$config"
sed -i 's/"hardware_output_enabled": false/"hardware_output_enabled": true/' "$config"

echo "=== CZ225 ROS2 virtual acceptance $(date -Is) ==="
start_fleet
ros2 run mentorpi_formation_bringup hardware_probe --namespace robot01 --require-localization
ros2 run mentorpi_formation_bringup tf_audit --timeout 6

for robot in Robot01 Robot02 Robot03 Robot04; do
  systemd-run --user --unit="mentorpi-agent-$robot" --collect \
    /bin/bash -lc "source /opt/ros/humble/setup.bash; source '$workspace/install/setup.bash'; export PYTHONPATH='$lab_root':\$PYTHONPATH; exec python3 -m formation_lab.mentorpi_agent --robot-id '$robot' --config '$config'"
done
sleep 2
ros2 run mentorpi_formation_bringup virtual_acceptance --control-mode laplacian --timeout 25 --tolerance 0.10

start_fleet
sleep 1
ros2 run mentorpi_formation_bringup virtual_acceptance --control-mode second_order --timeout 30 --tolerance 0.12
echo "=== CZ225_ROS2_VIRTUAL_ACCEPTANCE_PASS ==="
