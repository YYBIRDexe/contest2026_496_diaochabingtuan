#!/usr/bin/env bash
set -euo pipefail

robot_id=${1:-}
container_user=${2:-ubuntu}
container=${MENTORPI_CONTAINER:-MentorPi}
case "$robot_id" in
  Robot01|Robot02|Robot03|Robot04) ;;
  *) echo "usage: sudo ./deploy/install_on_robot.sh Robot01 [container_user]" >&2; exit 2 ;;
esac
if [ "$(id -u)" -ne 0 ]; then
  echo "run this installer with sudo" >&2
  exit 2
fi

command -v docker >/dev/null
docker inspect "$container" >/dev/null
test "$(docker inspect -f '{{.State.Running}}' "$container")" = true
if [ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$container")" != host ]; then
  echo "container $container must use host networking for the vendor ROS 2 stack" >&2
  exit 2
fi
docker exec "$container" test -f /opt/ros/humble/setup.bash
docker exec "$container" id "$container_user" >/dev/null

deploy_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
bundle_root=$(cd "$deploy_dir/.." && pwd)
container_home=$(docker exec "$container" getent passwd "$container_user" | cut -d: -f6 | tr -d '\r')
vendor_ws="$container_home/ros2_ws"
package_source="$bundle_root/ros2_ws/src/mentorpi_formation_bringup"
package_target="$vendor_ws/src/mentorpi_formation_bringup"
formation_root=/opt/openvela-formation

docker exec "$container" test -d "$vendor_ws/src"
test -f "$package_source/package.xml"
docker exec "$container" mkdir -p "$package_target"
docker cp "$package_source/." "$container:$package_target"
docker exec "$container" chown -R "$container_user:$container_user" "$package_target"

docker exec --user "$container_user" --workdir "$container_home" \
  --env VENDOR_WS="$vendor_ws" "$container" /bin/bash -lc '
    set -eo pipefail
    source /opt/ros/humble/setup.bash
    if [ -f /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash ]; then
      source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash
    fi
    if [ -f "$VENDOR_WS/install/setup.bash" ]; then source "$VENDOR_WS/install/setup.bash"; fi
    cd "$VENDOR_WS"
    colcon build --symlink-install --packages-select mentorpi_formation_bringup
  '

docker exec "$container" mkdir -p \
  "$formation_root/formation_lab" "$formation_root/config" "$formation_root/maps"
docker cp "$bundle_root/formation_lab/formation_lab/." "$container:$formation_root/formation_lab"
docker cp "$bundle_root/formation_lab/config/mentorpi.json" "$container:$formation_root/config/mentorpi.json"
docker exec "$container" chown -R "$container_user:$container_user" "$formation_root"
docker exec "$container" sed -i \
  's/"hardware_output_enabled": true/"hardware_output_enabled": false/' \
  "$formation_root/config/mentorpi.json"

install -d /opt/openvela-formation/scripts
install -m 0755 "$deploy_dir/run_formation_agent.sh" /opt/openvela-formation/scripts/run_formation_agent.sh
install -m 0755 "$deploy_dir/run_localization.sh" /opt/openvela-formation/scripts/run_localization.sh
install -m 0755 "$deploy_dir/enable_formation_agent.sh" /opt/openvela-formation/scripts/enable_formation_agent.sh
install -m 0755 "$deploy_dir/disable_formation_agent.sh" /opt/openvela-formation/scripts/disable_formation_agent.sh
install -m 0755 "$deploy_dir/run_distance_mission.sh" /opt/openvela-formation/scripts/run_distance_mission.sh
install -m 0755 "$deploy_dir/stop_distance_mission.sh" /opt/openvela-formation/scripts/stop_distance_mission.sh
install -m 0755 "$deploy_dir/run_orbit_mission.sh" /opt/openvela-formation/scripts/run_orbit_mission.sh
install -m 0755 "$deploy_dir/stop_orbit_mission.sh" /opt/openvela-formation/scripts/stop_orbit_mission.sh
install -m 0644 "$deploy_dir/formation-agent@.service" /etc/systemd/system/formation-agent@.service
install -m 0644 "$deploy_dir/mentorpi-localization.service" /etc/systemd/system/mentorpi-localization.service
install -m 0644 "$deploy_dir/mentorpi-distance-mission.service" /etc/systemd/system/mentorpi-distance-mission.service
install -m 0644 "$deploy_dir/mentorpi-orbit-mission.service" /etc/systemd/system/mentorpi-orbit-mission.service

robot_namespace=$(printf '%s' "$robot_id" | tr '[:upper:]' '[:lower:]')
{
  echo "ROBOT_ID=$robot_id"
  echo "ROBOT_NAMESPACE=$robot_namespace"
  echo "MENTORPI_CONTAINER=$container"
  echo "MENTORPI_CONTAINER_USER=$container_user"
  echo "MENTORPI_CONTAINER_HOME=$container_home"
  echo "MENTORPI_VENDOR_WS=$vendor_ws"
  echo "MENTORPI_FORMATION_ROOT=$formation_root"
  echo "MAP_YAML=$formation_root/maps/classroom.yaml"
  # Stock MentorPi bringup currently runs in domain 0. Change both together.
  echo "ROS_DOMAIN_ID=0"
  echo "ROS_LOCALHOST_ONLY=0"
} >/etc/default/openvela-formation
printf '%s\n' "$robot_id" >/etc/openvela-formation-robot-id

systemctl daemon-reload
systemctl disable --now "formation-agent@$robot_id.service" mentorpi-localization.service mentorpi-distance-mission.service mentorpi-orbit-mission.service >/dev/null 2>&1 || true

echo "Installed in Docker container $container for $robot_id ($robot_namespace)."
echo "ROS_DOMAIN_ID remains 0 to match the stock vendor bringup."
echo "Hardware output and localization remain disabled."
echo "Do not enable formation control until vendor topics and TF frames are uniquely namespaced."
