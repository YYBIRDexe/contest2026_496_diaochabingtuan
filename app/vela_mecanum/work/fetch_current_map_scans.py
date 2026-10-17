import getpass
from pathlib import Path
import paramiko

out=Path(__file__).resolve().parents[1]/'outputs'/'formation-kit'/'payload'/'evidence'/'current_map'
out.mkdir(parents=True,exist_ok=True)
password=getpass.getpass('Robot SSH password: ')
for index in range(1,5):
    client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(f'192.168.1.{200+index}',username='pi',password=password,timeout=8)
    try:
        if index==1:
            sftp=client.open_sftp()
            sftp.get('/home/pi/docker/tmp/classroom.pgm',str(out/'classroom.pgm'))
            sftp.get('/home/pi/docker/tmp/classroom.yaml',str(out/'classroom.yaml'))
            sftp.close()
        cmd=(f"docker exec -u ubuntu -e ROS_DOMAIN_ID={index} MentorPi bash -lc "
             "'source /opt/ros/humble/setup.bash; timeout 10 ros2 topic echo --once --full-length /scan_raw'")
        _,stdout,stderr=client.exec_command(cmd,timeout=15)
        body=stdout.read().decode(errors='replace')
        error=stderr.read().decode(errors='replace')
        if stdout.channel.recv_exit_status():
            print(f'robot{index}: scan ERROR {error[:200]}',flush=True)
        else:
            (out/f'robot{index}_scan_raw.txt').write_text(body,encoding='utf-8')
            print(f'robot{index}: scan {len(body)} bytes',flush=True)
    finally:client.close()
