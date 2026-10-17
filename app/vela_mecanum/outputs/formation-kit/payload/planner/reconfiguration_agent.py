"""Per-car ROS 2 waypoint executor with local fail-closed guards."""

from __future__ import annotations

import argparse
import json
import math
import signal
import time

ROBOT_IDS = tuple(f"robot{i}" for i in range(1, 5))
MAX_LINEAR_SPEED_MPS = 0.875
MIN_SEPARATION_M = 0.30
ROUTE_LOOKAHEAD_M = 0.28
ROUTE_MIN_SPEED_MPS = 0.30
ROUTE_GAIN = 3.5
LIDAR_HALF_ANGLE_RAD = math.radians(30)
LIDAR_HALF_ANGLE_COS = math.cos(LIDAR_HALF_ANGLE_RAD)
LIDAR_CLEARANCE_M = 0.25


def _advance_trajectory(route, index: int, x: float, y: float):
    if not route:
        return 0, 0.0, 0.0, 0.0, True
    index = min(max(0, index), len(route) - 1)
    while index < len(route) - 1:
        tx, ty = route[index]
        if math.hypot(tx - x, ty - y) > ROUTE_LOOKAHEAD_M:
            break
        index += 1
    tx, ty = route[index]
    dx, dy = tx - x, ty - y
    distance = math.hypot(dx, dy)
    complete = index == len(route) - 1 and distance <= 0.04
    if complete:
        return index, 0.0, 0.0, 0.0, True
    return index, dx, dy, distance, False


def _scan_path_clear(scan, direction: float) -> bool:
    count = 0
    minimum = math.inf
    angle = scan["angle_min"]
    increment = scan["angle_increment"]
    for value in scan["ranges"]:
        if math.isfinite(value) and value > 0.0 and math.cos(angle - direction) >= LIDAR_HALF_ANGLE_COS:
            count += 1
            minimum = min(minimum, value)
        angle += increment
    return count >= 3 and minimum >= LIDAR_CLEARANCE_M


def _body_velocity(yaw: float, world_x: float, world_y: float) -> tuple[float, float]:
    return (
        math.cos(yaw) * world_x + math.sin(yaw) * world_y,
        -math.sin(yaw) * world_x + math.cos(yaw) * world_y,
    )


def _route_velocity(dx: float, dy: float, distance: float, limit: float) -> tuple[float, float]:
    if not math.isfinite(distance) or distance <= 0.0:
        return 0.0, 0.0
    speed = min(limit, max(ROUTE_MIN_SPEED_MPS, ROUTE_GAIN * distance))
    return speed * dx / distance, speed * dy / distance


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
    # 在 ROS context 关闭前发送安全零速指令。
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node(f"formation_agent_{robot_id}")
    velocity = node.create_publisher(Twist, f"/{robot_id}/controller/cmd_vel", 10)
    status_pub = node.create_publisher(String, "/formation/agent_status", 10)
    poses = {}
    scan = {"ranges": (), "angle_min": 0.0, "angle_increment": 0.0, "arrival": -1e9}
    command = {"mission_id": None, "waypoint": None, "velocity": None, "trajectory": None,
               "trajectory_id": None, "trajectory_index": 0, "trajectory_speed": MAX_LINEAR_SPEED_MPS,
               "heading_rad": None, "arrival": -1e9, "stop": True}
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
                command.update(stop=True, waypoint=None, velocity=None, trajectory=None,
                               trajectory_id=None, trajectory_index=0, heading_rad=None, arrival=time.monotonic())
                return
            if data.get("robot_id") != robot_id:
                command.update(stop=True, waypoint=None, velocity=None, trajectory=None, arrival=time.monotonic())
                return
            mission_id = str(data["mission_id"])
            if not mission_id or mission_id == "None":
                return
            trajectory = data.get("trajectory")
            if trajectory is not None:
                trajectory_id = str(data.get("trajectory_id", ""))
                speed = float(data.get("speed_mps", MAX_LINEAR_SPEED_MPS))
                if (not trajectory_id or not isinstance(trajectory, list) or not trajectory
                        or len(trajectory) > 64 or not math.isfinite(speed) or speed <= 0):
                    return
                points = []
                for point in trajectory:
                    if not isinstance(point, list) or len(point) != 2:
                        return
                    values = (float(point[0]), float(point[1]))
                    if not all(math.isfinite(value) for value in values):
                        return
                    points.append(values)
                if command["trajectory_id"] != trajectory_id:
                    command["trajectory_index"] = 0
                command.update(mission_id=mission_id, waypoint=None, velocity=None,
                               trajectory=tuple(points), trajectory_id=trajectory_id,
                               trajectory_speed=min(MAX_LINEAR_SPEED_MPS, speed),
                               arrival=time.monotonic(), stop=False)
                return
            velocity = data.get("velocity")
            waypoint = data.get("waypoint")
            heading_rad = data.get("heading_rad")
            if heading_rad is not None:
                heading_rad = float(heading_rad)
                if not math.isfinite(heading_rad):
                    return
            if velocity is not None:
                if not isinstance(velocity, list) or len(velocity) != 2 or not all(math.isfinite(float(v)) for v in velocity):
                    return
                command.update(mission_id=mission_id, waypoint=None, trajectory=None,
                               velocity=(float(velocity[0]), float(velocity[1])),
                               heading_rad=heading_rad, arrival=time.monotonic(), stop=False)
                return
            if not isinstance(waypoint, list) or len(waypoint) != 2 or not all(math.isfinite(float(v)) for v in waypoint):
                return
            command.update(mission_id=mission_id, waypoint=(float(waypoint[0]), float(waypoint[1])),
                           trajectory=None,
                           velocity=None, heading_rad=heading_rad, arrival=time.monotonic(), stop=False)
        except (KeyError, TypeError, ValueError):
            return

    def fleet_state_callback(message: String):
        try:
            data = json.loads(message.data)
            received = time.monotonic()
            for name in ROBOT_IDS:
                if name == robot_id:
                    continue
                item = data["poses"][name]
                values = (float(item["x"]), float(item["y"]), float(item["yaw"]))
                valid = item.get("valid") is True and all(math.isfinite(v) for v in values)
                poses[name] = (*values, received, valid)
        except (KeyError, TypeError, ValueError):
            return

    subscriptions = []
    subscriptions.append(node.create_subscription(PoseWithCovarianceStamped, f"/{robot_id}/amcl_pose", pose_callback(robot_id), qos_profile_sensor_data))
    subscriptions.append(node.create_subscription(LaserScan, f"/{robot_id}/scan_raw", scan_callback, qos_profile_sensor_data))
    subscriptions.append(node.create_subscription(String, f"/{robot_id}/formation/fleet_state", fleet_state_callback, 10))
    subscriptions.append(node.create_subscription(String, f"/{robot_id}/formation/autonomous_command", command_callback, 10))

    def publish_control():
        nonlocal last_publish, last_published_stop
        now = time.monotonic()
        out = Twist()
        safe, reason = False, "no_waypoint"
        route_active = command["trajectory"] is not None
        route_index = command["trajectory_index"] if route_active else 0
        route_total = len(command["trajectory"]) if route_active else 0
        route_complete = False
        command_timeout = 2.0 if route_active else 0.9
        if command["stop"] or (command["waypoint"] is None and command["velocity"] is None and not route_active) or now - command["arrival"] > command_timeout:
            reason = "command_missing_or_stale"
        elif any(name not in poses or not poses[name][4] or now - poses[name][3] > 0.7 for name in ROBOT_IDS):
            reason = "pose_missing_or_stale"
        elif now - scan["arrival"] > 0.5:
            reason = "scan_missing_or_stale"
        else:
            x, y, yaw, _, _ = poses[robot_id]
            desired_heading = command["heading_rad"]
            heading_error = (desired_heading - yaw + math.pi) % (2 * math.pi) - math.pi if desired_heading is not None else 0.0
            if route_active:
                route = command["trajectory"]
                index, dx, dy, distance, route_complete = _advance_trajectory(
                    route, command["trajectory_index"], x, y
                )
                command["trajectory_index"] = index
                route_index = index
            elif command["velocity"] is not None:
                dx, dy = command["velocity"]
                distance = math.hypot(dx, dy)
            else:
                tx, ty = command["waypoint"]
                dx, dy = tx - x, ty - y
                distance = math.hypot(dx, dy)
            peers = [(name, math.hypot(x - poses[name][0], y - poses[name][1])) for name in ROBOT_IDS if name != robot_id]
            if any(separation < MIN_SEPARATION_M for _, separation in peers):
                reason = "peer_too_close"
            elif not (-3.18 <= x <= 3.18 and -3.18 <= y <= 3.18):
                reason = "outside_arena"
            elif distance <= 0.035:
                if desired_heading is not None and abs(heading_error) > 0.04:
                    out.angular.z = max(-0.60, min(0.60, 1.5 * heading_error))
                    safe, reason = True, "tracking"
                else:
                    safe, reason = True, "waypoint_reached"
            else:
                if route_active:
                    world_x, world_y = _route_velocity(dx, dy, distance, command["trajectory_speed"])
                elif command["velocity"] is not None:
                    speed = min(MAX_LINEAR_SPEED_MPS, distance)
                    world_x, world_y = speed * dx / distance, speed * dy / distance
                else:
                    speed = min(MAX_LINEAR_SPEED_MPS, 1.1 * distance)
                    world_x, world_y = speed * dx / distance, speed * dy / distance
                speed_scale = 1.0
                for name, separation in peers:
                    closing = ((poses[name][0] - x) * world_x + (poses[name][1] - y) * world_y) > 0
                    if closing and separation < 0.55:
                        speed_scale = min(speed_scale, max(0.0, (separation - MIN_SEPARATION_M) / (0.55 - MIN_SEPARATION_M)))
                if speed_scale < 1.0:
                    world_x *= speed_scale
                    world_y *= speed_scale
                if any(separation < MIN_SEPARATION_M and
                       ((poses[name][0] - x) * world_x + (poses[name][1] - y) * world_y) > 0
                       for name, separation in peers):
                    reason = "closing_on_peer"
                else:
                    body_x, body_y = _body_velocity(yaw, world_x, world_y)
                    direction = math.atan2(body_y, body_x)
                    if not _scan_path_clear(scan, direction):
                        if desired_heading is not None and abs(heading_error) > 0.04:
                            out.angular.z = max(-0.60, min(0.60, 1.5 * heading_error))
                            safe, reason = True, "tracking"
                        else:
                            reason = "lidar_path_blocked"
                    else:
                        out.linear.x, out.linear.y = body_x, body_y
                        out.angular.z = max(-0.60, min(0.60, 1.5 * heading_error))
                        safe, reason = True, "tracking"
        # 运动状态保持 10 Hz，空闲状态降低到 2 Hz，停止转换在下一个周期发送。
        stopped = command["stop"] or (command["waypoint"] is None and command["velocity"] is None and command["trajectory"] is None)
        publish_period = 0.5 if stopped else 0.1
        stop_transition = stopped and last_published_stop is False
        if not stop_transition and now - last_publish < publish_period:
            return
        velocity.publish(out)
        status = String()
        status.data = json.dumps({"robot_id": robot_id, "experiment_id": command["mission_id"],
                                  "safe": safe, "reason": reason, "timestamp_s": time.time(),
                                  "trajectory_active": route_active,
                                  "trajectory_index": route_index,
                                  "trajectory_total": route_total,
                                  "route_complete": route_complete}, separators=(",", ":"))
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
        if rclpy.ok():
            for _ in range(5):
                velocity.publish(Twist())
                time.sleep(0.05)
        executor.remove_node(node)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
