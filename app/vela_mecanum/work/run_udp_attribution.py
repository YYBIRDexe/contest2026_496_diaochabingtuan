from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import paramiko

base = Path(__file__).resolve().parents[1]
key = base / "work/keys/formation_autonomy_ed25519"
hosts = base / "work/keys/formation_known_hosts"
script = (base / "work/count_udp_by_process.py").read_text(encoding="utf-8")


def one(index):
    client = paramiko.SSHClient()
    client.load_host_keys(str(hosts))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(f"192.168.1.{200+index}", username="pi", key_filename=str(key), timeout=20)
    sftp = client.open_sftp()
    with sftp.file("/tmp/count_udp_by_process.py", "w") as remote:
        remote.write(script)
    sftp.close()
    peers = " ".join(f"192.168.1.{200+i}" for i in range(1, 5) if i != index)
    command = f"sudo -n python3 /tmp/count_udp_by_process.py --local 192.168.1.{200+index} --peers {peers} --seconds 10; rm -f /tmp/count_udp_by_process.py"
    _, stdout, stderr = client.exec_command(command, timeout=25)
    out, err = stdout.read().decode(), stderr.read().decode()
    status = stdout.channel.recv_exit_status()
    client.close()
    return index, status, out, err


with ThreadPoolExecutor(max_workers=4) as pool:
    futures = [pool.submit(one, i) for i in range(1, 5)]
    for future in as_completed(futures):
        print(future.result(), flush=True)
