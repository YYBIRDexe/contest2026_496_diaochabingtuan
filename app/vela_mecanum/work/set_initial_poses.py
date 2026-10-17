from __future__ import annotations

import getpass
import math
import paramiko


poses = {
    1: (-2.55, -0.80, -0.10),
    2: (-2.50, 0.00, -0.10),
    3: (-2.50, -0.50, -0.10),
    4: (-2.50, -0.25, -0.10),
}
password = getpass.getpass("Robot SSH password: ")

for index, (x, y, yaw) in poses.items():
    host = f"192.168.1.{200 + index}"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username="pi", password=password, timeout=8)
    code = f"""
import rclpy
from nav2_msgs.srv import SetInitialPose
rclpy.init()
node = rclpy.create_node('formation_initial_pose_robot{index}')
client = node.create_client(SetInitialPose, '/set_initial_pose')
assert client.wait_for_service(timeout_sec=8.0), 'set_initial_pose unavailable'
request = SetInitialPose.Request()
request.pose.header.frame_id = 'map'
request.pose.header.stamp = node.get_clock().now().to_msg()
request.pose.pose.pose.position.x = {x}
request.pose.pose.pose.position.y = {y}
request.pose.pose.pose.orientation.z = {math.sin(yaw / 2)}
request.pose.pose.pose.orientation.w = {math.cos(yaw / 2)}
request.pose.pose.covariance[0] = 0.04
request.pose.pose.covariance[7] = 0.04
request.pose.pose.covariance[35] = 0.03
future = client.call_async(request)
rclpy.spin_until_future_complete(node, future, timeout_sec=8.0)
assert future.done() and future.result() is not None, 'set_initial_pose failed'
print('initial pose accepted robot{index}: x={x} y={y} yaw={yaw}', flush=True)
node.destroy_node()
rclpy.shutdown()
"""
    command = (
        f"docker exec -i -u ubuntu -e ROS_DOMAIN_ID={index} MentorPi "
        "bash -lc 'source /opt/ros/humble/setup.bash; python3 -'"
    )
    stdin, stdout, stderr = client.exec_command(command, timeout=20)
    stdin.write(code)
    stdin.channel.shutdown_write()
    output = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    status = stdout.channel.recv_exit_status()
    print(f"robot{index}: exit={status}, {output.strip()} {error.strip()[:300]}", flush=True)
    client.close()
