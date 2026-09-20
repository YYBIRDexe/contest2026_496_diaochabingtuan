#!/usr/bin/env bash
set -euo pipefail

for robot in robot01 robot02 robot03 robot04; do
  ros2 run mentorpi_formation_bringup hardware_probe \
    --namespace "$robot" --require-localization --allow-command-publishers
done
ros2 run mentorpi_formation_bringup tf_audit --timeout 8
