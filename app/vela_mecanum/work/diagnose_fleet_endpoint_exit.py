"""Read-only post-run safety and fleet endpoint diagnostics."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time

import paramiko


BASE = Path(__file__).resolve().parents[1]
KEY = BASE / "work/keys/formation_autonomy_ed25519"
HOST_KEYS = BASE / "work/keys/formation_known_hosts"


def connect(index: int) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_host_keys(str(HOST_KEYS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(f"192.168.1.{200 + index}", username="pi", key_filename=str(KEY),
                   look_for_keys=False, allow_agent=False, timeout=10, auth_timeout=10)
    return client


def inspect(index: int) -> dict:
    robot = f"robot{index}"
    client = connect(index)
    try:
        command = (
            f"echo services=$(systemctl is-active formation-agent@{robot}.service),"
            f"$(systemctl is-active formation-command-bridge@{robot}.service); "
            "docker exec MentorPi python3 -c 'import json,pathlib,time; "
            "p=pathlib.Path(\"/run/openvela-formation/command-arm.json\"); "
            "d=json.loads(p.read_text()) if p.exists() else {}; "
            "print(\"lease_present\",p.exists(),\"lease_valid\",bool(d and time.monotonic()<float(d.get(\"expires_mono\",0))))'; "
            "echo agent_count=$(docker exec MentorPi pgrep -fc '^python3 /opt/openvela-formation/formation_lab/reconfiguration_agent[.]py --robot-id "
            f"{robot}$'); "
            "echo endpoint_count=$(docker exec MentorPi pgrep -fc 'fleet_endpoint[.]py' || true); "
            f"journalctl -u formation-command-bridge@{robot}.service --since '-3 minutes' --no-pager --output=cat | tail -n 15"
        )
        _, stdout, stderr = client.exec_command(command, timeout=20)
        safety_out = stdout.read().decode(errors="replace")
        safety_err = stderr.read().decode(errors="replace")
        safety_code = stdout.channel.recv_exit_status()

        channel = client.get_transport().open_session()
        channel.settimeout(1.0)
        endpoint_command = (
            "docker exec -i -u ubuntu -e ROS_DOMAIN_ID=42 MentorPi bash -lc "
            f"'source /opt/ros/humble/setup.bash; exec python3 -u "
            f"/opt/openvela-formation/formation_lab/fleet_endpoint.py --robot-id {robot}'"
        )
        channel.exec_command(endpoint_command)
        out = b""
        err = b""
        started = time.monotonic()
        while time.monotonic() - started < 8 and not channel.exit_status_ready():
            if channel.recv_ready():
                out += channel.recv(65536)
            if channel.recv_stderr_ready():
                err += channel.recv_stderr(65536)
            time.sleep(0.02)
        exited = channel.exit_status_ready()
        exit_code = channel.recv_exit_status() if exited else None
        if channel.recv_ready():
            out += channel.recv(65536)
        if channel.recv_stderr_ready():
            err += channel.recv_stderr(65536)
        channel.close()
        return {
            "robot": robot,
            "safety_code": safety_code,
            "safety_stdout": safety_out,
            "safety_stderr": safety_err,
            "endpoint_exited_within_8s": exited,
            "endpoint_exit_code": exit_code,
            "endpoint_stdout_tail": out.decode(errors="replace")[-2000:],
            "endpoint_stderr_tail": err.decode(errors="replace")[-4000:],
        }
    finally:
        client.close()


def main() -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        data = list(pool.map(inspect, range(1, 5)))
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
