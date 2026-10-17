from pathlib import Path
import getpass
import paramiko

out = Path(__file__).resolve().parent / "runtime_config"
out.mkdir(exist_ok=True)
password = getpass.getpass("Robot SSH password: ")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.1.201", username="pi", password=password, timeout=8)
paths = [
    "/opt/openvela-formation/scripts/run_formation_agent.sh",
    "/opt/openvela-formation/scripts/run_command_bridge.sh",
    "/opt/openvela-formation/scripts/stop_command_bridge.sh",
    "/opt/openvela-formation/scripts/run_localization_vendor_domain.sh",
    "/etc/default/openvela-formation",
]
for path in paths:
    _, stdout, stderr = client.exec_command(f"cat {path}", timeout=10)
    data = stdout.read()
    if stdout.channel.recv_exit_status():
        print(path, stderr.read().decode(errors="replace"))
    else:
        name = path.rsplit("/", 1)[-1]
        (out / name).write_bytes(data)
        print(path, len(data))
client.close()
