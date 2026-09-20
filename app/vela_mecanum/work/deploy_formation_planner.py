from datetime import datetime
from hashlib import sha256
from pathlib import Path

import paramiko


BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "outputs/formation-kit/payload/planner/formation_planner.py"
KEY = BASE / "work/keys/formation_autonomy_ed25519"
HOST_KEYS = BASE / "work/keys/formation_known_hosts"
REMOTE = "/opt/openvela-formation/formation_lab/formation_planner.py"
LEASE = "/run/openvela-formation/command-arm.json"


def connect(index):
    client = paramiko.SSHClient()
    client.load_host_keys(str(HOST_KEYS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        f"192.168.1.{200 + index}",
        username="pi",
        key_filename=str(KEY),
        look_for_keys=False,
        allow_agent=False,
        timeout=15,
        auth_timeout=15,
    )
    return client


def run(client, command, timeout=30):
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"command exit={code}: {error[-500:] or output[-500:]}")
    return output


def main():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    expected = sha256(SOURCE.read_bytes()).hexdigest()

    for index in range(1, 5):
        client = connect(index)
        try:
            run(client, f"if docker exec MentorPi test -e {LEASE}; then exit 40; fi")
        finally:
            client.close()

    for index in range(1, 5):
        robot = f"robot{index}"
        client = connect(index)
        try:
            sftp = client.open_sftp()
            sftp.put(str(SOURCE), "/home/pi/formation_planner.py")
            sftp.close()
            backup = f"/opt/openvela-formation/backups/formation-planner-{stamp}"
            output = run(
                client,
                f"if docker exec MentorPi test -e {LEASE}; then exit 40; fi; "
                f"sudo -n install -d -m 0755 {backup}; "
                f"sudo -n cp -a {REMOTE} {backup}/formation_planner.py; "
                "sudo -n docker cp /home/pi/formation_planner.py MentorPi:/home/ubuntu/formation_planner.py; "
                "rm -f /home/pi/formation_planner.py; "
                "sudo -n docker exec MentorPi python3 -m py_compile /home/ubuntu/formation_planner.py; "
                f"sudo -n docker exec MentorPi install -o ubuntu -g ubuntu -m 0644 /home/ubuntu/formation_planner.py {REMOTE}; "
                "sudo -n docker exec MentorPi rm -f /home/ubuntu/formation_planner.py; "
                f"docker exec MentorPi sha256sum {REMOTE}; "
                f"if docker exec MentorPi test -e {LEASE}; then exit 41; fi; "
                f"systemctl is-active formation-agent@{robot}.service formation-command-bridge@{robot}.service",
            )
            if expected not in output or output.splitlines()[-2:] != ["active", "active"]:
                raise RuntimeError(f"{robot}: planner 校验失败")
            print(f"{robot}: planner={expected} backup={backup}", flush=True)
        finally:
            client.close()


if __name__ == "__main__":
    main()
