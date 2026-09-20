import getpass
import json
import paramiko
from pathlib import Path

password = getpass.getpass("Robot SSH password: ")
out = Path(__file__).resolve().parent / "audit_after_teammate"
files = [
    "/opt/openvela-formation/formation_lab/formation_planner.py",
    "/opt/openvela-formation/formation_lab/reconfiguration_session.py",
    "/opt/openvela-formation/formation_lab/reconfiguration_ros.py",
    "/opt/openvela-formation/formation_lab/reconfiguration_agent.py",
    "/opt/openvela-formation/formation_lab/mentorpi_agent.py",
    "/opt/openvela-formation/formation_lab/command_bridge.py",
]
for index in range(1, 5):
    robot = f"robot{index}"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(f"192.168.1.{200+index}", username="pi", password=password, timeout=8)
        commands = {
            "identity": "hostname; date -Is; uptime; docker ps --format '{{.Names}} {{.Status}}'",
            "services": f"systemctl is-active formation-agent@{robot}.service formation-command-bridge@{robot}.service formation-reconfiguration.service",
            "files": "docker exec MentorPi sha256sum " + " ".join(files),
            "processes": "docker exec MentorPi ps -eo pid,args | grep -E 'reconfiguration|formation_agent|command_bridge|amcl|map_server' | grep -v grep || true",
            "ntp": "timedatectl show -p NTPSynchronized -p NTP -p Timezone; systemctl is-active fleet-ntp.service || true",
        }
        if index == 1:
            commands["ros_topics"] = "docker exec -u ubuntu -e ROS_DOMAIN_ID=42 MentorPi bash -lc 'source /opt/ros/humble/setup.bash; timeout 12 ros2 topic list | grep -E \"reconfiguration|amcl_pose|scan_raw|command_bridge_status\"'"
            commands["scan_qos"] = "docker exec -u ubuntu -e ROS_DOMAIN_ID=42 MentorPi bash -lc 'source /opt/ros/humble/setup.bash; timeout 12 ros2 topic info -v /robot1/scan_raw'"
        results = {}
        for name, command in commands.items():
            try:
                _, stdout, stderr = client.exec_command(command, timeout=20)
                results[name] = {"stdout": stdout.read().decode(errors="replace"), "stderr": stderr.read().decode(errors="replace"), "exit": stdout.channel.recv_exit_status()}
            except Exception as exc:
                results[name] = {"error": str(exc)}
            print(robot, name, results[name].get("exit", "error"), flush=True)
        (out / f"{robot}_detail.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    finally:
        client.close()
