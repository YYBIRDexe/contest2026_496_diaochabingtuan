"""Initialize one car's AMCL from its current laser scan and the live map."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time

from scan_localizer import ScanMatcher


def angle_distance(first: float, second: float) -> float:
    return abs(math.atan2(math.sin(first - second), math.cos(first - second)))


def main():
    import rclpy
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from nav2_msgs.srv import SetInitialPose
    from sensor_msgs.msg import LaserScan
    from rclpy.qos import qos_profile_sensor_data
    from std_srvs.srv import Empty

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot-id", choices=tuple(f"robot{i}" for i in range(1, 5)), required=True)
    parser.add_argument("--map", type=Path, default=Path("/home/ubuntu/shared/classroom.pgm"))
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()
    matcher = ScanMatcher(args.map)
    rclpy.init()
    node = rclpy.create_node(f"auto_localize_{args.robot_id}")
    scans = []
    poses = []

    def on_scan(message: LaserScan):
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        if abs(time.time() - stamp) < 0.7:
            scans.append((tuple(message.ranges), float(message.angle_min), float(message.angle_increment), time.monotonic()))
            if len(scans) > 10:
                del scans[:-10]

    def on_pose(message: PoseWithCovarianceStamped):
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        p, q = message.pose.pose.position, message.pose.pose.orientation
        cov = message.pose.covariance
        if (message.header.frame_id.lstrip("/") == "map" and abs(time.time() - stamp) < 0.7
                and all(math.isfinite(v) for v in (p.x, p.y, q.z, q.w, cov[0], cov[7], cov[35]))
                and 0 <= cov[0] <= 0.25 and 0 <= cov[7] <= 0.25 and 0 <= cov[35] <= 0.25):
            poses.append((float(p.x), float(p.y), 2 * math.atan2(q.z, q.w), time.monotonic()))
            if len(poses) > 10:
                del poses[:-10]

    scan_sub = node.create_subscription(LaserScan, "/scan_raw", on_scan, qos_profile_sensor_data)
    pose_sub = node.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", on_pose, qos_profile_sensor_data)
    deadline = time.monotonic() + args.timeout
    try:
        while time.monotonic() < deadline and not scans:
            rclpy.spin_once(node, timeout_sec=0.1)
        if not scans:
            raise RuntimeError("fresh lidar scan unavailable")
        first = scans[-1]
        first_estimate = matcher.estimate(first[0], first[1], first[2])
        while time.monotonic() < deadline and (not scans or scans[-1][3] < first[3] + 0.30):
            rclpy.spin_once(node, timeout_sec=0.1)
        if not scans or scans[-1][3] < first[3] + 0.30:
            raise RuntimeError("second lidar scan unavailable")
        second = scans[-1]
        estimate = matcher.estimate(second[0], second[1], second[2])
        if (math.hypot(estimate.x - first_estimate.x, estimate.y - first_estimate.y) > 0.25
                or angle_distance(estimate.yaw, first_estimate.yaw) > 0.30):
            raise RuntimeError("scan match changed between observations")
        if poses:
            x, y, yaw, _ = poses[-1]
            if math.hypot(x - estimate.x, y - estimate.y) <= 0.45 and angle_distance(yaw, estimate.yaw) <= 0.45:
                print(json.dumps({"robot_id": args.robot_id, "source": "verified_amcl", "x": x, "y": y, "yaw": yaw,
                                  "score": estimate.score, "confidence_ratio": estimate.confidence_ratio}))
                return
        client = node.create_client(SetInitialPose, "/set_initial_pose")
        while time.monotonic() < deadline and not client.wait_for_service(timeout_sec=0.2):
            rclpy.spin_once(node, timeout_sec=0.1)
        if not client.service_is_ready():
            raise RuntimeError("AMCL set_initial_pose service unavailable")
        request = SetInitialPose.Request()
        request.pose.header.frame_id = "map"
        request.pose.header.stamp = node.get_clock().now().to_msg()
        request.pose.pose.pose.position.x = estimate.x
        request.pose.pose.pose.position.y = estimate.y
        request.pose.pose.pose.orientation.z = math.sin(estimate.yaw / 2)
        request.pose.pose.pose.orientation.w = math.cos(estimate.yaw / 2)
        request.pose.pose.covariance[0] = 0.06
        request.pose.pose.covariance[7] = 0.06
        request.pose.pose.covariance[35] = 0.05
        future = client.call_async(request)
        while time.monotonic() < deadline and not future.done():
            rclpy.spin_once(node, timeout_sec=0.1)
        if not future.done() or future.result() is None:
            global_client = node.create_client(Empty, "/reinitialize_global_localization")
            while time.monotonic() < deadline and not global_client.wait_for_service(timeout_sec=0.2):
                rclpy.spin_once(node, timeout_sec=0.1)
            if not global_client.service_is_ready():
                raise RuntimeError("AMCL did not accept initial pose and global localization service unavailable")
            global_future = global_client.call_async(Empty.Request())
            while time.monotonic() < deadline and not global_future.done():
                rclpy.spin_once(node, timeout_sec=0.1)
            if not global_future.done() or global_future.result() is None:
                raise RuntimeError("AMCL global localization request failed")
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if poses:
                x, y, yaw, _ = poses[-1]
                if math.hypot(x - estimate.x, y - estimate.y) <= 0.45 and angle_distance(yaw, estimate.yaw) <= 0.45:
                    print(json.dumps({"robot_id": args.robot_id, "source": "scan_match", "x": x, "y": y, "yaw": yaw,
                                      "score": estimate.score, "confidence_ratio": estimate.confidence_ratio}))
                    return
        raise RuntimeError("AMCL pose did not converge near the scan match")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
