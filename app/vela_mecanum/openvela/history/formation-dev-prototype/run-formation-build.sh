#!/usr/bin/env bash

set -o pipefail

marker=/home/vela/OPENVELA_FORMATION_BUILD_DONE
log=/home/vela/openvela-formation-build.log
duration_file=/home/vela/openvela-formation-build-seconds
rm -f "$marker"
start=$(date +%s)
echo "=== VERIFIED_BUILD_ATTEMPT_$(date -Is) ===" | tee -a "$log"
{
  cd /home/vela/openvela || exit 125
  ./build.sh vendor/openvela/boards/vela/configs/goldfish-arm64-v8a-ap-formation/ --cmake -j4
} 2>&1 | tee -a "$log"
rc=${PIPESTATUS[0]}
end=$(date +%s)
echo $((end - start)) > "$duration_file"
echo "=== VERIFIED_BUILD_EXIT_${rc}_DURATION_$((end - start))s ===" | tee -a "$log"
if [ "$rc" -eq 0 ]; then
  touch "$marker"
fi
exit "$rc"
