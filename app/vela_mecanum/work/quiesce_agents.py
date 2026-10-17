"""Temporarily stop only formation agents to recover the congested WLAN."""

from pathlib import Path
import socket
import time

import paramiko


BASE = Path(__file__).resolve().parents[1]
KEY = BASE / "work" / "keys" / "formation_autonomy_ed25519"
HOST_KEYS = BASE / "work" / "keys" / "formation_known_hosts"


def connect(index: int) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_host_keys(str(HOST_KEYS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        f"192.168.1.{200 + index}", username="pi", key_filename=str(KEY),
        timeout=35, banner_timeout=35, auth_timeout=35,
    )
    client.get_transport().set_keepalive(3)
    return client


for index in range(1, 5):
    robot = f"robot{index}"
    pattern = f"^python3 /opt/openvela-formation/formation_lab/reconfiguration_agent[.]py --robot-id {robot}$"
    command = (
        f"sudo -n systemctl stop formation-agent@{robot}.service || true; "
        f"sudo -n docker exec MentorPi pkill -INT -f '{pattern}' || true; "
        "sleep 3; "
        f"test \"$(sudo -n docker exec MentorPi pgrep -fc '{pattern}')\" -eq 0"
    )
    for attempt in range(1, 13):
        client = None
        try:
            print(f"{robot}: quiesce attempt {attempt}", flush=True)
            client = connect(index)
            _, stdout, stderr = client.exec_command(command, timeout=45)
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            status = stdout.channel.recv_exit_status()
            print(f"{robot}: status={status} out={out!r} err={err!r}", flush=True)
            if status == 0:
                break
        except (OSError, EOFError, socket.timeout, paramiko.SSHException) as exc:
            print(f"{robot}: {exc!r}", flush=True)
        finally:
            if client is not None:
                client.close()
        time.sleep(min(12, 2 + attempt))
    else:
        raise RuntimeError(f"could not quiesce {robot}")
