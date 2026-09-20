from __future__ import annotations

import getpass
import time
import paramiko


password = getpass.getpass("Robot SSH password: ")


def run(client: paramiko.SSHClient, command: str, input_text: str | None = None, timeout: int = 25) -> str:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    if input_text is not None:
        stdin.write(input_text)
        stdin.channel.shutdown_write()
    result = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"{command}: exit={status}, stdout={result[:300]}, stderr={error[:300]}")
    return result.strip()


kill_code = r'''
import os
import signal

targets = []
for name in os.listdir('/proc'):
    if not name.isdigit():
        continue
    try:
        args = open(f'/proc/{name}/cmdline', 'rb').read().decode(errors='replace').split('\0')
    except (OSError, PermissionError):
        continue
    if len(args) < 2:
        continue
    if args[0] in ('/usr/bin/python3', '/usr/bin/python') and args[1] == '/opt/ros/humble/bin/ros2' and 'localization.launch.py' in args:
        targets.append(int(name))
for pid in targets:
    try:
        os.kill(pid, signal.SIGINT)
        print(f'sent SIGINT to localization launch {pid}', flush=True)
    except ProcessLookupError:
        pass
'''


for index in range(1, 5):
    host = f"192.168.1.{200 + index}"
    service = "mentorpi-localization-vendor-domain" if index in (1, 4) else "mentorpi-localization"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username="pi", password=password, timeout=8)
    print(f"robot{index}: stop {service}", flush=True)
    run(client, f"sudo systemctl stop {service}")
    print(f"robot{index}: {run(client, 'docker exec -i MentorPi python3 -', kill_code)}", flush=True)
    time.sleep(3)
    status = run(client, "docker exec MentorPi bash -lc 'ps -eo args | grep -E \"localization.launch.py|nav2_map_server/map_server|nav2_amcl/amcl\" | grep -v grep || true'")
    if status:
        raise RuntimeError(f"robot{index}: localization processes remained: {status[:500]}")
    run(client, f"sudo systemctl start {service}")
    time.sleep(3)
    active = run(client, f"systemctl is-active {service}")
    count = run(client, "docker exec MentorPi bash -lc 'pgrep -fc \"^/opt/ros/humble/lib/nav2_map_server/map_server\" || true'")
    print(f"robot{index}: service={active}, map_server_count={count}", flush=True)
    client.close()
