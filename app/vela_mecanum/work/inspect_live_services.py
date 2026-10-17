import getpass
import paramiko

password = getpass.getpass("Robot SSH password: ")
commands = [
    "systemctl list-units --type=service --all --no-legend | grep -E 'mentorpi|formation' || true",
    "systemctl list-unit-files --no-legend | grep -E 'mentorpi|formation' || true",
    "docker inspect MentorPi --format '{{json .Mounts}}'",
    "docker exec MentorPi ls -la /opt/openvela-formation/formation_lab",
    "docker exec MentorPi ls -la /opt/openvela-formation/config",
]
for index in range(1, 5):
    host = f"192.168.1.{200 + index}"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username="pi", password=password, timeout=8)
        print(f"\n========== robot{index} {host} ==========", flush=True)
        for command in commands:
            _, stdout, stderr = client.exec_command(command, timeout=15)
            print(f"$ {command}\n{stdout.read().decode(errors='replace')}", flush=True)
            error = stderr.read().decode(errors="replace")
            if error:
                print(f"ERR: {error[:500]}", flush=True)
    finally:
        client.close()
