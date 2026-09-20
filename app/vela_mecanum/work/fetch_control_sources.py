from __future__ import annotations

import getpass
from pathlib import Path
import paramiko

out = Path(__file__).resolve().parent / "control_sources"
out.mkdir(parents=True, exist_ok=True)
password = getpass.getpass("Robot SSH password: ")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.1.201", username="pi", password=password, timeout=8)
files = {
    "command_bridge.py": "/opt/openvela-formation/formation_lab/command_bridge.py",
    "mentorpi_agent.py": "/opt/openvela-formation/formation_lab/mentorpi_agent.py",
    "formation_once.py": "/opt/openvela-formation/formation_lab/formation_once.py",
    "agent.py": "/opt/openvela-formation/formation_lab/agent.py",
    "command_gate.py": "/opt/openvela-formation/formation_lab/command_gate.py",
    "cmd_vel_watchdog.py": "/home/ubuntu/shared/cmd_vel_watchdog.py",
    "mentorpi.json": "/opt/openvela-formation/config/mentorpi.json",
}
for name, path in files.items():
    _, stdout, stderr = client.exec_command(f"docker exec MentorPi cat {path}", timeout=10)
    body = stdout.read()
    error = stderr.read()
    if stdout.channel.recv_exit_status() != 0:
        raise RuntimeError(f"{path}: {error[:300]!r}")
    (out / name).write_bytes(body)
    print(f"{name}: {len(body)} bytes", flush=True)
client.close()
