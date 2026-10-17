from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
import argparse
import posixpath
import shlex
import subprocess

import paramiko


ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "outputs" / "formation-kit"
KEY = ROOT / "work" / "keys" / "formation_autonomy_ed25519"
HOST_KEYS = ROOT / "work" / "keys" / "formation_known_hosts"
REMOTE_INSTALLER = ROOT / "work" / "install_formation_remote.sh"
CONFIG_UPDATER = ROOT / "work" / "update_formation_limits.py"
SOURCES = {
    "formation_planner.py": KIT / "payload" / "planner" / "formation_planner.py",
    "reconfiguration_session.py": KIT / "payload" / "planner" / "reconfiguration_session.py",
    "reconfiguration_agent.py": KIT / "payload" / "planner" / "reconfiguration_agent.py",
    "fleet_endpoint.py": KIT / "payload" / "planner" / "fleet_endpoint.py",
    "auto_localize.py": KIT / "payload" / "planner" / "auto_localize.py",
    "scan_localizer.py": KIT / "payload" / "planner" / "scan_localizer.py",
    "command_bridge.py": KIT / "payload" / "baseline_robot1" / "command_bridge.py",
    "command_gate.py": KIT / "payload" / "baseline_robot1" / "command_gate.py",
}


def preflight() -> dict[str, str]:
    required = [KEY, HOST_KEYS, REMOTE_INSTALLER, CONFIG_UPDATER, *SOURCES.values()]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    python = ROOT / "work" / "formation-venv" / "Scripts" / "python.exe"
    subprocess.run(
        [str(python), "-m", "py_compile", *map(str, SOURCES.values()), str(CONFIG_UPDATER)],
        check=True,
    )
    subprocess.run([str(python), str(KIT / "verify_bundle.py")], check=True)
    return {name: sha256(path.read_bytes()).hexdigest() for name, path in SOURCES.items()}


def install_one(index: int, stamp: str, hashes: dict[str, str]) -> None:
    robot = f"robot{index}"
    stage = f"/home/pi/formation-install-{stamp}"
    client = paramiko.SSHClient()
    client.load_host_keys(str(HOST_KEYS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        f"192.168.1.{200 + index}", username="pi", key_filename=str(KEY),
        look_for_keys=False, allow_agent=False, timeout=15, auth_timeout=15,
    )
    try:
        _, stdout, stderr = client.exec_command(f"mkdir -m 700 {shlex.quote(stage)}", timeout=15)
        output = stdout.read().decode(errors="replace")
        error = stderr.read().decode(errors="replace")
        if stdout.channel.recv_exit_status():
            raise RuntimeError(f"{robot}: stage creation failed: {error or output}")
        with client.open_sftp() as sftp:
            for name, path in {
                **SOURCES,
                "install_formation_remote.sh": REMOTE_INSTALLER,
                "update_formation_limits.py": CONFIG_UPDATER,
            }.items():
                sftp.put(str(path), posixpath.join(stage, name))
        arguments = [robot, stage, *(hashes[name] for name in SOURCES)]
        command = "tr -d '\\r' < " + shlex.quote(posixpath.join(stage, "install_formation_remote.sh"))
        command += " | sudo -n bash -s -- " + " ".join(shlex.quote(value) for value in arguments)
        _, stdout, stderr = client.exec_command(command, timeout=120)
        output = stdout.read().decode(errors="replace")
        error = stderr.read().decode(errors="replace")
        code = stdout.channel.recv_exit_status()
        print(f"[{robot}] {output.strip()}", flush=True)
        if code:
            raise RuntimeError(f"{robot}: installation exited {code}: {error.strip()}")
        if "INSTALL_OK" not in output:
            raise RuntimeError(f"{robot}: installation did not report verification")
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    hashes = preflight()
    if args.check_only:
        print("LOCAL_INSTALL_CHECK_OK", flush=True)
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for index in range(1, 5):
        install_one(index, stamp, hashes)
    print("FOUR_CARS_INSTALL_OK", flush=True)


if __name__ == "__main__":
    main()
