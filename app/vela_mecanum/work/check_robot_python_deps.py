import getpass,paramiko
p=getpass.getpass('Robot SSH password: ')
c=paramiko.SSHClient();c.set_missing_host_key_policy(paramiko.AutoAddPolicy());c.connect('192.168.1.201',username='pi',password=p,timeout=8)
_,o,e=c.exec_command("docker exec -u ubuntu MentorPi bash -lc 'source /opt/ros/humble/setup.bash; python3 -c \"import numpy, PIL, rclpy, nav2_msgs; print(numpy.__version__, PIL.__version__)\"'",timeout=12)
print('exit',o.channel.recv_exit_status(),'stdout',o.read().decode(),'stderr',e.read().decode())
c.close()
