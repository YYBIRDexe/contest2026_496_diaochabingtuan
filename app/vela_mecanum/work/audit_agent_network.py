"""Read-only audit of the four formation robots using pinned SSH host keys."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import time

import paramiko


BASE = Path(__file__).resolve().parents[1]
KEY = BASE / "work" / "keys" / "formation_autonomy_ed25519"
HOST_KEYS = BASE / "work" / "keys" / "formation_known_hosts"
OUT = BASE / "work" / "agent-network-audit"
OUT.mkdir(exist_ok=True)


def connect(index: int) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_host_keys(str(HOST_KEYS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        f"192.168.1.{200 + index}",
        username="pi",
        key_filename=str(KEY),
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )
    return client


def run(client: paramiko.SSHClient, command: str, timeout: int = 30) -> dict:
    started = time.monotonic()
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    return {
        "exit": stdout.channel.recv_exit_status(),
        "elapsed_s": round(time.monotonic() - started, 3),
        "stdout": out,
        "stderr": err,
    }


def audit(index: int) -> tuple[int, dict]:
    robot = f"robot{index}"
    result = {"robot": robot, "host": f"192.168.1.{200 + index}"}
    client = connect(index)
    try:
        commands = {
            "identity": "date -Is; uptime; hostname; ip route; ip -brief address",
            "agent_unit": (
                f"systemctl cat formation-agent@{robot}.service; "
                f"systemctl show formation-agent@{robot}.service "
                "-p ActiveState -p SubState -p MainPID -p ControlGroup -p NRestarts "
                "-p ExecMainStartTimestamp -p ExecMainExitTimestamp -p Result"
            ),
            "agent_launchers": (
                "for f in /opt/openvela-formation/scripts/run_formation_agent.sh "
                "/opt/openvela-formation/scripts/stop_formation_agent.sh; do "
                "echo FILE:$f; if test -e $f; then stat -c '%a %U:%G %y %n' $f; "
                "sed -n '1,240p' $f; else echo MISSING; fi; done"
            ),
            "processes": (
                "docker exec MentorPi ps -eo pid,ppid,lstart,stat,args --sort=pid | "
                "grep -E 'reconfiguration_agent|mentorpi_agent|formation_lab' | grep -v grep || true"
            ),
            "service_health": (
                f"systemctl is-active formation-agent@{robot}.service "
                f"formation-command-bridge@{robot}.service mentorpi-localization.service "
                "mentorpi-localization-vendor-domain.service 2>&1 || true; "
                "systemctl list-units --type=service --state=running --no-legend | "
                "grep -Ei 'formation|fleet|localiz|lidar|laser|rplidar|ld[0-9]' || true"
            ),
            "motor_gate": (
                "docker exec MentorPi python3 -c 'import json,pathlib,time; "
                "c=json.load(open(\"/opt/openvela-formation/config/mentorpi.json\")); "
                "p=pathlib.Path(\"/run/openvela-formation/command-arm.json\"); "
                "d=json.loads(p.read_text()) if p.exists() else {}; "
                "print(\"hardware_output_enabled\",c.get(\"hardware_output_enabled\")); "
                "print(\"lease_present\",p.exists(),\"lease_valid\","
                "bool(d and time.monotonic()<float(d.get(\"expires_mono\",0))))'"
            ),
            "bridge_recent": (
                f"journalctl -u formation-command-bridge@{robot}.service -n 15 "
                "--no-pager --output=short-iso"
            ),
            "wifi": (
                "iw dev wlan0 link 2>&1 || true; cat /proc/net/wireless; "
                "ip -s link show wlan0; iwconfig wlan0 2>&1 || true"
            ),
            "network_counters": "nstat -az 2>&1 || true; ss -s; ss -uapn | head -n 120",
            "router_ping": "ping -c 20 -W 1 -i 0.2 192.168.1.1",
        }
        for name, command in commands.items():
            result[name] = run(client, command, timeout=40)
    finally:
        client.close()
    return index, result


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    combined = {"started": datetime.now().astimezone().isoformat(), "robots": {}}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(audit, index) for index in range(1, 5)]
        for future in as_completed(futures):
            try:
                index, result = future.result()
                combined["robots"][f"robot{index}"] = result
                print(f"robot{index}: audit complete", flush=True)
            except Exception as exc:
                print(f"audit error: {exc!r}", flush=True)
    combined["finished"] = datetime.now().astimezone().isoformat()
    path = OUT / f"pre-{stamp}.json"
    path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
