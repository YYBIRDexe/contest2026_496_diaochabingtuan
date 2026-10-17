from __future__ import annotations

from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
KEY = ROOT / "work" / "keys" / "formation_autonomy_ed25519"
HOST_KEYS = ROOT / "work" / "keys" / "formation_known_hosts"


def run(client: paramiko.SSHClient, command: str, input_text: str | None = None, timeout: int = 15) -> str:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    if input_text is not None:
        stdin.write(input_text)
        stdin.channel.shutdown_write()
    output = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"command failed with exit {code}: {error[-500:] or output[-500:]}")
    return output.strip()


def bridge_status(client: paramiko.SSHClient, robot: str) -> str:
    return run(
        client,
        "docker exec -u ubuntu -e ROS_DOMAIN_ID=42 MentorPi bash -lc '"
        "source /opt/ros/humble/setup.bash; timeout 7 ros2 topic echo "
        f"/{robot}/formation/command_bridge_status std_msgs/msg/String --once'",
        timeout=12,
    )


def main() -> None:
    for index in range(1, 5):
        robot = f"robot{index}"
        client = paramiko.SSHClient()
        client.load_host_keys(str(HOST_KEYS))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            f"192.168.1.{200 + index}", username="pi", key_filename=str(KEY),
            look_for_keys=False, allow_agent=False, timeout=15, auth_timeout=15,
        )
        lease_path = "/run/openvela-formation/command-arm.json"
        try:
            run(client, f"docker exec MentorPi test ! -e {lease_path}")
            writer = (
                "import json,os,pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
                "t=p.with_suffix('.tmp'); t.write_text(json.dumps({"
                "'id':sys.argv[2],'robot':sys.argv[3],'expires_mono':time.monotonic()+12.0})); "
                "os.chmod(t,0o644); os.replace(t,p)"
            )
            run(
                client,
                f"docker exec MentorPi python3 -c \"{writer}\" {lease_path} stationary-zero-{robot} {robot}",
            )
            armed = bridge_status(client, robot)
            if '"armed":true' not in armed or '"forwarding":false' not in armed:
                raise RuntimeError(f"{robot}: unexpected armed status: {armed}")
        finally:
            run(client, f"docker exec MentorPi rm -f {lease_path}")
            disarmed = bridge_status(client, robot)
            client.close()
        if '"armed":false' not in disarmed or '"forwarding":false' not in disarmed:
            raise RuntimeError(f"{robot}: bridge did not return to disarmed state: {disarmed}")
        print(f"{robot}: zero-output handshake passed; lease removed", flush=True)
    print("STATIONARY_ZERO_HANDSHAKE_OK", flush=True)


if __name__ == "__main__":
    main()
