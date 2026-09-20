from pathlib import Path
import getpass
import paramiko

out = Path(__file__).resolve().parent / "audit_after_teammate" / "source"
password = getpass.getpass("Robot SSH password: ")
for index in range(1, 5):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(f"192.168.1.{200+index}", username="pi", password=password, timeout=8)
    robot = f"robot{index}"
    directory = out / robot
    directory.mkdir(parents=True, exist_ok=True)
    try:
        for name in ("formation_planner.py", "reconfiguration_session.py", "reconfiguration_ros.py", "reconfiguration_agent.py"):
            command = f"docker exec MentorPi cat /opt/openvela-formation/formation_lab/{name}"
            _, stdout, stderr = client.exec_command(command, timeout=12)
            body = stdout.read()
            if stdout.channel.recv_exit_status():
                print(robot, name, "ERROR", stderr.read().decode(errors="replace")[:150], flush=True)
            else:
                (directory / name).write_bytes(body)
        print(robot, "downloaded", flush=True)
    finally:
        client.close()
