from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import time

import paramiko


BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "outputs" / "formation-kit" / "payload" / "baseline_robot1" / "command_gate.py"
KEY = BASE / "work" / "keys" / "formation_autonomy_ed25519"
HOST_KEYS = BASE / "work" / "keys" / "formation_known_hosts"
REMOTE = "/opt/openvela-formation/formation_lab/command_gate.py"


def connect(index: int) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_host_keys(str(HOST_KEYS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        f"192.168.1.{200 + index}", username="pi", key_filename=str(KEY),
        look_for_keys=False, allow_agent=False, timeout=10, auth_timeout=10,
    )
    return client


def run(client: paramiko.SSHClient, command: str, timeout: int = 30) -> str:
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(error[-500:] or output[-500:])
    return output.strip()


def main() -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    expected = sha256(SOURCE.read_bytes()).hexdigest()
    for index in range(1, 5):
        robot = f"robot{index}"
        client = connect(index)
        try:
            run(client, "test ! -e /run/openvela-formation/command-arm.json")
            sftp = client.open_sftp()
            sftp.put(str(SOURCE), "/home/pi/command_gate.py")
            sftp.close()
            run(client, f"docker exec MentorPi cp -a {REMOTE} {REMOTE}.bak-{stamp}")
            run(client, f"docker cp /home/pi/command_gate.py MentorPi:{REMOTE}")
            run(client, f"docker exec MentorPi python3 -m py_compile {REMOTE}")
            digest = run(client, f"docker exec MentorPi sha256sum {REMOTE}").split()[0]
            if digest != expected:
                raise RuntimeError(f"{robot}: command gate hash mismatch")
            run(client, f"sudo -n systemctl restart formation-command-bridge@{robot}.service")
            states = run(client, f"systemctl is-active formation-agent@{robot}.service formation-command-bridge@{robot}.service")
            if states.splitlines() != ["active", "active"]:
                raise RuntimeError(f"{robot}: services are not active")
            run(client, "test ! -e /run/openvela-formation/command-arm.json")
            print(f"{robot}: race command gate installed, backup={stamp}", flush=True)
        finally:
            client.close()
    print("RACE_GATE_OK: no motion lease created", flush=True)


if __name__ == "__main__":
    main()
