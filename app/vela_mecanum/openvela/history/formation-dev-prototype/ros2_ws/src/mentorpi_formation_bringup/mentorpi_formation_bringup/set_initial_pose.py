#!/usr/bin/env python3
"""Reliably seed one namespaced AMCL instance in the shared map frame."""

import argparse
import json
import math
import sys
import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--x", type=float, required=True)
    parser.add_argument("--y", type=float, required=True)
    parser.add_argument("--yaw", type=float, required=True, help="radians, counter-clockwise")
    parser.add_argument("--xy-variance", type=float, default=0.04)
    parser.add_argument("--yaw-variance", type=float, default=0.0685)
    parser.add_argument("--timeout", type=float, default=5.0)
    args, ros_args = parser.parse_known_args(argv)
    if args.xy_variance <= 0.0 or args.yaw_variance <= 0.0:
        parser.error("variances must be positive")

    rclpy.init(args=ros_args)
    node = rclpy.create_node("mentorpi_set_initial_pose")
    topic = f"/{args.namespace.strip('/')}/initialpose"
    publisher = node.create_publisher(PoseWithCovarianceStamped, topic, 10)
    deadline = time.monotonic() + args.timeout
    while rclpy.ok() and publisher.get_subscription_count() == 0 and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    if publisher.get_subscription_count() == 0:
        print(json.dumps({"ok": False, "topic": topic, "error": "no AMCL subscriber"}, ensure_ascii=False))
        node.destroy_node()
        rclpy.shutdown()
        return 2

    message = PoseWithCovarianceStamped()
    message.header.frame_id = "map"
    message.pose.pose.position.x = args.x
    message.pose.pose.position.y = args.y
    message.pose.pose.orientation.z = math.sin(args.yaw * 0.5)
    message.pose.pose.orientation.w = math.cos(args.yaw * 0.5)
    message.pose.covariance[0] = args.xy_variance
    message.pose.covariance[7] = args.xy_variance
    message.pose.covariance[35] = args.yaw_variance
    for _ in range(3):
        message.header.stamp = node.get_clock().now().to_msg()
        publisher.publish(message)
        rclpy.spin_once(node, timeout_sec=0.1)
    print(json.dumps({"ok": True, "topic": topic, "x": args.x, "y": args.y, "yaw": args.yaw}, ensure_ascii=False))
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
