import getpass
import paramiko

password=getpass.getpass('Robot SSH password: ')
for index in range(1,5):
    robot=f'robot{index}'
    client=paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(f'192.168.1.{200+index}',username='pi',password=password,timeout=8)
    try:
        commands={
            'fleet_services':"systemctl list-units --type=service --all --no-legend | grep -E 'fleet|localization|formation'",
            'fleet_processes':"docker exec MentorPi ps -eo pid,args | grep -E 'fleet_bridge|reconfiguration|amcl|map_server' | grep -v grep",
            'amcl_lifecycle':f"docker exec -u ubuntu -e ROS_DOMAIN_ID={index} MentorPi bash -lc 'source /opt/ros/humble/setup.bash; timeout 6 ros2 lifecycle get /amcl'",
            'amcl_topic':f"docker exec -u ubuntu -e ROS_DOMAIN_ID={index} MentorPi bash -lc 'source /opt/ros/humble/setup.bash; timeout 6 ros2 topic info -v /amcl_pose'",
            'fleet_logs':"journalctl --since '15 minutes ago' --no-pager --output=cat | grep -Ei 'fleet.bridge|amcl|localization' | tail -n 12",
        }
        print(f'\n### {robot}',flush=True)
        for name,command in commands.items():
            try:
                _,stdout,stderr=client.exec_command(command,timeout=12)
                result=stdout.read().decode(errors='replace').strip()
                error=stderr.read().decode(errors='replace').strip()
                print(name, result[-1600:], error[-300:],flush=True)
            except Exception as exc:
                print(name,'ERROR',exc,flush=True)
    finally:
        client.close()
