"""One command: verify live map/code, localize four cars, then form a shape.

Requires the per-car fleet_endpoint/agent and a prepared SSH key. This process
must remain running during the mission. On process loss the 0.9 s agent command
timeout and 12 s command-bridge lease expire independently on every car.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import sys
import threading
import time
import uuid

import paramiko

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "payload" / "planner"))
from formation_planner import FormationPlanner, OccupancyGrid, Pose, Request, ROBOT_IDS  # noqa: E402
from reconfiguration_session import ReconfigurationSession, Telemetry  # noqa: E402
from synchronized_formation import (  # noqa: E402
    FormationTranslateSession,
    SquareTurnSession,
    SynchronizedFormationSession,
    TranslateThenLineSession,
    build_spread_plan,
    build_synchronized_plan,
)
from scan_localizer import map_metadata  # noqa: E402

KEY_PATH = WORKSPACE / "work" / "keys" / "formation_autonomy_ed25519"
HOST_KEYS = WORKSPACE / "work" / "keys" / "formation_known_hosts"
MAP_PATH = ROOT / "payload" / "evidence" / "current_map" / "classroom.pgm"
REMOTE_ROOT = "/opt/openvela-formation/formation_lab"
LEASE_PATH = "/run/openvela-formation/command-arm.json"


def connect(robot: str) -> paramiko.SSHClient:
    if not KEY_PATH.is_file() or not HOST_KEYS.is_file():
        raise RuntimeError("SSH key setup is missing; see README.md")
    error = None
    for attempt in range(3):
        client = paramiko.SSHClient()
        client.load_host_keys(str(HOST_KEYS))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(f"192.168.1.{200 + int(robot[-1])}", username="pi", key_filename=str(KEY_PATH),
                           look_for_keys=False, allow_agent=False, timeout=5, auth_timeout=5)
            return client
        except (OSError, paramiko.SSHException) as exc:
            error = exc
            client.close()
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"{robot}: SSH unavailable: {error}")


def run(client: paramiko.SSHClient, command: str, input_text: str | None = None, timeout: int = 20) -> str:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    if input_text is not None:
        stdin.write(input_text)
        stdin.channel.shutdown_write()
    result = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"remote command exit={code}: {error[-300:] or result[-300:]}")
    return result.strip()


def check_car(robot: str, map_sha: str) -> None:
    import hashlib
    client = connect(robot)
    try:
        expected = [
            "auto_localize.py",
            "scan_localizer.py",
            "fleet_endpoint.py",
            "formation_planner.py",
            "reconfiguration_agent.py",
            "reconfiguration_session.py",
        ]
        remote_hashes = run(client, "docker exec MentorPi sha256sum " + " ".join(f"{REMOTE_ROOT}/{name}" for name in expected))
        actual = {Path(line.split()[-1]).name: line.split()[0] for line in remote_hashes.splitlines()}
        for name in expected:
            digest = hashlib.sha256((ROOT / "payload" / "planner" / name).read_bytes()).hexdigest()
            if actual.get(name) != digest:
                raise RuntimeError(f"{robot}: deployed {name} differs from the tested copy")
        current_map = run(client, "docker exec MentorPi sha256sum /home/ubuntu/shared/classroom.pgm").split()[0]
        if current_map != map_sha:
            raise RuntimeError(f"{robot}: map differs from the tested map")
        states = run(client, f"systemctl is-active formation-agent@{robot}.service formation-command-bridge@{robot}.service")
        if states.splitlines() != ["active", "active"]:
            raise RuntimeError(f"{robot}: required services are not active: {states}")
        enabled = run(client, "docker exec MentorPi python3 -c 'import json; print(json.load(open(\"/opt/openvela-formation/config/mentorpi.json\"))[\"hardware_output_enabled\"])'")
        if enabled != "True":
            raise RuntimeError(f"{robot}: motor output gate is disabled")
        print(f"{robot}: map, code and services verified", flush=True)
    finally:
        client.close()


def localize_car(robot: str) -> dict:
    client = connect(robot)
    try:
        domain = int(robot[-1])
        command = (f"docker exec -u ubuntu -e ROS_DOMAIN_ID={domain} MentorPi bash -lc "
                   f"'source /opt/ros/humble/setup.bash; exec python3 {REMOTE_ROOT}/auto_localize.py "
                   f"--robot-id {robot} --timeout 35'")
        output = run(client, command, timeout=45)
        data = json.loads(output.splitlines()[-1])
        if data.get("robot_id") != robot or not all(math.isfinite(float(data[key])) for key in ("x", "y", "yaw")):
            raise RuntimeError(f"{robot}: invalid localization result")
        print(f"{robot}: {data['source']} x={data['x']:.2f} y={data['y']:.2f}", flush=True)
        return data
    finally:
        client.close()


class Endpoint:
    def __init__(self, robot: str):
        self.robot = robot
        self.lock = threading.Lock()
        self.latest: dict | None = None
        self.received_at = -1e9
        self.channel = None
        self.client = None
        self.closed = threading.Event()
        self.opened_at = -1e9
        self.thread = threading.Thread(target=self._loop, name=f"endpoint-{robot}", daemon=True)

    def start(self):
        self.thread.start()

    def _loop(self):
        had_connection = False
        while not self.closed.is_set():
            try:
                if had_connection:
                    # 小车重新启动后需要重新初始化 AMCL，再恢复 fleet telemetry。
                    localize_car(self.robot)
                self.client = connect(self.robot)
                self.client.get_transport().set_keepalive(2)
                channel = self.client.get_transport().open_session()
                channel.settimeout(1.0)
                command = ("docker exec -i -u ubuntu -e ROS_DOMAIN_ID=42 MentorPi bash -lc "
                           f"'source /opt/ros/humble/setup.bash; exec python3 -u {REMOTE_ROOT}/fleet_endpoint.py "
                           f"--robot-id {self.robot}'")
                channel.exec_command(command)
                had_connection = True
                self.opened_at = time.monotonic()
                with self.lock:
                    self.channel = channel
                buffer = b""
                opened_at = time.monotonic()
                while not self.closed.is_set() and not channel.exit_status_ready():
                    with self.lock:
                        last_seen = self.received_at
                    if time.monotonic() - max(opened_at, last_seen) > 5.0:
                        raise RuntimeError("telemetry stream stalled")
                    if channel.recv_ready():
                        buffer += channel.recv(65536)
                        while b"\n" in buffer:
                            raw, buffer = buffer.split(b"\n", 1)
                            if raw.startswith(b"@"):
                                try:
                                    data = json.loads(raw[1:])
                                    if data.get("robot_id") == self.robot and data.get("type") == "telemetry":
                                        with self.lock:
                                            self.latest = data
                                            self.received_at = time.monotonic()
                                except (UnicodeDecodeError, ValueError):
                                    pass
                    else:
                        self.closed.wait(0.02)
            except Exception as exc:
                print(f"{self.robot}: endpoint reconnecting ({exc})", flush=True)
            finally:
                with self.lock:
                    self.channel = None
                    self.latest = None
                    self.received_at = -1e9
                if self.client is not None:
                    self.client.close()
                if not self.closed.is_set():
                    self.closed.wait(2.0)

    def snapshot(self) -> tuple[dict | None, float]:
        with self.lock:
            return self.latest, self.received_at

    def send(self, kind: str, payload: dict):
        body = json.dumps({"type": kind, "payload": payload}, separators=(",", ":")) + "\n"
        with self.lock:
            if self.channel is not None and not self.channel.closed:
                self.channel.sendall(body.encode())

    def stop(self):
        self.closed.set()
        with self.lock:
            if self.channel is not None:
                self.channel.close()
        self.thread.join(timeout=3)


class LeaseKeeper:
    def __init__(self):
        self.identifier = str(uuid.uuid4())
        self.armed = threading.Event()
        self.closed = threading.Event()
        self.error: str | None = None
        self.thread = threading.Thread(target=self._loop, name="lease-keeper", daemon=True)

    def start(self):
        self.thread.start()

    def _write(self, robot: str):
        client = connect(robot)
        try:
            code = f'''
import json, os, pathlib, time
p=pathlib.Path("{LEASE_PATH}")
p.parent.mkdir(parents=True,exist_ok=True)
tmp=p.with_suffix(".tmp")
tmp.write_text(json.dumps({{"id":"{self.identifier}","robot":"{robot}","expires_mono":time.monotonic()+12.0}}))
# bridge 使用 ubuntu 用户运行，租约由 root 创建并提供只读权限。
os.chmod(tmp,0o644)
os.replace(tmp,p)
'''
            run(client, "docker exec -i MentorPi python3 -", code, timeout=10)
        finally:
            client.close()

    def _revoke(self, robot: str):
        try:
            client = connect(robot)
            try:
                run(client, f"docker exec MentorPi python3 -c 'import pathlib; pathlib.Path(\"{LEASE_PATH}\").unlink(missing_ok=True)'", timeout=10)
            finally:
                client.close()
        except Exception:
            pass  # The short lease still expires locally.

    def _loop(self):
        was_armed = False
        refreshed_at = -1e9
        while not self.closed.is_set():
            if self.armed.is_set():
                if time.monotonic() - refreshed_at >= 4.0:
                    try:
                        with ThreadPoolExecutor(max_workers=4) as pool:
                            list(pool.map(self._write, ROBOT_IDS))
                        self.error = None
                        refreshed_at = time.monotonic()
                    except Exception as exc:
                        self.error = str(exc)
                was_armed = True
            elif was_armed:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(self._revoke, ROBOT_IDS))
                was_armed = False
            self.closed.wait(0.1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(self._revoke, ROBOT_IDS))

    def stop(self):
        self.closed.set()
        self.thread.join(timeout=15)


def main():
    import hashlib
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("formation", choices=("square", "line", "circle", "diamond", "triangle"))
    parser.add_argument("--spacing", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=360.0, help="whole mission timeout in seconds")
    parser.add_argument("--check-only", action="store_true", help="verify deployment without localization or motion")
    parser.add_argument("--validate-motion", action="store_true", help="localize and validate the requested route without arming motors")
    parser.add_argument("--simulate", action="store_true", help="run saved-map digital twin; no robot connection")
    parser.add_argument("--motion-mode", choices=("sequential", "synchronized"), default="sequential")
    parser.add_argument("--mission", choices=("formation", "formation-forward", "translate-then-line", "square-turn"), default="formation")
    parser.add_argument("--travel", type=float, default=1.0, help="formation travel distance in meters")
    parser.add_argument("--straight", type=float, default=0.6, help="straight distance before and after the turn")
    parser.add_argument("--turn-radius", type=float, default=0.4)
    parser.add_argument("--turn-direction", choices=("auto", "left", "right"), default="auto")
    parser.add_argument("--cruise-speed", type=float, default=0.15)
    args = parser.parse_args()
    if args.simulate:
        from simulate_current_map import run as simulate
        data_dir = ROOT / "payload" / "evidence" / "current_map"
        print(json.dumps(simulate(data_dir, args.formation, args.spacing), indent=2), flush=True)
        return
    map_sha = hashlib.sha256(MAP_PATH.read_bytes()).hexdigest()
    deadline = time.monotonic() + args.timeout
    while True:
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda robot: check_car(robot, map_sha), ROBOT_IDS))
            if args.check_only:
                print("PREFLIGHT_OK", flush=True)
                return
            with ThreadPoolExecutor(max_workers=4) as pool:
                initial = {robot: result for robot, result in zip(ROBOT_IDS, pool.map(localize_car, ROBOT_IDS))}
            break
        except Exception as exc:
            if args.check_only or args.validate_motion or time.monotonic() >= deadline:
                raise
            print(f"Waiting for all four cars and localization: {exc}", flush=True)
            time.sleep(3)
    poses = [initial[robot] for robot in ROBOT_IDS]
    for index, first in enumerate(poses):
        for second in poses[index + 1:]:
            if math.hypot(first["x"] - second["x"], first["y"] - second["y"]) < 0.30:
                raise RuntimeError("two localized cars are less than 0.30 m apart")
    resolution, origin = map_metadata(MAP_PATH)
    planner = FormationPlanner(arena=(-3.3, 3.3, -3.3, 3.3), map_grid=OccupancyGrid(MAP_PATH, resolution, origin))
    synchronized = args.motion_mode == "synchronized" or args.mission in ("formation-forward", "translate-then-line", "square-turn")
    if args.mission == "formation-forward":
        session = FormationTranslateSession(planner, args.travel, args.cruise_speed)
    elif args.mission == "translate-then-line":
        session = TranslateThenLineSession(planner, args.spacing, args.travel)
    elif args.mission == "square-turn":
        session = SquareTurnSession(
            planner, args.spacing, args.straight, args.turn_radius,
            args.cruise_speed, args.turn_direction,
        )
    elif synchronized:
        session = SynchronizedFormationSession(planner, Request(args.formation, args.spacing))
    else:
        session = ReconfigurationSession(planner, Request(args.formation, args.spacing))
    if args.validate_motion:
        current = {
            robot: Pose(float(initial[robot]["x"]), float(initial[robot]["y"]), float(initial[robot]["yaw"]))
            for robot in ROBOT_IDS
        }
        if args.mission == "formation-forward":
            session._snapshot_geometry(current)
        elif args.mission == "square-turn":
            session._build_square_targets(current)
        elif args.mission == "translate-then-line":
            geometry = session._snapshot_geometry(current)
            session._build_line_targets(
                current,
                geometry.translate_targets["robot4"],
                geometry.heading_rad,
            )
        elif synchronized:
            minimum_gap = min(
                math.hypot(current[first].x - current[second].x, current[first].y - current[second].y)
                for index, first in enumerate(ROBOT_IDS)
                for second in ROBOT_IDS[index + 1:]
            )
            if minimum_gap < planner.separation:
                build_spread_plan(planner, current, Request(args.formation, args.spacing))
            else:
                build_synchronized_plan(planner, current, Request(args.formation, args.spacing))
        else:
            planner.plan(current, Request(args.formation, args.spacing))
        print("MOTION_VALIDATION_OK", flush=True)
        return
    endpoints = {robot: Endpoint(robot) for robot in ROBOT_IDS}
    keeper = LeaseKeeper()
    for endpoint in endpoints.values():
        endpoint.start()
    keeper.start()
    last_state = None
    progress_key = None
    progress_started = -1e9
    progress_best_distance = math.inf
    progress_last_report = -1e9
    synchronized_started = -1e9
    synchronized_positions = None
    synchronized_blocked_since = -1e9
    handshake_started = -1e9
    armed_seen = -1e9
    mission_started = time.monotonic()
    paused_count = 0
    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            snapshots = {robot: endpoints[robot].snapshot() for robot in ROBOT_IDS}
            readings = {}
            fleet = {}
            for robot, (data, received) in snapshots.items():
                stream_connected = data is not None and now - received <= 1.2
                statuses_ready = bool(
                    stream_connected and data.get("agent") is not None and data.get("bridge") is not None
                )
                connected = statuses_ready
                pose_data = data.get("pose") if connected else None
                valid = bool(pose_data and pose_data.get("valid") and data.get("pose_age_s", 1e9) + now - received <= 0.7)
                pose = Pose(float(pose_data["x"]), float(pose_data["y"]), float(pose_data["yaw"])) if valid else None
                agent = data.get("agent") if connected else None
                path_clear = agent is None or agent.get("reason") not in ("lidar_path_blocked", "outside_arena")
                readings[robot] = Telemetry(pose, received, connected, float(pose_data["xy_variance_m2"]) if valid else 1.0,
                                            float(pose_data["yaw_variance_rad2"]) if valid else 1.0,
                                            bool(connected and data.get("lidar_fresh")), path_clear)
                fleet[robot] = {"x": pose.x if pose else 0.0, "y": pose.y if pose else 0.0,
                                "yaw": pose.yaw if pose else 0.0, "valid": valid}
            waiting_statuses = {
                robot: tuple(
                    name for name, value in (
                        ("agent status", (snapshots[robot][0] or {}).get("agent")),
                        ("command bridge status", (snapshots[robot][0] or {}).get("bridge")),
                    )
                    if value is None
                )
                for robot in ROBOT_IDS
                if snapshots[robot][0] is not None and now - snapshots[robot][1] <= 1.2
            }
            waiting_statuses = {robot: names for robot, names in waiting_statuses.items() if names}
            if waiting_statuses:
                keeper.armed.clear()
                waiting_key = ("WAITING_STATUS", tuple(sorted(waiting_statuses.items())))
                if last_state != waiting_key:
                    detail = "; ".join(
                        f"{robot}: " + " and ".join(names)
                        for robot, names in waiting_statuses.items()
                    )
                    print(f"WAITING: receiving live status ({detail})", flush=True)
                    last_state = waiting_key
                for endpoint in endpoints.values():
                    endpoint.send("fleet", {"poses": fleet})
                    endpoint.send("command", {"stop_all": True})
                time.sleep(0.2)
                continue
            started = time.monotonic()
            decision = session.tick(now, readings)
            if synchronized and decision.state == "PAUSED" and "path blocked by lidar" in decision.reason:
                if synchronized_blocked_since < 0:
                    synchronized_blocked_since = now
                elif now - synchronized_blocked_since > 20.0:
                    raise RuntimeError(f"synchronized path remained blocked for 20 s: {decision.reason}")
            else:
                synchronized_blocked_since = -1e9
            planning_delay = time.monotonic() - started
            stop = decision.stop_all or planning_delay > 0.5 or not all(reading.connected for reading in readings.values())
            if synchronized:
                motion_requested = bool(not stop and decision.commands)
            else:
                motion_requested = bool(not stop and decision.robot_id and decision.waypoint)
            keeper.armed.set() if motion_requested else keeper.armed.clear()
            if keeper.error:
                raise RuntimeError(f"lease renewal failed: {keeper.error}")
            all_bridges_armed = all(
                bool((((snapshots[robot][0] or {}).get("bridge") or {}).get("armed")))
                for robot in ROBOT_IDS
            )
            commands = {robot: {"stop_all": True} for robot in ROBOT_IDS}
            # 四个 bridge 确认短期租约后才发布 waypoint。
            if motion_requested and all_bridges_armed:
                if synchronized:
                    commands = {
                        robot: {"stop_all": False, "robot_id": robot,
                                "velocity": list((decision.velocities or {}).get(robot, (0.0, 0.0))),
                                "heading_rad": (decision.headings or {}).get(robot),
                                "mission_id": keeper.identifier}
                        for robot in ROBOT_IDS
                    }
                else:
                    commands = {robot: {"stop_all": True} for robot in ROBOT_IDS}
                    commands[decision.robot_id] = {
                        "stop_all": False,
                        "robot_id": decision.robot_id,
                        "waypoint": list(decision.waypoint),
                        "mission_id": keeper.identifier,
                    }
            for endpoint in endpoints.values():
                endpoint.send("fleet", {"poses": fleet})
                endpoint.send("command", commands[endpoint.robot])
            state_key = (decision.state, decision.reason)
            if state_key != last_state:
                print(f"{decision.state}: {decision.reason}", flush=True)
                if decision.state == "PAUSED":
                    paused_count += 1
                last_state = state_key
            if synchronized and decision.state == "RUNNING":
                current_positions = {
                    robot: (readings[robot].pose.x, readings[robot].pose.y)
                    for robot in ROBOT_IDS if readings[robot].pose is not None
                }
                if synchronized_started < 0 or synchronized_positions is None:
                    synchronized_started = now
                    synchronized_positions = current_positions
                elif sum(
                    math.hypot(current_positions[robot][0] - synchronized_positions[robot][0],
                               current_positions[robot][1] - synchronized_positions[robot][1])
                    for robot in ROBOT_IDS
                ) >= 0.03:
                    synchronized_started = now
                    synchronized_positions = current_positions
                if now - progress_last_report >= 2.0:
                    print(
                        f"PROGRESS synchronized: "
                        + ", ".join(
                            f"{robot}=({readings[robot].pose.x:.2f},{readings[robot].pose.y:.2f})"
                            for robot in ROBOT_IDS if readings[robot].pose is not None
                        ),
                        flush=True,
                    )
                    progress_last_report = now
                all_forwarding = all(
                    ((snapshots[robot][0] or {}).get("bridge") or {}).get("forwarding") is True
                    and ((snapshots[robot][0] or {}).get("agent") or {}).get("reason") == "tracking"
                    for robot in ROBOT_IDS
                )
                if all_bridges_armed and all_forwarding and now - synchronized_started > 15.0:
                    raise RuntimeError(
                        "synchronized motion made less than 0.03 m aggregate position progress in 15 s"
                    )
            elif not synchronized and decision.state == "RUNNING" and decision.robot_id and decision.waypoint:
                moving = decision.robot_id
                pose = readings[moving].pose
                assert pose is not None
                key = (moving, tuple(decision.waypoint))
                distance = math.hypot(pose.x - decision.waypoint[0], pose.y - decision.waypoint[1])
                if key != progress_key:
                    progress_key = key
                    handshake_started = now
                    armed_seen = -1e9
                    progress_started = -1e9
                    progress_best_distance = distance
                    progress_last_report = -1e9
                elif progress_started > 0 and distance < progress_best_distance - 0.01:
                    progress_started = now
                    progress_best_distance = distance
                data = snapshots[moving][0] or {}
                bridge = data.get("bridge") or {}
                agent = data.get("agent") or {}
                if all_bridges_armed and armed_seen < 0:
                    armed_seen = now
                forwarding = bridge.get("forwarding") is True and agent.get("reason") == "tracking"
                if forwarding and progress_started < 0:
                    progress_started = now
                    progress_best_distance = distance
                if now - progress_last_report >= 2.0:
                    print(
                        f"PROGRESS {moving}: pose=({pose.x:.2f},{pose.y:.2f}) "
                        f"goal=({decision.waypoint[0]:.2f},{decision.waypoint[1]:.2f}) "
                        f"remaining={distance:.2f}m agent={agent.get('reason')} "
                        f"bridge={bridge.get('reason')} armed={bridge.get('armed')} "
                        f"forwarding={bridge.get('forwarding')}",
                        flush=True,
                    )
                    progress_last_report = now
                if not all_bridges_armed and now - handshake_started > 15.0:
                    raise RuntimeError("not all four command bridges acknowledged the short lease within 15 s")
                if all_bridges_armed and not forwarding and now - armed_seen > 15.0:
                    raise RuntimeError(
                        f"{moving} command path did not reach forwarding within 15 s; "
                        f"agent={agent.get('reason')} bridge={bridge.get('reason')}"
                    )
                if progress_started > 0 and now - progress_started > 10.0:
                    raise RuntimeError(
                        f"{moving} made less than 0.01 m progress in 10 s; "
                        f"agent={agent.get('reason')} bridge={bridge.get('reason')} "
                        f"armed={bridge.get('armed')} forwarding={bridge.get('forwarding')}"
                    )
            else:
                progress_key = None
                handshake_started = -1e9
                armed_seen = -1e9
                progress_started = -1e9
                progress_best_distance = math.inf
                synchronized_started = -1e9
            if decision.state == "COMPLETE":
                final_poses = {robot: readings[robot].pose for robot in ROBOT_IDS}
                if synchronized:
                    targets = decision.commands
                    headings = decision.headings or {}
                else:
                    assert session.plan is not None
                    targets = session.plan.targets
                    headings = {}
                position_errors = {
                    robot: math.hypot(final_poses[robot].x - targets[robot][0], final_poses[robot].y - targets[robot][1])
                    for robot in ROBOT_IDS
                }
                yaw_errors = {
                    robot: abs((headings[robot] - final_poses[robot].yaw + math.pi) % (2 * math.pi) - math.pi)
                    for robot in ROBOT_IDS if robot in headings
                }
                minimum_gap = min(
                    math.hypot(final_poses[first].x - final_poses[second].x,
                               final_poses[first].y - final_poses[second].y)
                    for index, first in enumerate(ROBOT_IDS) for second in ROBOT_IDS[index + 1:]
                )
                report = {
                    "mission_id": keeper.identifier,
                    "mission": args.mission,
                    "elapsed_s": round(time.monotonic() - mission_started, 3),
                    "motion_elapsed_s": round(session.motion_finished_s - session.motion_started_s, 3)
                    if getattr(session, "motion_finished_s", None) is not None else None,
                    "paused_count": paused_count,
                    "minimum_gap_m": round(minimum_gap, 4),
                    "position_error_m": {robot: round(value, 4) for robot, value in position_errors.items()},
                    "yaw_error_rad": {robot: round(value, 4) for robot, value in yaw_errors.items()},
                    "final_pose": {
                        robot: {"x": round(final_poses[robot].x, 4), "y": round(final_poses[robot].y, 4),
                                "yaw": round(final_poses[robot].yaw, 4)}
                        for robot in ROBOT_IDS
                    },
                    "target": {
                        robot: {"x": round(targets[robot][0], 4), "y": round(targets[robot][1], 4),
                                "yaw": round(headings[robot], 4) if robot in headings else None}
                        for robot in ROBOT_IDS
                    },
                }
                report_dir = ROOT / "mission-reports"
                report_dir.mkdir(exist_ok=True)
                report_path = report_dir / f"{keeper.identifier}.json"
                report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
                print("FORMATION_RESULT " + json.dumps(report, separators=(",", ":")), flush=True)
                print(f"FORMATION_REPORT {report_path}", flush=True)
                print("FORMATION_COMPLETE", flush=True)
                return
            if decision.state in ("BLOCKED", "ABORTED"):
                raise RuntimeError(f"formation stopped: {decision.reason}")
            time.sleep(0.2)
        raise RuntimeError("mission timeout; all cars commanded to stop")
    finally:
        keeper.armed.clear()
        for _ in range(5):
            for endpoint in endpoints.values():
                endpoint.send("command", {"stop_all": True})
            time.sleep(0.1)
        keeper.stop()
        for endpoint in endpoints.values():
            endpoint.stop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted: stopping all cars", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"AUTO_FORMATION_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
