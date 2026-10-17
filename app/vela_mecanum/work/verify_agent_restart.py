from pathlib import Path
import json
import time
import paramiko

base = Path(__file__).resolve().parents[1]
key = base / "work/keys/formation_autonomy_ed25519"
hosts = base / "work/keys/formation_known_hosts"

for index in range(1, 5):
    robot = f"robot{index}"
    client = paramiko.SSHClient()
    client.load_host_keys(str(hosts))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(f"192.168.1.{200+index}", username="pi", key_filename=str(key), timeout=20)
    get_pid = f"docker exec MentorPi pgrep -f '^python3 /opt/openvela-formation/formation_lab/reconfiguration_agent[.]py --robot-id {robot}$'"
    _, stdout, stderr = client.exec_command(get_pid, timeout=10)
    before = stdout.read().decode().strip()
    stderr.read()
    stdout.channel.recv_exit_status()
    started = time.monotonic()
    _, stdout, stderr = client.exec_command(f"sudo -n systemctl restart formation-agent@{robot}.service", timeout=30)
    out, err = stdout.read().decode(), stderr.read().decode()
    restart_exit = stdout.channel.recv_exit_status()
    elapsed = time.monotonic() - started
    time.sleep(2)
    command = (
        f"echo PID=$(docker exec MentorPi pgrep -f '^python3 /opt/openvela-formation/formation_lab/reconfiguration_agent[.]py --robot-id {robot}$'); "
        f"systemctl show formation-agent@{robot}.service -p ActiveState -p SubState -p Result -p NRestarts; "
        f"journalctl -u formation-agent@{robot}.service --since '-90 seconds' --no-pager --output=cat | tail -n 80; "
        "if docker exec MentorPi test -e /run/openvela-formation/command-arm.json; then echo LEASE_PRESENT; else echo NO_LEASE; fi"
    )
    _, stdout, stderr = client.exec_command(command, timeout=20)
    verify_out, verify_err = stdout.read().decode(), stderr.read().decode()
    verify_exit = stdout.channel.recv_exit_status()
    client.close()
    print(json.dumps({"robot": robot, "before_pid": before, "restart_exit": restart_exit,
                      "restart_elapsed_s": round(elapsed, 3), "restart_stdout": out,
                      "restart_stderr": err, "verify_exit": verify_exit,
                      "verify_stdout": verify_out, "verify_stderr": verify_err}, ensure_ascii=False), flush=True)
