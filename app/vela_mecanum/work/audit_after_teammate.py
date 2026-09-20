"""Read-only four-car runtime audit after teammate changes."""

from datetime import datetime
import getpass
import json
from pathlib import Path
import paramiko

out = Path(__file__).resolve().parent / "audit_after_teammate"
out.mkdir(exist_ok=True)
password = getpass.getpass("Robot SSH password: ")
for index in range(1, 5):
    robot = f"robot{index}"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(f"192.168.1.{200+index}", username="pi", password=password, timeout=8)
        commands = {
            "time": "date -Is",
            "services": f"systemctl is-active formation-agent@{robot}.service formation-command-bridge@{robot}.service mentorpi-localization.service mentorpi-localization-vendor-domain.service formation-reconfiguration.service 2>&1 || true",
            "units": f"systemctl cat formation-agent@{robot}.service formation-command-bridge@{robot}.service formation-reconfiguration.service 2>&1 || true",
            "versions": "docker exec MentorPi sh -c 'for f in /opt/openvela-formation/formation_lab/{formation_planner,reconfiguration_session,reconfiguration_ros,reconfiguration_agent,mentorpi_agent,command_bridge}.py /opt/openvela-formation/config/mentorpi.json; do test -f $f && sha256sum $f && stat -c \"%y %n\" $f; done'",
            "launchers": "sha256sum /opt/openvela-formation/scripts/run_formation_agent.sh /opt/openvela-formation/scripts/run_reconfiguration_coordinator.sh 2>&1 || true",
            "hardware": "docker exec MentorPi python3 -c 'import json; print(json.load(open(\"/opt/openvela-formation/config/mentorpi.json\"))[\"hardware_output_enabled\"])'",
            "lease": "docker exec MentorPi python3 -c 'import json,time,pathlib; p=pathlib.Path(\"/run/openvela-formation/command-arm.json\"); d=json.loads(p.read_text()) if p.exists() else {}; print(\"present\",bool(d),\"valid\",bool(d and time.monotonic()<float(d.get(\"expires_mono\",0))))'",
            "processes": "docker exec MentorPi ps -eo pid,args | grep -E 'reconfiguration|formation_agent|command_bridge|amcl|map_server' | grep -v grep || true",
            "agent_log": f"journalctl -u formation-agent@{robot}.service --since '15 minutes ago' --no-pager --output=cat | tail -n 30",
            "bridge_log": f"journalctl -u formation-command-bridge@{robot}.service --since '15 minutes ago' --no-pager --output=cat | tail -n 20",
        }
        if index == 1:
            commands["coordinator_log"] = "journalctl -u formation-reconfiguration.service --since '15 minutes ago' --no-pager --output=cat | tail -n 40"
        results = {}
        for name, command in commands.items():
            print(robot, name, flush=True)
            try:
                _, stdout, stderr = client.exec_command(command, timeout=18)
                results[name] = {"stdout": stdout.read().decode(errors="replace"), "stderr": stderr.read().decode(errors="replace"), "exit": stdout.channel.recv_exit_status()}
            except Exception as exc:
                results[name] = {"error": str(exc)}
                print(robot, name, "ERROR", exc, flush=True)
        (out / f"{robot}.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(robot, "services:", results["services"]["stdout"].strip().replace("\n", ", "), "hardware:", results["hardware"]["stdout"].strip(), "lease:", results["lease"]["stdout"].strip(), flush=True)
    except Exception as exc:
        print(robot, "ERROR", exc, flush=True)
    finally:
        client.close()
