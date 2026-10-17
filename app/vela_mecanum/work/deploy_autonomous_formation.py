"""Install the VM-tested autonomous additions without starting a mission."""

from __future__ import annotations

import getpass
import hashlib
from pathlib import Path
import posixpath
import time

import paramiko

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE / "outputs" / "formation-kit"
SOURCE = ROOT / "payload" / "planner"
KEY = BASE / "work" / "keys" / "formation_autonomy_ed25519"
HOST_KEYS = BASE / "work" / "keys" / "formation_known_hosts"
MAP_SHA = hashlib.sha256((ROOT / "payload" / "evidence" / "current_map" / "classroom.pgm").read_bytes()).hexdigest()
FILES = ("scan_localizer.py", "auto_localize.py", "fleet_endpoint.py", "reconfiguration_agent.py")
REMOTE = "/opt/openvela-formation/formation_lab"
TAG = time.strftime("%Y%m%d-%H%M%S")


def run(client, command):
    _, stdout, stderr = client.exec_command(command, timeout=20)
    out, err = stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")
    if stdout.channel.recv_exit_status():
        raise RuntimeError(f"{command}: {err[-400:] or out[-400:]}")
    return out.strip()


def main():
    if not KEY.is_file():
        raise RuntimeError("missing local SSH key")
    password = getpass.getpass("Robot SSH password (one-time key setup): ")
    public = KEY.with_suffix(KEY.suffix + ".pub").read_text().strip()
    host_keys = paramiko.HostKeys()
    if HOST_KEYS.exists():
        host_keys.load(str(HOST_KEYS))
    for index in range(1, 5):
        robot, host = f"robot{index}", f"192.168.1.{200+index}"
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username="pi", password=password, timeout=8, auth_timeout=8)
        try:
            key = client.get_transport().get_remote_server_key()
            previous = host_keys.lookup(host)
            if previous is not None and previous.get(key.get_name()) != key:
                raise RuntimeError(f"{host}: SSH host key changed")
            host_keys.add(host, key.get_name(), key)
            map_name = run(client, f"docker exec -u ubuntu -e ROS_DOMAIN_ID={index} MentorPi bash -lc 'source /opt/ros/humble/setup.bash; timeout 8 ros2 param get /map_server yaml_filename'")
            if "/home/ubuntu/shared/classroom.yaml" not in map_name:
                raise RuntimeError(f"{robot}: active map path changed: {map_name}")
            actual_map = run(client, "docker exec MentorPi sha256sum /home/ubuntu/shared/classroom.pgm").split()[0]
            if actual_map != MAP_SHA:
                raise RuntimeError(f"{robot}: active map content changed")
            states = run(client, f"systemctl is-active formation-agent@{robot}.service formation-command-bridge@{robot}.service")
            if states.splitlines() != ["active", "active"]:
                raise RuntimeError(f"{robot}: required service down: {states}")
            # Pin the tested teammate planner/session before touching the live agent.
            for name in ("formation_planner.py", "reconfiguration_session.py"):
                actual = run(client, f"docker exec MentorPi sha256sum {REMOTE}/{name}").split()[0]
                expected = hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
                if actual != expected:
                    raise RuntimeError(f"{robot}: running {name} differs from VM-tested source")
            auth = run(client, "test -d /home/pi/.ssh || mkdir -m 700 /home/pi/.ssh; touch /home/pi/.ssh/authorized_keys; chmod 600 /home/pi/.ssh/authorized_keys; cat /home/pi/.ssh/authorized_keys")
            if public not in auth.splitlines():
                sftp = client.open_sftp()
                stage_pub = f"/home/pi/formation-autonomy-{TAG}.pub"
                sftp.put(str(KEY.with_suffix(KEY.suffix + ".pub")), stage_pub)
                sftp.close()
                run(client, f"cat {stage_pub} >> /home/pi/.ssh/authorized_keys")
            stage = f"/home/pi/formation-autonomy-{TAG}"
            run(client, f"mkdir -p {stage}")
            sftp = client.open_sftp()
            for name in FILES:
                sftp.put(str(SOURCE / name), posixpath.join(stage, name))
            sftp.close()
            for name in FILES:
                target = f"{REMOTE}/{name}"
                run(client, f"docker exec MentorPi sh -c 'test ! -f {target} || cp -a {target} {target}.bak-{TAG}'")
                run(client, f"docker cp {stage}/{name} MentorPi:{target}")
            run(client, "docker exec MentorPi python3 -m py_compile " + " ".join(f"{REMOTE}/{name}" for name in FILES))
            hashes = run(client, "docker exec MentorPi sha256sum " + " ".join(f"{REMOTE}/{name}" for name in FILES))
            for line in hashes.splitlines():
                digest, path = line.split(maxsplit=1)
                if digest != hashlib.sha256((SOURCE / Path(path).name).read_bytes()).hexdigest():
                    raise RuntimeError(f"{robot}: installed hash mismatch: {path}")
            run(client, f"sudo -n systemctl restart formation-agent@{robot}.service")
            if run(client, f"systemctl is-active formation-agent@{robot}.service") != "active":
                raise RuntimeError(f"{robot}: agent failed to restart")
            print(f"{robot}: active map confirmed; code installed and hash verified; backup {TAG}", flush=True)
        finally:
            client.close()
        host_keys.save(str(HOST_KEYS))
    print("All four cars deployed. No command lease was created.", flush=True)


if __name__ == "__main__":
    main()
