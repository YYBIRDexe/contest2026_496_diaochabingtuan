"""Import this saved kit locally, or upload it to four robots as inactive files."""

from __future__ import annotations

import argparse
import getpass
from hashlib import sha256
import json
from pathlib import Path
import shutil

import paramiko


ROOT = Path(__file__).resolve().parent
HOSTS = [f"192.168.1.{index}" for index in range(201, 205)]
REMOTE_DIR = "/home/pi/formation-kit-2026-09-19"


def entries():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        source = ROOT / item["path"]
        if not source.is_file() or sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError(f"Bundle file is missing or changed: {item['path']}")
    return manifest["files"]


def install_local(destination: Path, files: list[dict]):
    destination = destination.expanduser().resolve()
    if destination == ROOT or ROOT in destination.parents or destination in ROOT.parents:
        raise RuntimeError("Choose a destination outside the source bundle")
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError(f"Destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for item in files:
        target = destination / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / item["path"], target)
    shutil.copy2(ROOT / "manifest.json", destination / "manifest.json")
    shutil.copy2(ROOT / "README.md", destination / "README.md")
    print(f"Local import complete: {destination} ({len(files)} files)")


def upload_robots(files: list[dict], username: str):
    class ConfirmHostKey(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            import base64
            fingerprint = base64.b64encode(sha256(key.asbytes()).digest()).decode().rstrip("=")
            answer = input(f"New SSH host {hostname}, SHA256:{fingerprint}. Trust this key? Type yes: ")
            if answer != "yes":
                raise RuntimeError(f"SSH host key not accepted: {hostname}")
            client.get_host_keys().add(hostname, key.get_name(), key)

    password = getpass.getpass("Robot SSH password (not saved): ")
    for host in HOSTS:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.load_host_keys(str(Path.home() / ".ssh" / "known_hosts")) if (Path.home() / ".ssh" / "known_hosts").exists() else None
        client.set_missing_host_key_policy(ConfirmHostKey())
        try:
            client.connect(host, username=username, password=password, timeout=8, auth_timeout=8)
            sftp = client.open_sftp()
            def mkdirs(remote):
                current = ""
                for part in remote.strip("/").split("/"):
                    current += "/" + part
                    try:
                        sftp.stat(current)
                    except OSError:
                        sftp.mkdir(current)
            mkdirs(REMOTE_DIR)
            for item in files:
                remote = REMOTE_DIR + "/" + item["path"]
                mkdirs(remote.rsplit("/", 1)[0])
                sftp.put(str(ROOT / item["path"]), remote)
                with sftp.open(remote, "rb") as stream:
                    digest = sha256(stream.read()).hexdigest()
                if digest != item["sha256"]:
                    raise RuntimeError(f"Upload verification failed on {host}: {item['path']}")
            sftp.put(str(ROOT / "manifest.json"), REMOTE_DIR + "/manifest.json")
            sftp.close()
            print(f"{host}: staged and verified {len(files)} files in {REMOTE_DIR}; no services started")
        finally:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "robots", "both"), required=True)
    parser.add_argument("--destination", type=Path, default=Path.home() / "Documents" / "FormationKit-2026-09-19")
    parser.add_argument("--username", default="pi")
    args = parser.parse_args()
    files = entries()
    if args.target in ("local", "both"):
        install_local(args.destination, files)
    if args.target in ("robots", "both"):
        upload_robots(files, args.username)


if __name__ == "__main__":
    main()
