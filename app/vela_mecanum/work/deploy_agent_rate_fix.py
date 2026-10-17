"""Deploy the reviewed agent signal/rate fix sequentially with backups."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

import paramiko


BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "work/audit_after_teammate/source/robot1/reconfiguration_agent.py"
KEY = BASE / "work/keys/formation_autonomy_ed25519"
HOST_KEYS = BASE / "work/keys/formation_known_hosts"
OUT = BASE / "work/agent-network-audit"
REMOTE = "/opt/openvela-formation/formation_lab/reconfiguration_agent.py"


def connect(index):
    c = paramiko.SSHClient()
    c.load_host_keys(str(HOST_KEYS))
    c.set_missing_host_key_policy(paramiko.RejectPolicy())
    c.connect(f"192.168.1.{200+index}", username="pi", key_filename=str(KEY), timeout=20,
              banner_timeout=20, auth_timeout=20)
    c.get_transport().set_keepalive(5)
    return c


def run(c, command, timeout=45):
    _, stdout, stderr = c.exec_command(command, timeout=timeout)
    out, err = stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(json.dumps({"command": command, "exit": status, "stdout": out, "stderr": err}, ensure_ascii=False))
    return {"command": command, "exit": status, "stdout": out, "stderr": err}


def main():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    expected = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    report = {"stamp": stamp, "expected_sha256": expected, "robots": {}}
    for index in range(1, 5):
        robot = f"robot{index}"
        print(f"{robot}: deploy", flush=True)
        c = connect(index)
        steps = []
        try:
            steps.append(run(c,
                "docker exec MentorPi python3 -c 'from rclpy.signals import SignalHandlerOptions; "
                "assert hasattr(SignalHandlerOptions, \"NO\"); print(\"signal_api_ok\")'; "
                "if docker exec MentorPi test -e /run/openvela-formation/command-arm.json; then exit 40; else echo no_lease; fi"))
            sftp = c.open_sftp()
            sftp.put(str(SOURCE), "/tmp/reconfiguration_agent.py")
            sftp.close()
            backup = f"/opt/openvela-formation/backups/agent-ratefix-{stamp}"
            steps.append(run(c,
                f"sudo -n install -d -m 0755 {backup}; "
                f"sudo -n cp -a {REMOTE} {backup}/reconfiguration_agent.py; "
                "sudo -n docker cp /tmp/reconfiguration_agent.py MentorPi:/tmp/reconfiguration_agent.py; "
                "rm -f /tmp/reconfiguration_agent.py; "
                "sudo -n docker exec MentorPi python3 -m py_compile /tmp/reconfiguration_agent.py; "
                f"sudo -n docker exec MentorPi install -o ubuntu -g ubuntu -m 0644 /tmp/reconfiguration_agent.py {REMOTE}; "
                "sudo -n docker exec MentorPi rm -f /tmp/reconfiguration_agent.py; "
                f"sudo -n systemctl restart formation-agent@{robot}.service", timeout=60))
            time.sleep(3)
            verify = run(c,
                f"test \"$(systemctl is-active formation-agent@{robot}.service)\" = active; "
                f"test \"$(docker exec MentorPi pgrep -fc '^python3 {REMOTE.replace('.py', '[.]py')} --robot-id {robot}$')\" -eq 1; "
                f"docker exec MentorPi sha256sum {REMOTE}; "
                f"systemctl show formation-agent@{robot}.service -p ActiveState -p SubState -p MainPID -p Result -p NRestarts; "
                "if docker exec MentorPi test -e /run/openvela-formation/command-arm.json; then exit 41; else echo no_lease; fi; "
                f"journalctl -u formation-agent@{robot}.service --since '-2 minutes' --no-pager --output=cat | tail -n 30")
            steps.append(verify)
            if expected not in verify["stdout"]:
                raise RuntimeError(f"{robot}: checksum mismatch")
            report["robots"][robot] = {"backup": backup, "steps": steps, "ok": True}
            print(f"{robot}: verified", flush=True)
        finally:
            c.close()
    path = OUT / f"agent-ratefix-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
