import getpass
import paramiko

password = getpass.getpass("Robot SSH password: ")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.1.201", username="pi", password=password, timeout=8)
for service in ("formation-agent@robot1", "formation-command-bridge@robot1", "mentorpi-localization-vendor-domain"):
    command = f"systemctl cat {service}; systemctl show {service} -p ActiveState -p ExecStart -p FragmentPath"
    _, stdout, stderr = client.exec_command(command, timeout=15)
    print(f"\n### {service}\n{stdout.read().decode(errors='replace')}\n{stderr.read().decode(errors='replace')}")
client.close()
