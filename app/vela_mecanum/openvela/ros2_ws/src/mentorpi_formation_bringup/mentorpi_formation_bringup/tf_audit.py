#!/usr/bin/env python3
"""Check that every robot has a complete, unique map->odom->base TF chain."""

import argparse
import json
import math
import sys

import rclpy
from rclpy.duration import Duration
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--robots", nargs="+", default=["robot01", "robot02", "robot03", "robot04"])
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--min-separation", type=float, default=0.05)
    args = parser.parse_args(argv)
    rclpy.init()
    node = rclpy.create_node("mentorpi_tf_audit")
    buffer = Buffer(cache_time=Duration(seconds=30.0))
    listener = TransformListener(buffer, node, spin_thread=False)
    deadline = node.get_clock().now() + Duration(seconds=args.timeout)
    result = {"ok": True, "robots": {}, "errors": []}
    while rclpy.ok() and node.get_clock().now() < deadline:
        all_ready = True
        for robot in args.robots:
            base = f"{robot}/base_link"
            odom = f"{robot}/odom"
            try:
                map_to_base = buffer.lookup_transform("map", base, Time())
                buffer.lookup_transform("map", odom, Time())
                buffer.lookup_transform(odom, base, Time())
                t = map_to_base.transform.translation
                finite = all(math.isfinite(value) for value in (t.x, t.y, t.z))
                result["robots"][robot] = {"map_to_base": [t.x, t.y, t.z], "finite": finite}
                if not finite:
                    result["ok"] = False
                    result["errors"].append(f"{robot}: non-finite transform")
            except TransformException:
                all_ready = False
        if all_ready:
            break
        rclpy.spin_once(node, timeout_sec=0.1)
    for robot in args.robots:
        if robot not in result["robots"]:
            result["ok"] = False
            result["errors"].append(f"{robot}: missing map->odom->base_link chain")
    ready = sorted(result["robots"])
    for index, first in enumerate(ready):
        p1 = result["robots"][first]["map_to_base"]
        for second in ready[index + 1 :]:
            p2 = result["robots"][second]["map_to_base"]
            distance = math.hypot(p1[0] - p2[0], p1[1] - p2[1])
            if distance < args.min_separation:
                result["ok"] = False
                result["errors"].append(
                    f"{first}/{second}: map poses overlap ({distance:.4f} m); initialize each robot separately"
                )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    del listener
    node.destroy_node()
    rclpy.shutdown()
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
