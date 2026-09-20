import getpass
import paramiko
from pathlib import Path

password=getpass.getpass('Robot SSH password: ')
out=Path(__file__).resolve().parent/'audit_after_teammate'/'dds'
out.mkdir(exist_ok=True)
for index in range(1,5):
    client=paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(f'192.168.1.{200+index}',username='pi',password=password,timeout=8)
    try:
        _,stdout,stderr=client.exec_command('docker exec MentorPi cat /home/ubuntu/shared/fleet_udp_unicast.xml',timeout=12)
        body=stdout.read()
        (out/f'robot{index}.xml').write_bytes(body)
        print(index,len(body),stdout.channel.recv_exit_status(),flush=True)
    finally:
        client.close()
