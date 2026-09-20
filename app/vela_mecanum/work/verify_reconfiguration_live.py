import getpass
import json
import paramiko

password = getpass.getpass("Robot SSH password: ")
for index in range(1, 5):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(f"192.168.1.{200+index}", username="pi", password=password, timeout=8)
    robot = f"robot{index}"
    try:
        commands = [
            f"systemctl is-active formation-agent@{robot}.service formation-command-bridge@{robot}.service",
            "docker exec MentorPi python3 -c 'import json; print(json.load(open(\"/opt/openvela-formation/config/mentorpi.json\"))[\"hardware_output_enabled\"])'",
            "docker exec MentorPi sh -c 'if test -f /run/openvela-formation/command-arm.json; then cat /run/openvela-formation/command-arm.json; else echo NO_LEASE; fi'",
            f"journalctl -u formation-agent@{robot}.service -n 10 --no-pager --output=cat",
        ]
        if index == 1:
            commands += ["systemctl is-active formation-reconfiguration.service", "journalctl -u formation-reconfiguration.service -n 10 --no-pager --output=cat"]
        print(f"\n### {robot}")
        for command in commands:
            _, stdout, stderr = client.exec_command(command, timeout=15)
            out = stdout.read().decode(errors="replace").strip()
            err = stderr.read().decode(errors="replace").strip()
            print(command, "\n", out[-1000:], err[-300:])
    finally:
        client.close()
