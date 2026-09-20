from __future__ import annotations

import argparse
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan

from .lidar_guard import clearance_speed_scale, directional_clearance


DIRECTIONS = {
    "forward": (1.0, 0.0, 0.0),
    "backward": (-1.0, 0.0, math.pi),
    "left": (0.0, 1.0, math.pi / 2.0),
    "right": (0.0, -1.0, -math.pi / 2.0),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Short lidar-guarded MentorPi motion test")
    parser.add_argument("--direction", choices=DIRECTIONS, default="forward")
    parser.add_argument("--speed", type=float, default=0.05)
    parser.add_argument("--duration", type=float, default=0.5)
    parser.add_argument("--stop-distance", type=float, default=0.45)
    parser.add_argument("--slow-distance", type=float, default=0.80)
    parser.add_argument("--scan-timeout", type=float, default=0.5)
    parser.add_argument("--cmd-topic", default="/controller/cmd_vel")
    parser.add_argument("--scan-topic", default="/scan_raw")
    args, ros_args = parser.parse_known_args()

    if not 0.0 <= args.speed <= 0.10:
        raise SystemExit("speed must be between 0.0 and 0.10 m/s")
    if not 0.0 < args.duration <= 1.0:
        raise SystemExit("duration must be between 0 and 1.0 seconds")

    rclpy.init(args=ros_args)
    node = rclpy.create_node("lidar_guarded_motion_test")
    publisher = node.create_publisher(Twist, args.cmd_topic, 10)
    latest_scan: dict[str, object] = {}

    def scan_callback(message: LaserScan) -> None:
        latest_scan["message"] = message
        latest_scan["received"] = time.monotonic()

    subscription = node.create_subscription(
        LaserScan, args.scan_topic, scan_callback, qos_profile_sensor_data
    )

    def publish_zero(repetitions: int = 5) -> None:
        for _ in range(repetitions):
            publisher.publish(Twist())
            rclpy.spin_once(node, timeout_sec=0.02)

    try:
        deadline = time.monotonic() + 3.0
        while "message" not in latest_scan and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        if "message" not in latest_scan:
            raise SystemExit("no lidar data received; motion refused")

        vx_axis, vy_axis, direction_rad = DIRECTIONS[args.direction]
        started = time.monotonic()
        while time.monotonic() - started < args.duration:
            rclpy.spin_once(node, timeout_sec=0.02)
            received = float(latest_scan.get("received", 0.0))
            if time.monotonic() - received > args.scan_timeout:
                raise SystemExit("lidar data became stale; motion stopped")
            scan = latest_scan["message"]
            assert isinstance(scan, LaserScan)
            clearance = directional_clearance(
                scan.ranges,
                scan.angle_min,
                scan.angle_increment,
                scan.range_min,
                scan.range_max,
                direction_rad,
                math.radians(30.0),
            )
            if clearance is None:
                raise SystemExit("no valid lidar ranges in motion sector; motion refused")
            scale = clearance_speed_scale(clearance, args.stop_distance, args.slow_distance)
            if scale <= 0.0:
                raise SystemExit(f"obstacle at {clearance:.3f} m; motion refused")
            command = Twist()
            command.linear.x = vx_axis * args.speed * scale
            command.linear.y = vy_axis * args.speed * scale
            publisher.publish(command)
        node.get_logger().info("guarded motion test completed")
    finally:
        publish_zero()
        del subscription
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
