from pathlib import Path
import paramiko

base = Path(__file__).resolve().parents[1]
c = paramiko.SSHClient()
c.load_host_keys(str(base / "work/keys/formation_known_hosts"))
c.set_missing_host_key_policy(paramiko.RejectPolicy())
c.connect("192.168.1.201", username="pi", key_filename=str(base / "work/keys/formation_autonomy_ed25519"), timeout=20)
command = """docker exec MentorPi sed -n '1,320p' /opt/openvela-formation/formation_lab/fleet_bridge.py
echo UNIT
systemctl cat fleet-bridge@robot1.service
echo LAUNCHER
sed -n '1,260p' /opt/openvela-formation/scripts/run_fleet_bridge.sh 2>/dev/null || true
"""
_, stdout, stderr = c.exec_command(command, timeout=30)
print(stdout.read().decode(errors="replace"))
print(stderr.read().decode(errors="replace"))
c.close()
