#!/usr/bin/env python3
"""End-to-end ROS2 acceptance for four distributed formation agents."""

import argparse
import json
import math
import sys
import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from std_msgs.msg import String


ROBOT_IDS = ("Robot01", "Robot02", "Robot03", "Robot04")
TARGETS = {
    "Robot01": (-0.4, -0.4),
    "Robot02": (-0.4, 0.4),
    "Robot03": (0.4, 0.4),
    "Robot04": (0.4, -0.4),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control-mode", choices=("anchored", "laplacian", "second_order"), default="laplacian")
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--tolerance", type=float, default=0.10)
    args, ros_args = parser.parse_known_args(argv)
    rclpy.init(args=ros_args)
    node = rclpy.create_node("mentorpi_virtual_acceptance")
    mission_publisher = node.create_publisher(String, "/formation/mission", 10)
    poses = {}
    safe_agents = set()

    def pose_callback(robot_id):
        def callback(message: PoseWithCovarianceStamped):
            poses[robot_id] = (float(message.pose.pose.position.x), float(message.pose.pose.position.y))

        return callback

    subscriptions = [
        node.create_subscription(
            PoseWithCovarianceStamped,
            f"/{robot_id.lower()}/amcl_pose",
            pose_callback(robot_id),
            10,
        )
        for robot_id in ROBOT_IDS
    ]

    def status_callback(message: String):
        try:
            payload = json.loads(message.data)
            if payload.get("safe") and payload.get("reason") == "tracking":
                safe_agents.add(payload.get("robot_id"))
        except (TypeError, ValueError):
            pass

    subscriptions.append(node.create_subscription(String, "/formation/agent_status", status_callback, 20))

    start = time.monotonic()
    last_publish = 0.0
    max_error = math.inf
    success = False
    while rclpy.ok() and time.monotonic() - start < args.timeout:
        now = time.monotonic()
        if now - last_publish >= 0.2:
            message = String()
            message.data = json.dumps(
                {
                    "enabled": True,
                    "experiment_id": f"ros2-virtual-{args.control_mode}",
                    "formation": "square",
                    "spacing_m": 0.8,
                    "control_mode": args.control_mode,
                    "center_x": 0.0,
                    "center_y": 0.0,
                    "heading_rad": 0.0,
                },
                separators=(",", ":"),
            )
            mission_publisher.publish(message)
            last_publish = now
        rclpy.spin_once(node, timeout_sec=0.05)
        if len(poses) == 4:
            max_error = max(math.hypot(poses[key][0] - TARGETS[key][0], poses[key][1] - TARGETS[key][1]) for key in ROBOT_IDS)
            if max_error <= args.tolerance and safe_agents == set(ROBOT_IDS):
                success = True
                break

    stop = String()
    stop.data = '{"enabled":false,"state":"VIRTUAL_ACCEPTANCE_DONE"}'
    mission_publisher.publish(stop)
    rclpy.spin_once(node, timeout_sec=0.2)
    result = {
        "ok": success,
        "control_mode": args.control_mode,
        "elapsed_s": round(time.monotonic() - start, 3),
        "max_error_m": None if not math.isfinite(max_error) else round(max_error, 6),
        "safe_agents": sorted(safe_agents),
        "poses": {key: [round(value, 6) for value in poses[key]] for key in sorted(poses)},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    del subscriptions
    node.destroy_node()
    rclpy.shutdown()
    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
