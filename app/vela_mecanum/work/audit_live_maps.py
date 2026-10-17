import getpass
import paramiko

p=getpass.getpass('Robot SSH password: ')
for index in range(1,5):
    c=paramiko.SSHClient();c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(f'192.168.1.{200+index}',username='pi',password=p,timeout=8)
    commands={
        'map_params':f"docker exec -u ubuntu -e ROS_DOMAIN_ID={index} MentorPi bash -lc 'source /opt/ros/humble/setup.bash; timeout 8 ros2 param get /map_server yaml_filename'",
        'map_files':"docker exec MentorPi sha256sum /home/ubuntu/shared/classroom.pgm /home/ubuntu/shared/classroom.yaml /opt/openvela-formation/maps/classroom.pgm /opt/openvela-formation/maps/classroom.yaml",
        'yaml':"docker exec MentorPi cat /home/ubuntu/shared/classroom.yaml",
        'code':"docker exec MentorPi sha256sum /opt/openvela-formation/formation_lab/formation_planner.py /opt/openvela-formation/formation_lab/reconfiguration_session.py /opt/openvela-formation/formation_lab/reconfiguration_agent.py /opt/openvela-formation/formation_lab/reconfiguration_ros.py",
    }
    try:
        print(f'\nrobot{index}',flush=True)
        for name,cmd in commands.items():
            _,o,e=c.exec_command(cmd,timeout=15)
            result=o.read().decode(errors='replace').strip()
            error=e.read().decode(errors='replace').strip()
            print(name,result,error[:200],flush=True)
    finally:c.close()
