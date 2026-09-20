from __future__ import annotations

import getpass
from pathlib import Path
import paramiko
import sys


OUT = Path(__file__).resolve().parent / "robot_data"
OUT.mkdir(parents=True, exist_ok=True)
password = getpass.getpass("Robot SSH password: ")
poses_only = "--poses-only" in sys.argv

for index in range(1, 5):
    host = f"192.168.1.{200 + index}"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username="pi", password=password, timeout=8)
    print(f"Connected robot{index}", flush=True)
    if index == 1 and not poses_only:
        sftp = client.open_sftp()
        sftp.get("/opt/openvela-formation/maps/classroom.pgm", str(OUT / "classroom.pgm"))
        sftp.get("/opt/openvela-formation/maps/classroom.yaml", str(OUT / "classroom.yaml"))
        sftp.close()
    for topic in (("amcl_pose",) if poses_only else ("scan_raw", "amcl_pose")):
        command = (
            f"docker exec -u ubuntu -e ROS_DOMAIN_ID={index} MentorPi "
            "bash -lc 'source /opt/ros/humble/setup.bash; "
            f"timeout 12 ros2 topic echo --once {'--full-length ' if topic == 'scan_raw' else ''}/{topic}'"
        )
        _, stdout, stderr = client.exec_command(command, timeout=18)
        body = stdout.read().decode(errors="replace")
        error = stderr.read().decode(errors="replace")
        (OUT / f"robot{index}_{topic}.txt").write_text(body, encoding="utf-8")
        print(f"robot{index} {topic}: {len(body)} bytes, error={error[:120]!r}", flush=True)
    client.close()
