from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import posixpath
import time

import paramiko


BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "outputs" / "formation-kit" / "payload" / "planner"
KEY = BASE / "work" / "keys" / "formation_autonomy_ed25519"
HOST_KEYS = BASE / "work" / "keys" / "formation_known_hosts"
REMOTE_ROOT = "/opt/openvela-formation/formation_lab"
FILES = (
    "formation_planner.py",
    "reconfiguration_session.py",
    "reconfiguration_agent.py",
    "fleet_endpoint.py",
    "auto_localize.py",
    "scan_localizer.py",
)


def connect(index: int) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_host_keys(str(HOST_KEYS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        f"192.168.1.{200 + index}",
        username="pi",
        key_filename=str(KEY),
        look_for_keys=False,
        allow_agent=False,
        timeout=10,
        auth_timeout=10,
    )
    return client


def run(client: paramiko.SSHClient, command: str, timeout: int = 30) -> str:
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"remote command failed: {command}: {error[-600:] or output[-600:]}")
    return output.strip()


def main() -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    expected = {name: sha256((SOURCE / name).read_bytes()).hexdigest() for name in FILES}
    for index in range(1, 5):
        client = connect(index)
        try:
            robot = f"robot{index}"
            run(client, "test ! -e /run/openvela-formation/command-arm.json")
            states = run(client, f"systemctl is-active formation-agent@{robot}.service formation-command-bridge@{robot}.service")
            if states.splitlines() != ["active", "active"]:
                raise RuntimeError(f"{robot}: required services are not active: {states}")
            enabled = run(client, "docker exec MentorPi python3 -c 'import json; print(json.load(open(\"/opt/openvela-formation/config/mentorpi.json\"))[\"hardware_output_enabled\"])'")
            if enabled != "True":
                raise RuntimeError(f"{robot}: hardware output gate is not enabled")
            count = run(client, "docker exec MentorPi sh -c \"ps -eo args | awk '/reconfiguration_agent.py/ && !/awk/ && !/grep/ {count++} END {print count+0}'\"")
            if count != "1":
                raise RuntimeError(f"{robot}: expected one agent before deployment, found {count}")
            stage = f"/home/pi/formation-update-{stamp}"
            run(client, f"mkdir -p {stage}")
            sftp = client.open_sftp()
            for name in FILES:
                sftp.put(str(SOURCE / name), posixpath.join(stage, name))
            sftp.close()
            for name in FILES:
                target = f"{REMOTE_ROOT}/{name}"
                backup = f"{target}.bak-{stamp}"
                run(client, f"docker exec MentorPi sh -c 'cp -a {target} {backup}'")
                run(client, f"docker cp {stage}/{name} MentorPi:{target}")
            run(client, "docker exec MentorPi python3 -m py_compile " + " ".join(f"{REMOTE_ROOT}/{name}" for name in FILES))
            hashes = run(client, "docker exec MentorPi sha256sum " + " ".join(f"{REMOTE_ROOT}/{name}" for name in FILES))
            actual = {Path(line.split()[-1]).name: line.split()[0] for line in hashes.splitlines()}
            if actual != expected:
                raise RuntimeError(f"{robot}: installed hashes do not match tested sources: {actual}")
            run(client, f"sudo -n systemctl restart formation-agent@{robot}.service")
            if run(client, f"systemctl is-active formation-agent@{robot}.service") != "active":
                raise RuntimeError(f"{robot}: agent did not return active")
            run(client, "test ! -e /run/openvela-formation/command-arm.json")
            count = run(client, "docker exec MentorPi sh -c \"ps -eo args | awk '/reconfiguration_agent.py/ && !/awk/ && !/grep/ {count++} END {print count+0}'\"")
            if count != "1":
                raise RuntimeError(f"{robot}: expected one agent after deployment, found {count}")
            print(f"{robot}: six formation files installed, compiled, hashed, agent active, backup={stamp}", flush=True)
        finally:
            client.close()
    print("DEPLOYMENT_OK: no motion lease created", flush=True)


if __name__ == "__main__":
    main()
