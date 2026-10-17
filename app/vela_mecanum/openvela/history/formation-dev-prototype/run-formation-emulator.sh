#!/usr/bin/env bash

set -o pipefail
cd /home/vela/openvela || exit 125
exec ./emulator.sh cmake_out/vela_goldfish-arm64-v8a-ap-formation/ \
  -no-window \
  -no-audio \
  -no-snapshot \
  -gpu swiftshader_indirect \
  -accel off \
  >> /home/vela/openvela-formation-emulator.log 2>&1
