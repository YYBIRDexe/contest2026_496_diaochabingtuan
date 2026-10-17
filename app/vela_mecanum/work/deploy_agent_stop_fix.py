"""Back up and deploy the formation-agent stop/restart fix to four robots."""

from datetime import datetime
import json
from pathlib import Path
import shlex
import time

import paramiko


BASE = Path(__file__).resolve().parents[1]
KEY = BASE / "work" / "keys" / "formation_autonomy_ed25519"
HOST_KEYS = BASE / "work" / "keys" / "formation_known_hosts"
FIX = BASE / "work" / "agent-stop-fix"
OUT = BASE / "work" / "agent-network-audit"


def connect(index: int) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_host_keys(str(HOST_KEYS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        f"192.168.1.{200 + index}", username="pi", key_filename=str(KEY),
        timeout=12, banner_timeout=12, auth_timeout=12,
    )
    return client


def run(client: paramiko.SSHClient, command: str, timeout: int = 40) -> dict:
    started = time.monotonic()
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    status = stdout.channel.recv_exit_status()
    result = {"command": command, "exit": status, "elapsed_s": round(time.monotonic() - started, 3), "stdout": out, "stderr": err}
    if status != 0:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def upload(client: paramiko.SSHClient, source: Path, destination: str) -> None:
    sftp = client.open_sftp()
    try:
        sftp.put(str(source), destination)
    finally:
        sftp.close()


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = {"stamp": stamp, "robots": {}}
    stop_hash = __import__("hashlib").sha256((FIX / "stop_formation_agent.sh").read_bytes()).hexdigest()
    unit_hash = __import__("hashlib").sha256((FIX / "formation-agent@.service").read_bytes()).hexdigest()

    # 逐车部署，减少无线网络瞬时数据量。
    for index in range(1, 5):
        robot = f"robot{index}"
        backup = f"/opt/openvela-formation/backups/formation-agent-stopfix-{stamp}"
        last_error = None
        for attempt in range(1, 7):
            print(f"{robot}: attempt {attempt}", flush=True)
            client = None
            steps = []
            try:
                client = connect(index)
                safety = run(
                    client,
                    "docker exec MentorPi python3 -c 'import json,pathlib,time; "
                    "p=pathlib.Path(\"/run/openvela-formation/command-arm.json\"); "
                    "d=json.loads(p.read_text()) if p.exists() else {}; "
                    "assert not (d and time.monotonic()<float(d.get(\"expires_mono\",0))), \"valid motor lease exists\"; "
                    "print(\"no valid motor lease\")'",
                )
                steps.append(safety)

                upload(client, FIX / "stop_formation_agent.sh", "/tmp/stop_formation_agent.sh")
                upload(client, FIX / "formation-agent@.service", "/tmp/formation-agent@.service")
                command = (
                    f"sudo -n install -d -m 0755 {shlex.quote(backup)}/etc/systemd/system "
                    f"{shlex.quote(backup)}/opt/openvela-formation/scripts; "
                    f"test -e {shlex.quote(backup)}/etc/systemd/system/formation-agent@.service || "
                    f"sudo -n cp -a /etc/systemd/system/formation-agent@.service {shlex.quote(backup)}/etc/systemd/system/; "
                    "if test -e /opt/openvela-formation/scripts/stop_formation_agent.sh && "
                    f"! test -e {shlex.quote(backup)}/opt/openvela-formation/scripts/stop_formation_agent.sh; then "
                    f"sudo -n cp -a /opt/openvela-formation/scripts/stop_formation_agent.sh {shlex.quote(backup)}/opt/openvela-formation/scripts/; fi; "
                    "sudo -n install -o root -g root -m 0755 /tmp/stop_formation_agent.sh /opt/openvela-formation/scripts/stop_formation_agent.sh; "
                    "sudo -n install -o root -g root -m 0644 /tmp/formation-agent@.service /etc/systemd/system/formation-agent@.service; "
                    "rm -f /tmp/stop_formation_agent.sh /tmp/formation-agent@.service; "
                    "sudo -n systemctl daemon-reload; "
                    f"sudo -n systemctl restart formation-agent@{robot}.service"
                )
                steps.append(run(client, command, timeout=60))
                time.sleep(3)
                verify = run(
                    client,
                    f"test \"$(systemctl is-active formation-agent@{robot}.service)\" = active; "
                    "count=$(docker exec MentorPi pgrep -fc '^python3 /opt/openvela-formation/formation_lab/reconfiguration_agent[.]py --robot-id "
                    f"{robot}$'); test \"$count\" -eq 1; echo agent_count=$count; "
                    "sha256sum /opt/openvela-formation/scripts/stop_formation_agent.sh /etc/systemd/system/formation-agent@.service; "
                    f"systemctl show formation-agent@{robot}.service -p ActiveState -p SubState -p MainPID -p Result; "
                    "docker exec MentorPi python3 -c 'import json,pathlib,time; p=pathlib.Path(\"/run/openvela-formation/command-arm.json\"); "
                    "d=json.loads(p.read_text()) if p.exists() else {}; print(\"lease_present\",p.exists(),\"lease_valid\",bool(d and time.monotonic()<float(d.get(\"expires_mono\",0))))'",
                    timeout=40,
                )
                steps.append(verify)
                if stop_hash not in verify["stdout"] or unit_hash not in verify["stdout"]:
                    raise RuntimeError(f"{robot}: deployed hashes do not match local files")
                report["robots"][robot] = {"backup": backup, "steps": steps, "attempt": attempt, "ok": True}
                print(f"{robot}: fixed and verified", flush=True)
                break
            except Exception as exc:
                last_error = exc
                print(f"{robot}: attempt {attempt} failed: {exc!r}", flush=True)
                time.sleep(min(8, attempt * 2))
            finally:
                if client is not None:
                    client.close()
        else:
            report["robots"][robot] = {"ok": False, "error": repr(last_error)}
            raise RuntimeError(f"{robot}: retries exhausted: {last_error!r}")

    path = OUT / f"deploy-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
