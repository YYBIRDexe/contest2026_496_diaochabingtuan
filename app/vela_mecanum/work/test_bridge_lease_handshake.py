"""Create a short read-only lease handshake and observe bridge status; no waypoint."""

import json
from pathlib import Path
import time

import paramiko


BASE = Path(__file__).resolve().parents[1]
KEY = BASE / "work/keys/formation_autonomy_ed25519"
HOST_KEYS = BASE / "work/keys/formation_known_hosts"
HOST = "192.168.1.201"


def run(client, command, input_text=None, timeout=15):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    if input_text is not None:
        stdin.write(input_text)
        stdin.channel.shutdown_write()
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError((code, out, err))
    return out


def main():
    client = paramiko.SSHClient()
    client.load_host_keys(str(HOST_KEYS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(HOST, username="pi", key_filename=str(KEY), look_for_keys=False,
                   allow_agent=False, timeout=10, auth_timeout=10)
    lease = "bridge-handshake-only"
    try:
        code = f'''
import json, os, pathlib, time
p=pathlib.Path("/run/openvela-formation/command-arm.json")
tmp=p.with_suffix(".tmp")
tmp.write_text(json.dumps({{"id":"{lease}","robot":"robot1","expires_mono":time.monotonic()+8.0}}))
os.chmod(tmp,0o644)
os.replace(tmp,p)
'''
        run(client, "docker exec -i MentorPi python3 -", code)
        command = (
            "docker exec -u ubuntu -e ROS_DOMAIN_ID=42 MentorPi bash -lc "
            "'source /opt/ros/humble/setup.bash; "
            "timeout 6 ros2 topic echo /robot1/formation/command_bridge_status std_msgs/msg/String'"
        )
        output = run(client, command, timeout=10)
        print(output)
        if 'armed\\":true' not in output or 'forwarding\\":false' not in output:
            raise RuntimeError("bridge did not report armed=true, forwarding=false")
    finally:
        try:
            run(client, "docker exec MentorPi rm -f /run/openvela-formation/command-arm.json")
        finally:
            client.close()


if __name__ == "__main__":
    main()
