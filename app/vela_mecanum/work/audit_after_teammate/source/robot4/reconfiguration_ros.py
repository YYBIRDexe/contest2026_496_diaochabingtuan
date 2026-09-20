"""ROS 2 planning monitor for four MentorPi cars. Never publishes velocity."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import threading
import time
import uuid

from formation_planner import FormationPlanner, OccupancyGrid, Pose, Request, ROBOT_IDS
from reconfiguration_session import ReconfigurationSession, Telemetry


def main():
    import rclpy
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from std_msgs.msg import String
    from rclpy.qos import qos_profile_sensor_data

    parser = argparse.ArgumentParser()
    parser.add_argument("--robot-id", choices=ROBOT_IDS, required=True)
    parser.add_argument("--map", type=Path, default=Path("/opt/openvela-formation/maps/classroom.pgm"))
    parser.add_argument("--execute", action="store_true", help="publish waypoints to per-car agents")
    args = parser.parse_args()
    grid = OccupancyGrid(args.map, 0.05, (-10.2, -5.04))
    planner = FormationPlanner(map_grid=grid)
    rclpy.init()
    node = rclpy.create_node(f"formation_reconfiguration_{args.robot_id}")
    publisher = node.create_publisher(String, f"/{args.robot_id}/formation/reconfiguration_status", 10)
    command_pub = node.create_publisher(String, "/formation/reconfiguration_command", 10)
    lock = threading.Lock()
    poses: dict[str, Telemetry] = {}
    scan_arrival: dict[str, float] = {}
    pending: list[Request] = []
    session: ReconfigurationSession | None = None
    mission_id: str | None = None
    stopping = threading.Event()

    def on_pose(robot):
        def callback(message: PoseWithCovarianceStamped):
            p = message.pose.pose
            q = p.orientation
            cov = message.pose.covariance
            stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
            stamp_ok = abs(time.time() - stamp) <= 0.7
            valid = (
                message.header.frame_id.lstrip("/") == "map"
                and stamp_ok
                and all(math.isfinite(v) for v in (p.position.x, p.position.y, q.z, q.w, cov[0], cov[7], cov[35]))
                and 0 <= cov[0] <= 0.25 and 0 <= cov[7] <= 0.25 and 0 <= cov[35] <= 0.25
            )
            yaw = 2 * math.atan2(q.z, q.w)
            with lock:
                poses[robot] = Telemetry(
                    Pose(float(p.position.x), float(p.position.y), yaw) if valid else None,
                    time.monotonic(),
                    True,
                    max(float(cov[0]), float(cov[7])) if valid else 1.0,
                    float(cov[35]) if valid else 1.0,
                )
        return callback

    def on_scan_alive(robot):
        def callback(message: String):
            try:
                data = json.loads(message.data)
                if data.get("robot") != robot or data.get("fresh") is not True:
                    return
            except (TypeError, ValueError):
                return
            with lock:
                scan_arrival[robot] = time.monotonic()
        return callback

    subscriptions = []
    for robot in ROBOT_IDS:
        subscriptions.append(node.create_subscription(PoseWithCovarianceStamped, f"/{robot}/amcl_pose", on_pose(robot), qos_profile_sensor_data))
        subscriptions.append(node.create_subscription(String, f"/{robot}/fleet/scan_alive", on_scan_alive(robot), 10))

    def on_request(message: String):
        try:
            data = json.loads(message.data)
            request = Request(str(data["formation"]), float(data.get("spacing_m", 0.5)), assignment="auto")
            if request.formation not in ("square", "line", "circle", "diamond"):
                raise ValueError("unsupported formation")
            with lock:
                pending.append(request)
        except (KeyError, TypeError, ValueError) as exc:
            node.get_logger().warn(f"invalid reconfiguration request: {exc}")

    subscriptions.append(node.create_subscription(String, "/formation/reconfiguration_request", on_request, 10))

    def monitor():
        nonlocal session, mission_id
        while not stopping.is_set():
            now = time.monotonic()
            with lock:
                if pending:
                    session = ReconfigurationSession(planner, pending[-1])
                    mission_id = str(uuid.uuid4())
                    pending.clear()
                readings = {}
                for robot in ROBOT_IDS:
                    item = poses.get(robot)
                    fresh_scan = now - scan_arrival.get(robot, -1e6) <= 0.7
                    if item is None:
                        readings[robot] = Telemetry(None, 0, False, lidar_fresh=fresh_scan)
                    else:
                        readings[robot] = Telemetry(item.pose, item.stamp_s, now - item.stamp_s <= 0.7,
                                                    item.xy_variance_m2, item.yaw_variance_rad2, fresh_scan)
            if session is not None:
                decision = session.tick(now, readings)
                payload = {
                    "robot_id": args.robot_id,
                    "state": decision.state,
                    "reason": decision.reason,
                    "stop_all": decision.stop_all,
                    "moving_robot": decision.robot_id,
                    "waypoint": decision.waypoint,
                    "execution_enabled": args.execute,
                    "plan_steps": len(session.plan.steps) if session.plan else 0,
                }
            else:
                payload = {"robot_id": args.robot_id, "state": "IDLE", "stop_all": True,
                           "execution_enabled": args.execute, "reason": "awaiting request"}
            move = String()
            if args.execute and session is not None and not decision.stop_all and decision.robot_id and decision.waypoint:
                move.data = json.dumps({"mission_id": mission_id, "robot_id": decision.robot_id,
                                        "waypoint": decision.waypoint, "stop_all": False}, separators=(",", ":"))
            else:
                move.data = '{"stop_all":true}'
            command_pub.publish(move)
            output = String()
            output.data = json.dumps(payload, separators=(",", ":"))
            publisher.publish(output)
            stopping.wait(0.5)

    worker = threading.Thread(target=monitor, name="reconfiguration-monitor", daemon=True)
    worker.start()
    try:
        rclpy.spin(node)
    finally:
        stopping.set()
        worker.join(timeout=2)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

# BEST_EFFORT pose tuning: amcl_pose is a lossy-link stream, not a control message.
