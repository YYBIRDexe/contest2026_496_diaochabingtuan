"""VM-only ROS test: fake four lidar/AMCL services using captured real scans."""

from pathlib import Path
import os
import subprocess
import sys
import threading
import time

from scan_localizer import parse_scan_echo


def run(data_dir: Path):
    import rclpy
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import qos_profile_sensor_data
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from nav2_msgs.srv import SetInitialPose
    from sensor_msgs.msg import LaserScan

    for index in range(1, 5):
        context = Context()
        rclpy.init(context=context, domain_id=index)
        node = rclpy.create_node(f"virtual_robot{index}", context=context)
        ranges, angle_min, angle_step = parse_scan_echo(data_dir / f"robot{index}_scan_raw.txt")
        scan_pub = node.create_publisher(LaserScan, "/scan_raw", qos_profile_sensor_data)
        pose_pub = node.create_publisher(PoseWithCovarianceStamped, "/amcl_pose", qos_profile_sensor_data)
        selected = {"pose": None}

        def set_initial_pose(request, response):
            selected["pose"] = request.pose
            return response

        service = node.create_service(SetInitialPose, "/set_initial_pose", set_initial_pose)

        def publish():
            scan = LaserScan()
            scan.header.stamp = node.get_clock().now().to_msg()
            scan.header.frame_id = "laser"
            scan.angle_min = angle_min
            scan.angle_increment = angle_step
            scan.ranges = ranges
            scan_pub.publish(scan)
            if selected["pose"] is not None:
                pose = selected["pose"]
                pose.header.stamp = node.get_clock().now().to_msg()
                pose_pub.publish(pose)

        timer = node.create_timer(0.1, publish)
        executor = SingleThreadedExecutor(context=context)
        executor.add_node(node)
        running = True

        def spin():
            while running:
                executor.spin_once(timeout_sec=0.05)

        worker = threading.Thread(target=spin, daemon=True)
        worker.start()
        env = dict(os.environ, ROS_DOMAIN_ID=str(index))
        try:
            command = [sys.executable, str(Path(__file__).with_name("auto_localize.py")),
                       "--robot-id", f"robot{index}", "--map", str(data_dir / "classroom.pgm")]
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            print(f"robot{index}: exit={result.returncode} stdout={result.stdout.strip()} stderr={result.stderr.strip()[:300]}", flush=True)
            if result.returncode != 0 or selected["pose"] is None:
                raise RuntimeError(f"virtual localization failed for robot{index}")
        finally:
            running = False
            worker.join(timeout=2)
            executor.remove_node(node)
            executor.shutdown()
            node.destroy_node()
            rclpy.shutdown(context=context)


if __name__ == "__main__":
    run(Path(sys.argv[1]))
