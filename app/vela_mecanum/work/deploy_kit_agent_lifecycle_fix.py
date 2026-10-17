"""Deploy the tested formation-kit agent sequentially with backups and no lease."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

import paramiko


BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "outputs/formation-kit/payload/planner/reconfiguration_agent.py"
KEY = BASE / "work/keys/formation_autonomy_ed25519"
HOST_KEYS = BASE / "work/keys/formation_known_hosts"
OUT = BASE / "work/agent-network-audit"
REMOTE = "/opt/openvela-formation/formation_lab/reconfiguration_agent.py"
LEASE = "/run/openvela-formation/command-arm.json"


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
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )
    client.get_transport().set_keepalive(5)
    return client


def run(client: paramiko.SSHClient, command: str, timeout: int = 45) -> dict:
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(json.dumps({"command": command, "exit": status, "stdout": out, "stderr": err}, ensure_ascii=False))
    return {"command": command, "exit": status, "stdout": out, "stderr": err}


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    expected = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    report = {"stamp": stamp, "expected_sha256": expected, "robots": {}}
    OUT.mkdir(parents=True, exist_ok=True)

    # Refuse the entire deployment before touching any car if a lease exists or
    # either required service is not active on any member of the fleet.
    for index in range(1, 5):
        robot = f"robot{index}"
        client = connect(index)
        try:
            run(
                client,
                f"test \"$(systemctl is-active formation-agent@{robot}.service)\" = active; "
                f"test \"$(systemctl is-active formation-command-bridge@{robot}.service)\" = active; "
                f"if docker exec MentorPi test -e {LEASE}; then exit 40; else echo no_lease; fi",
            )
            print(f"{robot}: preflight active, no lease", flush=True)
        finally:
            client.close()

    for index in range(1, 5):
        robot = f"robot{index}"
        print(f"{robot}: deploying", flush=True)
        client = connect(index)
        steps = []
        try:
            sftp = client.open_sftp()
            sftp.put(str(SOURCE), "/tmp/reconfiguration_agent.py")
            sftp.close()
            backup = f"/opt/openvela-formation/backups/formation-kit-agent-{stamp}"
            steps.append(
                run(
                    client,
                    f"if docker exec MentorPi test -e {LEASE}; then exit 40; fi; "
                    f"sudo -n install -d -m 0755 {backup}; "
                    f"sudo -n cp -a {REMOTE} {backup}/reconfiguration_agent.py; "
                    "sudo -n docker cp /tmp/reconfiguration_agent.py MentorPi:/tmp/reconfiguration_agent.py; "
                    "rm -f /tmp/reconfiguration_agent.py; "
                    "sudo -n docker exec MentorPi python3 -m py_compile /tmp/reconfiguration_agent.py; "
                    f"sudo -n docker exec MentorPi install -o ubuntu -g ubuntu -m 0644 /tmp/reconfiguration_agent.py {REMOTE}; "
                    "sudo -n docker exec MentorPi rm -f /tmp/reconfiguration_agent.py; "
                    f"sudo -n systemctl restart formation-agent@{robot}.service",
                    timeout=60,
                )
            )
            time.sleep(3)
            verify = run(
                client,
                f"test \"$(systemctl is-active formation-agent@{robot}.service)\" = active; "
                f"test \"$(systemctl is-active formation-command-bridge@{robot}.service)\" = active; "
                f"test \"$(docker exec MentorPi pgrep -fc '^python3 {REMOTE.replace('.py', '[.]py')} --robot-id {robot}$')\" -eq 1; "
                f"docker exec MentorPi sha256sum {REMOTE}; "
                f"systemctl show formation-agent@{robot}.service -p ActiveState -p SubState -p MainPID -p Result -p NRestarts; "
                f"if docker exec MentorPi test -e {LEASE}; then exit 41; else echo no_lease; fi; "
                f"journalctl -u formation-agent@{robot}.service --since '-90 seconds' --no-pager --output=cat | tail -n 20",
            )
            steps.append(verify)
            if expected not in verify["stdout"]:
                raise RuntimeError(f"{robot}: checksum mismatch")
            report["robots"][robot] = {"backup": backup, "steps": steps, "ok": True}
            print(f"{robot}: verified active, one instance, no lease", flush=True)
        finally:
            client.close()

    path = OUT / f"formation-kit-agent-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
