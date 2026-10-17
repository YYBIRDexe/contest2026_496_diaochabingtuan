"""Deploy the tested fleet endpoint serialization fix without restarting services."""

from datetime import datetime
import hashlib
import json
from pathlib import Path

import paramiko


BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "outputs/formation-kit/payload/planner/fleet_endpoint.py"
KEY = BASE / "work/keys/formation_autonomy_ed25519"
HOST_KEYS = BASE / "work/keys/formation_known_hosts"
REMOTE = "/opt/openvela-formation/formation_lab/fleet_endpoint.py"
LEASE = "/run/openvela-formation/command-arm.json"


def connect(index: int) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_host_keys(str(HOST_KEYS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(f"192.168.1.{200 + index}", username="pi", key_filename=str(KEY),
                   look_for_keys=False, allow_agent=False, timeout=20, auth_timeout=20)
    return client


def run(client: paramiko.SSHClient, command: str, timeout: int = 45) -> str:
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(json.dumps({"command": command, "exit": code, "stdout": out, "stderr": err}, ensure_ascii=False))
    return out


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    expected = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    for index in range(1, 5):
        robot = f"robot{index}"
        client = connect(index)
        try:
            run(client, f"if docker exec MentorPi test -e {LEASE}; then exit 40; else echo no_lease; fi")
        finally:
            client.close()
    for index in range(1, 5):
        robot = f"robot{index}"
        client = connect(index)
        try:
            sftp = client.open_sftp()
            sftp.put(str(SOURCE), "/tmp/fleet_endpoint.py")
            sftp.close()
            backup = f"/opt/openvela-formation/backups/fleet-endpoint-bool-{stamp}"
            output = run(
                client,
                f"if docker exec MentorPi test -e {LEASE}; then exit 40; fi; "
                f"sudo -n install -d -m 0755 {backup}; sudo -n cp -a {REMOTE} {backup}/fleet_endpoint.py; "
                "sudo -n docker cp /tmp/fleet_endpoint.py MentorPi:/tmp/fleet_endpoint.py; rm -f /tmp/fleet_endpoint.py; "
                "sudo -n docker exec MentorPi python3 -m py_compile /tmp/fleet_endpoint.py; "
                f"sudo -n docker exec MentorPi install -o ubuntu -g ubuntu -m 0644 /tmp/fleet_endpoint.py {REMOTE}; "
                "sudo -n docker exec MentorPi rm -f /tmp/fleet_endpoint.py; "
                f"docker exec MentorPi sha256sum {REMOTE}; "
                f"if docker exec MentorPi test -e {LEASE}; then exit 41; else echo no_lease; fi",
            )
            if expected not in output:
                raise RuntimeError(f"{robot}: checksum mismatch")
            print(f"{robot}: endpoint verified, no service restart, no lease", flush=True)
        finally:
            client.close()


if __name__ == "__main__":
    main()
