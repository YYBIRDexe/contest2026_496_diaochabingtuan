#!/usr/bin/env python3
"""Validate the MentorPi M1 ROS graph before any wheel command is enabled."""

import argparse
import json
import sys
import time

import rclpy


EXPECTED_TYPES = {
    "cmd_vel": "geometry_msgs/msg/Twist",
    "odom": "nav_msgs/msg/Odometry",
    "scan": "sensor_msgs/msg/LaserScan",
    "pose": "geometry_msgs/msg/PoseWithCovarianceStamped",
}


def _topic(namespace: str, suffix: str) -> str:
    return f"/{namespace.strip('/')}/{suffix.strip('/')}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Probe CZ225 / MentorPi M1 ROS2 interfaces")
    parser.add_argument("--namespace", default="robot01")
    parser.add_argument("--cmd-vel", default="controller/cmd_vel")
    parser.add_argument("--odom", default="odom")
    parser.add_argument("--scan", default="scan_raw")
    parser.add_argument("--pose", default="amcl_pose")
    parser.add_argument("--require-localization", action="store_true")
    parser.add_argument("--allow-command-publishers", action="store_true")
    parser.add_argument("--timeout", type=float, default=4.0)
    args, ros_args = parser.parse_known_args(argv)

    paths = {
        "cmd_vel": _topic(args.namespace, args.cmd_vel),
        "odom": _topic(args.namespace, args.odom),
        "scan": _topic(args.namespace, args.scan),
        "pose": _topic(args.namespace, args.pose),
    }
    required = ("cmd_vel", "odom", "scan", "pose") if args.require_localization else ("cmd_vel", "odom", "scan")
    rclpy.init(args=ros_args)
    node = rclpy.create_node("mentorpi_hardware_probe")
    deadline = time.monotonic() + args.timeout
    graph = {}
    while rclpy.ok() and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
        graph = dict(node.get_topic_names_and_types())
        if all(path in graph for path in (paths[key] for key in required)):
            break

    result = {"ok": True, "namespace": args.namespace, "interfaces": {}, "errors": []}
    for name, path in paths.items():
        types = graph.get(path, [])
        publishers = len(node.get_publishers_info_by_topic(path)) if types else 0
        subscribers = len(node.get_subscriptions_info_by_topic(path)) if types else 0
        required_now = name in required
        type_ok = EXPECTED_TYPES[name] in types
        endpoint_ok = subscribers > 0 if name == "cmd_vel" else publishers > 0
        conflict_free = name != "cmd_vel" or args.allow_command_publishers or publishers == 0
        ok = (not required_now) or (type_ok and endpoint_ok and conflict_free)
        result["interfaces"][name] = {
            "topic": path,
            "types": types,
            "publishers": publishers,
            "subscribers": subscribers,
            "required": required_now,
            "ok": ok,
        }
        if not ok:
            result["ok"] = False
            direction = "subscriber" if name == "cmd_vel" else "publisher"
            detail = f"expected {EXPECTED_TYPES[name]} with a {direction}"
            if name == "cmd_vel" and publishers and not args.allow_command_publishers:
                detail += "; competing command publisher detected"
            result["errors"].append(f"{path}: {detail}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    node.destroy_node()
    rclpy.shutdown()
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
