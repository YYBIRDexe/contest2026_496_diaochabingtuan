from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
KEY = ROOT / "work" / "keys" / "formation_autonomy_ed25519"
HOST_KEYS = ROOT / "work" / "keys" / "formation_known_hosts"


def run(client: paramiko.SSHClient, command: str, timeout: int = 20) -> str:
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"command failed with exit {code}: {error[-500:] or output[-500:]}")
    return output.strip()


def main() -> None:
    for index in range(1, 5):
        robot = f"robot{index}"
        client = paramiko.SSHClient()
        client.load_host_keys(str(HOST_KEYS))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            f"192.168.1.{200 + index}", username="pi", key_filename=str(KEY),
            look_for_keys=False, allow_agent=False, timeout=15, auth_timeout=15,
        )
        try:
            states = run(
                client,
                f"systemctl is-active formation-agent@{robot}.service "
                f"formation-command-bridge@{robot}.service",
            ).splitlines()
            if states != ["active", "active"]:
                raise RuntimeError(f"{robot}: required service state is {states}")
            agent_count = run(
                client,
                "docker exec MentorPi pgrep -fc "
                f"'^python3 /opt/openvela-formation/formation_lab/reconfiguration_agent[.]py --robot-id {robot}$'",
            )
            if agent_count != "1":
                raise RuntimeError(f"{robot}: agent_count={agent_count}")
            lease = run(
                client,
                "docker exec MentorPi sh -c 'test ! -e /run/openvela-formation/command-arm.json && echo absent'",
            )
            config = run(
                client,
                "docker exec MentorPi python3 -c 'import json; "
                "d=json.load(open(\"/opt/openvela-formation/config/mentorpi.json\")); "
                "print(d[\"hardware_output_enabled\"],d[\"limits\"][\"max_linear_mps\"],"
                "d[\"limits\"][\"max_acceleration_mps2\"])'",
            )
            bridge = run(
                client,
                "docker exec -u ubuntu -e ROS_DOMAIN_ID=42 MentorPi bash -lc '"
                "source /opt/ros/humble/setup.bash; timeout 7 ros2 topic echo "
                f"/{robot}/formation/command_bridge_status std_msgs/msg/String --once'",
                timeout=12,
            )
            if '"armed":false' not in bridge or '"forwarding":false' not in bridge:
                raise RuntimeError(f"{robot}: bridge status does not show disarmed idle state: {bridge}")
            pose = run(
                client,
                "docker exec -u ubuntu -e ROS_DOMAIN_ID=42 MentorPi bash -lc '"
                "source /opt/ros/humble/setup.bash; timeout 7 ros2 topic echo "
                f"/{robot}/amcl_pose geometry_msgs/msg/PoseWithCovarianceStamped --once'",
                timeout=12,
            )
            scan = run(
                client,
                "docker exec -u ubuntu -e ROS_DOMAIN_ID=42 MentorPi bash -lc '"
                "source /opt/ros/humble/setup.bash; timeout 7 ros2 topic echo "
                f"/{robot}/scan_raw sensor_msgs/msg/LaserScan --once'",
                timeout=12,
            )
            if "frame_id:" not in pose or "ranges:" not in scan:
                raise RuntimeError(f"{robot}: localization or lidar message is incomplete")
            print(
                f"{robot}: services=active agent_count=1 lease={lease} config={config} "
                "bridge=disarmed pose=received scan=received",
                flush=True,
            )
        finally:
            client.close()
    print("STATIONARY_ACCEPTANCE_OK", flush=True)


if __name__ == "__main__":
    main()
