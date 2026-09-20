import getpass
import paramiko
import sys

code = r'''
import json,time
import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from rclpy.qos import qos_profile_sensor_data
rclpy.init()
node=rclpy.create_node('codex_readonly_formation_audit')
seen={}
subscriptions=[]
def capture(name):
    def callback(message):
        if hasattr(message,'data'):
            try: data=json.loads(message.data)
            except Exception: data=message.data[:200]
        elif isinstance(message,PoseWithCovarianceStamped):
            p=message.pose.pose.position
            data={'x':round(p.x,3),'y':round(p.y,3),'frame':message.header.frame_id,'stamp':message.header.stamp.sec,'cov_xy':[round(message.pose.covariance[i],3) for i in (0,7)]}
        else:
            data={'samples':len(message.ranges),'stamp':message.header.stamp.sec}
        key=f"agent_status.{data.get('robot_id')}" if name=='agent_status' and isinstance(data,dict) else name
        seen[key]=(data,time.monotonic())
    return callback
for i in range(1,5):
    r=f'robot{i}'
    subscriptions.append(node.create_subscription(PoseWithCovarianceStamped,f'/{r}/amcl_pose',capture(f'{r}.pose'),qos_profile_sensor_data))
    subscriptions.append(node.create_subscription(LaserScan,f'/{r}/scan_raw',capture(f'{r}.scan'),qos_profile_sensor_data))
    subscriptions.append(node.create_subscription(String,f'/{r}/formation/command_bridge_status',capture(f'{r}.bridge'),10))
    subscriptions.append(node.create_subscription(String,'/formation/agent_status',capture('agent_status'),10))
subscriptions.append(node.create_subscription(String,'/robot1/formation/reconfiguration_status',capture('coordinator'),10))
end=time.monotonic()+15
while time.monotonic()<end:
    rclpy.spin_once(node,timeout_sec=0.1)
for key,(value,when) in sorted(seen.items()):
    print(key, json.dumps(value,separators=(',',':')), 'age_s',round(time.monotonic()-when,2))
print('missing',sorted(set([f'robot{i}.{part}' for i in range(1,5) for part in ('pose','scan','bridge')]+[f'agent_status.robot{i}' for i in range(1,5)]+['coordinator'])-set(seen)))
node.destroy_node()
rclpy.shutdown()
'''
password=getpass.getpass('Robot SSH password: ')
client=paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(sys.argv[1] if len(sys.argv)>1 else '192.168.1.201',username='pi',password=password,timeout=8)
command="docker exec -i -u ubuntu -e ROS_DOMAIN_ID=42 MentorPi bash -lc 'source /opt/ros/humble/setup.bash; python3 -'"
stdin,stdout,stderr=client.exec_command(command,timeout=25)
stdin.write(code)
stdin.channel.shutdown_write()
print(stdout.read().decode(errors='replace'))
print(stderr.read().decode(errors='replace'))
client.close()
