"""Per-car ROS 2 waypoint executor with local fail-closed guards."""

from __future__ import annotations

import argparse
import json
import math
import signal
import time

ROBOT_IDS = tuple(f"robot{i}" for i in range(1, 5))


def main():
    import rclpy
    from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import String
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.signals import SignalHandlerOptions

    parser = argparse.ArgumentParser()
    parser.add_argument("--robot-id", required=True, choices=ROBOT_IDS)
    args = parser.parse_args()
    robot_id = args.robot_id
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node(f"formation_agent_{robot_id}")
    velocity = node.create_publisher(Twist, f"/{robot_id}/controller/cmd_vel", 10)
    status_pub = node.create_publisher(String, "/formation/agent_status", 10)
    poses = {}
    scan = {"ranges": (), "angle_min": 0.0, "angle_increment": 0.0, "arrival": -1e9}
    command = {"mission_id": None, "waypoint": None, "arrival": -1e9, "stop": True}
    last_publish = -1e9
    last_published_stop = None

    def pose_callback(name):
        def callback(message: PoseWithCovarianceStamped):
            p, q = message.pose.pose.position, message.pose.pose.orientation
            cov = message.pose.covariance
            stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
            valid = (
                message.header.frame_id.lstrip("/") == "map"
                and abs(time.time() - stamp) <= 0.7
                and all(math.isfinite(v) for v in (p.x, p.y, q.z, q.w, cov[0], cov[7], cov[35]))
                and 0 <= cov[0] <= 0.25 and 0 <= cov[7] <= 0.25 and 0 <= cov[35] <= 0.25
            )
            poses[name] = (float(p.x), float(p.y), 2 * math.atan2(q.z, q.w), time.monotonic(), valid)
        return callback

    def scan_callback(message: LaserScan):
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        if abs(time.time() - stamp) > 0.7:
            return
        scan.update(ranges=tuple(message.ranges), angle_min=message.angle_min,
                    angle_increment=message.angle_increment, arrival=time.monotonic())

    def command_callback(message: String):
        try:
            data = json.loads(message.data)
            if data.get("stop_all") is True:
                command.update(stop=True, waypoint=None, arrival=time.monotonic())
                return
            if data.get("robot_id") != robot_id:
                command.update(stop=True, waypoint=None, arrival=time.monotonic())
                return
            waypoint = data["waypoint"]
            if not isinstance(waypoint, list) or len(waypoint) != 2 or not all(math.isfinite(float(v)) for v in waypoint):
                return
            mission_id = str(data["mission_id"])
            if not mission_id or mission_id == "None":
                return
            command.update(mission_id=mission_id, waypoint=(float(waypoint[0]), float(waypoint[1])),
                           arrival=time.monotonic(), stop=False)
        except (KeyError, TypeError, ValueError):
            return

    subscriptions = []
    for name in ROBOT_IDS:
        subscriptions.append(node.create_subscription(PoseWithCovarianceStamped, f"/{name}/amcl_pose", pose_callback(name), qos_profile_sensor_data))
    subscriptions.append(node.create_subscription(LaserScan, f"/{robot_id}/scan_raw", scan_callback, qos_profile_sensor_data))
    subscriptions.append(node.create_subscription(String, "/formation/reconfiguration_command", command_callback, 10))

    def publish_control():
        nonlocal last_publish, last_published_stop
        now = time.monotonic()
        out = Twist()
        safe, reason = False, "no_waypoint"
        if command["stop"] or command["waypoint"] is None or now - command["arrival"] > 0.9:
            reason = "waypoint_missing_or_stale"
        elif any(name not in poses or not poses[name][4] or now - poses[name][3] > 0.7 for name in ROBOT_IDS):
            reason = "pose_missing_or_stale"
        elif now - scan["arrival"] > 0.5:
            reason = "scan_missing_or_stale"
        else:
            x, y, yaw, _, _ = poses[robot_id]
            tx, ty = command["waypoint"]
            dx, dy = tx - x, ty - y
            distance = math.hypot(dx, dy)
            peers = [(name, math.hypot(x - poses[name][0], y - poses[name][1])) for name in ROBOT_IDS if name != robot_id]
            if any(separation < 0.22 for _, separation in peers):
                reason = "peer_too_close"
            elif not (-2.88 <= x <= 2.88 and -2.88 <= y <= 2.88):
                reason = "outside_arena"
            elif distance <= 0.035:
                safe, reason = True, "waypoint_reached"
            else:
                speed = min(0.12, 0.6 * distance)
                world_x, world_y = speed * dx / distance, speed * dy / distance
                if any(separation < 0.35 and
                       ((poses[name][0] - x) * world_x + (poses[name][1] - y) * world_y) > 0
                       for name, separation in peers):
                    reason = "closing_on_peer"
                else:
                    body_x = math.cos(yaw) * world_x + math.sin(yaw) * world_y
                    body_y = -math.sin(yaw) * world_x + math.cos(yaw) * world_y
                    direction = math.atan2(body_y, body_x)
                    front_ranges = [float(r) for index, r in enumerate(scan["ranges"])
                                    if math.isfinite(r) and r > 0
                                    and abs(math.atan2(math.sin(scan["angle_min"] + index * scan["angle_increment"] - direction),
                                                       math.cos(scan["angle_min"] + index * scan["angle_increment"] - direction))) < math.radians(30)]
                    if len(front_ranges) < 3 or min(front_ranges) < 0.4:
                        reason = "lidar_path_blocked"
                    else:
                        out.linear.x, out.linear.y = body_x, body_y
                        safe, reason = True, "tracking"
        stopped = command["stop"] or command["waypoint"] is None
        publish_period = 0.5 if stopped else 0.1
        stop_transition = stopped and last_published_stop is False
        if not stop_transition and now - last_publish < publish_period:
            return
        velocity.publish(out)
        status = String()
        status.data = json.dumps({"robot_id": robot_id, "experiment_id": command["mission_id"],
                                  "safe": safe, "reason": reason, "timestamp_s": time.time()}, separators=(",", ":"))
        status_pub.publish(status)
        last_publish = now
        last_published_stop = stopped

    node.create_timer(0.05, publish_control)
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    stopping = False
    def request_stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        while not stopping:
            executor.spin_once(timeout_sec=0.1)
    finally:
        for _ in range(5):
            velocity.publish(Twist())
            time.sleep(0.05)
        executor.remove_node(node)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

# BEST_EFFORT pose tuning: amcl_pose is a lossy-link stream, not a control message.
