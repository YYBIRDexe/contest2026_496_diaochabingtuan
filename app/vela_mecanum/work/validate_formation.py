from __future__ import annotations

import getpass
import paramiko


password = getpass.getpass("Robot SSH password: ")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.1.201", username="pi", password=password, timeout=8)
code = r'''
import time
from formation_lab.formation_once import build_relative_mission, validate_geometry

poses = {
    'robot1': (-2.529, -0.771, -0.076),
    'robot2': (-2.544, 0.021, -0.108),
    'robot3': (-2.556, -0.496, -0.094),
    'robot4': (-2.550, -0.213, -0.094),
}
for formation in ('square', 'line', 'circle', 'diamond'):
    mission = build_relative_mission(poses, 0.1, 5, formation, 0.5, 'anchored', 'preflight', time.time())
    try:
        validate_geometry(poses, mission, 3.0, 0.25, 0.4)
        outcome = 'PASS'
    except Exception as exc:
        outcome = f'REJECT: {exc}'
    try:
        validate_geometry(poses, mission, 3.0, 0.0, 0.4)
        travel = 'target travel within 0.4 m'
    except Exception as exc:
        travel = f'target issue: {exc}'
    print(f'{formation}: {outcome}; {travel}')
'''
stdin, stdout, stderr = client.exec_command(
    "docker exec -i -u ubuntu -e PYTHONPATH=/opt/openvela-formation MentorPi python3 -",
    timeout=20,
)
stdin.write(code)
stdin.channel.shutdown_write()
print(stdout.read().decode(errors="replace"), end="")
print(stderr.read().decode(errors="replace"), end="")
client.close()
