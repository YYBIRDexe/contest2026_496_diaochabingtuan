"""Install tested formation executor files, services, and retain rollback copies."""

import getpass
import json
import paramiko
import time

PASSWORD = getpass.getpass("Robot SSH password: ")
STAGE = "/home/pi/formation-kit-2026-09-18/payload"
TAG = time.strftime("%Y%m%d-%H%M%S")
PYTHON_FILES = ("formation_planner.py", "reconfiguration_session.py", "reconfiguration_ros.py", "reconfiguration_agent.py")


def connect(index):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(f"192.168.1.{200+index}", username="pi", password=PASSWORD, timeout=8)
    return client


def run(client, command, data=None, timeout=30):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    if data is not None:
        stdin.write(data)
        stdin.channel.shutdown_write()
    result = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"{command}: exit={status}; {error[-500:]} {result[-500:]}")
    return result.strip()


def set_hardware(client, enabled):
    code = f'''
import json, os, pathlib
p=pathlib.Path("/opt/openvela-formation/config/mentorpi.json")
d=json.loads(p.read_text())
d["hardware_output_enabled"]={enabled}
t=p.with_suffix(".json.tmp-reconfiguration")
t.write_text(json.dumps(d, indent=2)+"\\n")
os.replace(t,p)
print(d["hardware_output_enabled"])
'''
    return run(client, "docker exec -i MentorPi python3 -", code)


def install(index):
    robot = f"robot{index}"
    client = connect(index)
    try:
        current = run(client, "docker exec MentorPi python3 -c 'import json; print(json.load(open(\"/opt/openvela-formation/config/mentorpi.json\"))[\"hardware_output_enabled\"])'")
        if current != "False":
            raise RuntimeError(f"{robot}: hardware was already enabled; refusing unreviewed replacement")
        run(client, f"sudo -n cp -a /opt/openvela-formation/scripts/run_formation_agent.sh /opt/openvela-formation/scripts/run_formation_agent.sh.bak-{TAG}")
        run(client, f"docker exec MentorPi cp -a /opt/openvela-formation/config/mentorpi.json /opt/openvela-formation/config/mentorpi.json.bak-{TAG}")
        for name in PYTHON_FILES:
            target = f"/opt/openvela-formation/formation_lab/{name}"
            run(client, f"docker exec MentorPi sh -c 'test ! -e {target} || cp -a {target} {target}.bak-{TAG}'")
            run(client, f"docker cp {STAGE}/planner/{name} MentorPi:{target}")
        run(client, "docker exec MentorPi python3 -m py_compile " + " ".join(f"/opt/openvela-formation/formation_lab/{name}" for name in PYTHON_FILES))
        run(client, f"sudo -n install -m 0755 {STAGE}/deploy/run_formation_agent.sh /opt/openvela-formation/scripts/run_formation_agent.sh")
        if index == 1:
            run(client, f"sudo -n install -m 0755 {STAGE}/deploy/run_reconfiguration_coordinator.sh /opt/openvela-formation/scripts/run_reconfiguration_coordinator.sh")
            run(client, f"sudo -n install -m 0644 {STAGE}/deploy/formation-reconfiguration.service /etc/systemd/system/formation-reconfiguration.service")
            run(client, "sudo -n systemctl daemon-reload")
        print(f"{robot}: files installed; backup suffix {TAG}", flush=True)
    finally:
        client.close()


def start(index):
    client = connect(index)
    try:
        robot = f"robot{index}"
        run(client, f"sudo -n systemctl enable --now formation-agent@{robot}.service")
        state = run(client, f"systemctl is-active formation-agent@{robot}.service")
        if state != "active":
            raise RuntimeError(f"{robot}: agent service {state}")
        print(f"{robot}: agent active", flush=True)
        if index == 1:
            run(client, "sudo -n systemctl enable --now formation-reconfiguration.service")
            state = run(client, "systemctl is-active formation-reconfiguration.service")
            if state != "active":
                raise RuntimeError(f"coordinator service {state}")
            print("coordinator: active", flush=True)
    finally:
        client.close()


def enable(index):
    client = connect(index)
    try:
        print(f"robot{index}: hardware_output_enabled={set_hardware(client, True)}; lease remains absent", flush=True)
    finally:
        client.close()


def rollback(indices):
    print("Deployment failed; restoring disabled hardware and original agent launcher", flush=True)
    for index in indices:
        try:
            client = connect(index)
            try:
                set_hardware(client, False)
                if index == 1:
                    run(client, "sudo -n systemctl disable --now formation-reconfiguration.service")
                run(client, f"sudo -n systemctl disable --now formation-agent@robot{index}.service")
                run(client, f"sudo -n cp -a /opt/openvela-formation/scripts/run_formation_agent.sh.bak-{TAG} /opt/openvela-formation/scripts/run_formation_agent.sh")
                print(f"robot{index}: rollback complete", flush=True)
            finally:
                client.close()
        except Exception as exc:
            print(f"robot{index}: rollback needs manual attention: {exc}", flush=True)


def main():
    installed = []
    try:
        for index in range(1, 5):
            install(index)
            installed.append(index)
        for index in range(1, 5):
            start(index)
        for index in range(1, 5):
            enable(index)
        print("All four agents and coordinator installed; command leases not created", flush=True)
    except Exception:
        rollback(installed)
        raise


if __name__ == "__main__":
    main()
