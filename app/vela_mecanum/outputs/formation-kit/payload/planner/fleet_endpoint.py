"""Per-car SSH/ROS endpoint for a one-command, TCP-backed fleet run."""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time


POSE_MAX_AGE_S = 0.9
LIDAR_MAX_AGE_S = 1.2
AGENT_MAX_AGE_S = 2.0
BRIDGE_MAX_AGE_S = 3.0


def main():
    import rclpy
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import String
    from rclpy.qos import qos_profile_sensor_data

    parser = argparse.ArgumentParser()
    parser.add_argument("--robot-id", required=True, choices=tuple(f"robot{i}" for i in range(1, 5)))
    args = parser.parse_args()
    robot = args.robot_id
    rclpy.init()
    node = rclpy.create_node(f"fleet_endpoint_{robot}")
    command_pub = node.create_publisher(String, f"/{robot}/formation/autonomous_command", 10)
    fleet_pub = node.create_publisher(String, f"/{robot}/formation/fleet_state", 10)
    lock = threading.Lock()
    state = {"pose": None, "pose_arrival": -1e9, "scan_arrival": -1e9, "agent": None,
             "agent_arrival": -1e9, "bridge": None, "bridge_arrival": -1e9}
    stopping = threading.Event()

    def on_pose(message: PoseWithCovarianceStamped):
        p, q = message.pose.pose.position, message.pose.pose.orientation
        cov = message.pose.covariance
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        # 部分 ROS 环境会返回 NumPy 标量，JSON telemetry 需要原生 bool。
        valid = bool(message.header.frame_id.lstrip("/") == "map" and abs(time.time() - stamp) <= POSE_MAX_AGE_S
                     and all(math.isfinite(v) for v in (p.x, p.y, q.z, q.w, cov[0], cov[7], cov[35]))
                     and 0 <= cov[0] <= 0.25 and 0 <= cov[7] <= 0.25 and 0 <= cov[35] <= 0.25)
        with lock:
            state["pose"] = {"x": float(p.x), "y": float(p.y), "yaw": 2 * math.atan2(q.z, q.w),
                             "xy_variance_m2": max(float(cov[0]), float(cov[7])),
                             "yaw_variance_rad2": float(cov[35]), "valid": valid}
            state["pose_arrival"] = time.monotonic()

    def on_scan(message: LaserScan):
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        if abs(time.time() - stamp) <= 0.7:
            with lock:
                state["scan_arrival"] = time.monotonic()

    def status_callback(kind):
        def callback(message: String):
            try:
                data = json.loads(message.data)
                if data.get("robot_id", data.get("robot")) != robot:
                    return
            except (TypeError, ValueError):
                return
            with lock:
                state[kind] = data
                state[kind + "_arrival"] = time.monotonic()
        return callback

    subscriptions = [
        node.create_subscription(PoseWithCovarianceStamped, f"/{robot}/amcl_pose", on_pose, qos_profile_sensor_data),
        node.create_subscription(LaserScan, f"/{robot}/scan_raw", on_scan, qos_profile_sensor_data),
        node.create_subscription(String, "/formation/agent_status", status_callback("agent"), 10),
        node.create_subscription(String, f"/{robot}/formation/command_bridge_status", status_callback("bridge"), 10),
    ]

    def send_status():
        now = time.monotonic()
        with lock:
            body = {"type": "telemetry", "robot_id": robot, "pose": state["pose"],
                    "pose_age_s": now - state["pose_arrival"],
                    "lidar_fresh": now - state["scan_arrival"] <= LIDAR_MAX_AGE_S,
                    "agent": state["agent"] if now - state["agent_arrival"] <= AGENT_MAX_AGE_S else None,
                    "bridge": state["bridge"] if now - state["bridge_arrival"] <= BRIDGE_MAX_AGE_S else None,
                    "agent_age_s": now - state["agent_arrival"],
                    "bridge_age_s": now - state["bridge_arrival"]}
        print("@" + json.dumps(body, separators=(",", ":")), flush=True)

    node.create_timer(0.2, send_status)

    def input_loop():
        try:
            for line in sys.stdin:
                try:
                    data = json.loads(line)
                    if data.get("type") == "command":
                        message = String()
                        message.data = json.dumps(data["payload"], separators=(",", ":"))
                        command_pub.publish(message)
                    elif data.get("type") == "fleet":
                        message = String()
                        message.data = json.dumps(data["payload"], separators=(",", ":"))
                        fleet_pub.publish(message)
                except (KeyError, TypeError, ValueError):
                    continue
        finally:
            for _ in range(5):
                message = String()
                message.data = '{"stop_all":true}'
                command_pub.publish(message)
                time.sleep(0.05)
            stopping.set()

    reader = threading.Thread(target=input_loop, name="endpoint-stdin", daemon=True)
    reader.start()
    try:
        while rclpy.ok() and not stopping.is_set():
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
