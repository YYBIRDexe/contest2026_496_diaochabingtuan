from __future__ import annotations

import csv
import json
import math
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .agent import CONTROL_MODES, AgentObservation, FORMATIONS, ROBOT_IDS, FormationMission, RobotFormationAgent, formation_offsets
from .laplacian import GraphTopology, default_topology
from .second_order import SecondOrderCommand, SecondOrderFormationAgent


class LabError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "invalid_request"):
        super().__init__(message)
        self.status = status
        self.code = code


class ExperimentState(str, Enum):
    IDLE = "IDLE"
    VALIDATING = "VALIDATING"
    FORMING = "FORMING"
    HOLDING = "HOLDING"
    STOPPING = "STOPPING"
    FINISHED = "FINISHED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


ACTIVE_STATES = {
    ExperimentState.VALIDATING,
    ExperimentState.FORMING,
    ExperimentState.HOLDING,
    ExperimentState.STOPPING,
}


@dataclass
class Robot:
    robot_id: str
    x: float
    y: float
    target_x: float = 0.0
    target_y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    yaw_rad: float = 0.0
    target_yaw_rad: float = 0.0
    wz: float = 0.0
    ax: float = 0.0
    ay: float = 0.0
    angular_accel: float = 0.0
    agent_safe: bool = True
    agent_reason: str = "idle"
    online: bool = True
    localization_ok: bool = True

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_m"] = round(math.hypot(self.target_x - self.x, self.target_y - self.y), 4)
        for key in ("x", "y", "target_x", "target_y", "vx", "vy", "yaw_rad", "target_yaw_rad", "wz", "ax", "ay", "angular_accel"):
            data[key] = round(data[key], 4)
        return data


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    formation: str
    spacing_m: float
    duration_s: float
    control_mode: str = "anchored"


class FormationSimulator:
    FORMATIONS = FORMATIONS

    def __init__(self, data_dir: Path, tick_s: float = 0.05, time_scale: float = 1.0):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tick_s = tick_s
        self.time_scale = time_scale
        self.arena_half_extent_m = 3.0
        self.min_distance_m = 0.25
        self.max_speed_mps = 0.65
        self.topology: GraphTopology = default_topology()
        self.position_tolerance_m = 0.05
        self.forming_timeout_s = 30.0
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._shutdown = False
        self._spec: ExperimentSpec | None = None
        self._state = ExperimentState.IDLE
        self._robots = self._initial_robots()
        self._agents = self._new_agents()
        self._message = "ready"
        self._error_code: str | None = None
        self._started_at: float | None = None
        self._formed_at: float | None = None
        self._finished_at: float | None = None
        self._last_update = time.monotonic()
        self._last_telemetry = 0.0
        self._trajectory_path: Path | None = None
        self._thread = threading.Thread(target=self._worker, name="formation-simulator", daemon=True)
        self._thread.start()

    @staticmethod
    def _initial_robots() -> list[Robot]:
        return [
            Robot("Robot01", -1.40, -1.00),
            Robot("Robot02", -1.40, 1.00),
            Robot("Robot03", 1.40, 1.00),
            Robot("Robot04", 1.40, -1.00),
        ]

    def _new_agents(self, control_mode: str = "anchored") -> dict[str, RobotFormationAgent]:
        if control_mode == "second_order":
            return {
                robot_id: SecondOrderFormationAgent(
                    robot_id,
                    max_linear_mps=self.max_speed_mps,
                    max_angular_radps=1.5,
                    arena_half_extent_m=self.arena_half_extent_m,
                    min_distance_m=self.min_distance_m,
                    topology=self.topology,
                )
                for robot_id in ROBOT_IDS
            }
        return {
            robot_id: RobotFormationAgent(
                robot_id,
                self.max_speed_mps,
                1.5,
                self.arena_half_extent_m,
                self.min_distance_m,
                control_mode=control_mode,
                topology=self.topology,
            )
            for robot_id in ROBOT_IDS
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            "platform": "Hiwonder MentorPi (Raspberry Pi 5)",
            "drive_model": "mecanum_holonomic",
            "command_axes": ["vx", "vy", "wz"],
            "control_architecture": "distributed_onboard_agents",
            "coordinator_output": "mission_and_parameters_only",
            "formations": list(self.FORMATIONS),
            "control_modes": {
                "anchored": "existing absolute-slot plus peer-relative controller",
                "laplacian": "standard displacement-consensus with virtual-leader pinning",
                "second_order": "standard pinned double-integrator consensus with position and velocity damping",
            },
            "default_control_mode": "anchored",
            "consensus_graph": self.topology.stability_report(),
            "robot_count": 4,
            "spacing_m": {"min": 0.35, "max": 2.5, "default": 0.8},
            "duration_s": {"min": 1, "max": 300, "default": 30},
            "arena": {"width_m": 6.0, "height_m": 6.0},
            "safety": {
                "min_distance_m": self.min_distance_m,
                "max_speed_mps": self.max_speed_mps,
                "checks": ["boundary", "separation", "online", "localization", "forming_timeout"],
            },
            "actions": ["start", "status", "stop", "reset", "capabilities"],
        }

    def handle_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LabError("JSON body must be an object")
        action = str(payload.get("action", "")).lower().strip()
        request_id = str(payload.get("request_id") or uuid.uuid4().hex[:12])
        if action == "capabilities":
            return {"ok": True, "request_id": request_id, "capabilities": self.capabilities()}
        if action == "start":
            result = self.start(payload)
        elif action == "status":
            result = self.snapshot()
        elif action == "stop":
            result = self.stop(str(payload.get("reason") or "operator_stop"))
        elif action == "reset":
            result = self.reset()
        elif action == "inject_fault":
            result = self.inject_fault(payload)
        else:
            raise LabError("action must be start, status, stop, reset, or capabilities")
        return {"ok": True, "request_id": request_id, "experiment": result}

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        formation = str(payload.get("formation", "square")).lower().strip()
        if formation not in self.FORMATIONS:
            raise LabError(f"unsupported formation: {formation}", code="unsupported_formation")
        try:
            spacing = float(payload.get("spacing_m", 0.8))
            duration = float(payload.get("duration_s", 30))
        except (TypeError, ValueError) as exc:
            raise LabError("spacing_m and duration_s must be numbers") from exc
        control_mode = str(payload.get("control_mode", "anchored")).lower().strip()
        if control_mode not in CONTROL_MODES:
            raise LabError(f"control_mode must be one of: {', '.join(CONTROL_MODES)}", code="unsupported_control_mode")
        graph_report = self.topology.stability_report()
        if control_mode == "laplacian" and not graph_report["exponentially_stable_nominal_model"]:
            raise LabError("consensus graph is not pinned/connected: lambda_min(L+B) must be positive", code="unstable_consensus_graph")
        if control_mode == "second_order" and not graph_report["second_order"]["exponentially_stable_nominal_model"]:
            raise LabError("second-order consensus model is not exponentially stable for this graph/gains", code="unstable_second_order_model")
        if not 0.35 <= spacing <= 2.5:
            raise LabError("spacing_m must be between 0.35 and 2.5", code="unsafe_spacing")
        if not 1 <= duration <= 300:
            raise LabError("duration_s must be between 1 and 300", code="unsafe_duration")
        experiment_id = str(payload.get("experiment_id") or f"exp-{time.strftime('%Y%m%d-%H%M%S')}")
        if not experiment_id or len(experiment_id) > 64 or not all(c.isalnum() or c in "-_" for c in experiment_id):
            raise LabError("experiment_id must use only letters, digits, '-' or '_'", code="bad_experiment_id")
        spec = ExperimentSpec(experiment_id, formation, spacing, duration, control_mode)

        with self._lock:
            if self._spec and self._spec.experiment_id == experiment_id:
                if self._spec == spec:
                    snap = self._snapshot_locked()
                    snap["idempotent_replay"] = True
                    return snap
                raise LabError("experiment_id already exists with different parameters", 409, "id_conflict")
            if self._state in ACTIVE_STATES:
                raise LabError("another experiment is already active", 409, "experiment_active")
            self._state = ExperimentState.VALIDATING
            self._spec = spec
            self._robots = self._initial_robots()
            self._agents = self._new_agents(control_mode)
            mission = FormationMission(experiment_id, formation, spacing, control_mode=control_mode)
            for robot in self._robots:
                agent = self._agents[robot.robot_id]
                agent.accept_mission(mission)
                robot.target_x, robot.target_y, robot.target_yaw_rad = agent.target_pose()
            self._message = "parameters accepted; forming"
            self._error_code = None
            self._started_at = time.time()
            self._formed_at = None
            self._finished_at = None
            self._last_update = time.monotonic()
            self._state = ExperimentState.FORMING
            run_dir = self.data_dir / experiment_id
            run_dir.mkdir(parents=True, exist_ok=True)
            self._trajectory_path = run_dir / "trajectory.csv"
            with self._trajectory_path.open("w", newline="", encoding="utf-8") as fp:
                csv.writer(fp).writerow(["time_s", "state", "robot_id", "x", "y", "yaw_rad", "target_x", "target_y", "target_yaw_rad", "vx", "vy", "wz", "ax", "ay", "angular_accel", "agent_safe", "agent_reason"])
            (run_dir / "request.json").write_text(json.dumps(asdict(spec), ensure_ascii=False, indent=2), encoding="utf-8")
            self._wake.set()
            return self._snapshot_locked()

    def stop(self, reason: str) -> dict[str, Any]:
        with self._lock:
            if self._state not in ACTIVE_STATES:
                raise LabError("no active experiment", 409, "no_active_experiment")
            self._state = ExperimentState.STOPPING
            self._message = reason[:120]
            self._error_code = "operator_stop"
            self._wake.set()
            return self._snapshot_locked()

    def reset(self) -> dict[str, Any]:
        with self._lock:
            if self._state in ACTIVE_STATES:
                raise LabError("stop the active experiment before reset", 409, "experiment_active")
            self._spec = None
            self._state = ExperimentState.IDLE
            self._robots = self._initial_robots()
            self._agents = self._new_agents()
            self._message = "ready"
            self._error_code = None
            self._started_at = self._formed_at = self._finished_at = None
            self._trajectory_path = None
            return self._snapshot_locked()

    def inject_fault(self, payload: dict[str, Any]) -> dict[str, Any]:
        fault = str(payload.get("fault", "")).lower()
        robot_id = str(payload.get("robot_id", "Robot01"))
        with self._lock:
            robot = next((r for r in self._robots if r.robot_id == robot_id), None)
            if not robot:
                raise LabError("unknown robot_id")
            if fault == "offline":
                robot.online = False
            elif fault == "localization_lost":
                robot.localization_ok = False
            elif fault == "boundary":
                robot.x = self.arena_half_extent_m + 0.2
            elif fault == "collision":
                other = self._robots[0 if robot is not self._robots[0] else 1]
                robot.x, robot.y = other.x, other.y
            else:
                raise LabError("fault must be offline, localization_lost, boundary, or collision")
            self._wake.set()
            return self._snapshot_locked()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> dict[str, Any]:
        now = time.time()
        max_error = max((math.hypot(r.target_x - r.x, r.target_y - r.y) for r in self._robots), default=0.0)
        minimum_distance = min(
            (math.hypot(a.x - b.x, a.y - b.y) for i, a in enumerate(self._robots) for b in self._robots[i + 1 :]),
            default=0.0,
        )
        return {
            "experiment_id": self._spec.experiment_id if self._spec else None,
            "state": self._state.value,
            "formation": self._spec.formation if self._spec else None,
            "spacing_m": self._spec.spacing_m if self._spec else None,
            "duration_s": self._spec.duration_s if self._spec else None,
            "control_mode": self._spec.control_mode if self._spec else None,
            "consensus_graph": self.topology.stability_report(),
            "elapsed_s": round(now - self._started_at, 3) if self._started_at else 0.0,
            "hold_elapsed_s": round(now - self._formed_at, 3) if self._formed_at else 0.0,
            "max_error_m": round(max_error, 4),
            "minimum_distance_m": round(minimum_distance, 4),
            "message": self._message,
            "error_code": self._error_code,
            "robots": [r.public() for r in self._robots],
        }

    @staticmethod
    def _targets(formation: str, spacing: float) -> list[tuple[float, float]]:
        offsets = formation_offsets(formation, spacing)
        return [offsets[robot_id] for robot_id in ROBOT_IDS]

    def _worker(self) -> None:
        while not self._shutdown:
            self._wake.wait(self.tick_s)
            self._wake.clear()
            now_mono = time.monotonic()
            with self._lock:
                dt = min(max(now_mono - self._last_update, 0.001), 0.2) * self.time_scale
                self._last_update = now_mono
                if self._state == ExperimentState.STOPPING:
                    for agent in self._agents.values():
                        agent.emergency_stop()
                    for robot in self._robots:
                        robot.vx = robot.vy = robot.wz = 0.0
                        robot.ax = robot.ay = robot.angular_accel = 0.0
                    self._state = ExperimentState.ABORTED
                    self._finished_at = time.time()
                    self._finalize_locked()
                elif self._state in (ExperimentState.FORMING, ExperimentState.HOLDING):
                    self._step_locked(dt)

    def _step_locked(self, dt: float) -> None:
        safety = self._safety_violation_locked()
        if safety:
            self._fail_locked(*safety)
            return
        if self._state == ExperimentState.FORMING:
            observations = {
                robot.robot_id: AgentObservation(
                    robot.robot_id,
                    robot.x,
                    robot.y,
                    robot.yaw_rad,
                    robot.online,
                    robot.localization_ok,
                    robot.vx,
                    robot.vy,
                    robot.wz,
                )
                for robot in self._robots
            }
            commands = {
                robot_id: agent.compute(observations[robot_id], (observation for peer_id, observation in observations.items() if peer_id != robot_id))
                for robot_id, agent in self._agents.items()
            }
            for robot in self._robots:
                command = commands[robot.robot_id]
                robot.agent_safe, robot.agent_reason = command.safe, command.reason
                robot.target_x, robot.target_y, robot.target_yaw_rad = command.target_x, command.target_y, command.target_yaw_rad
                if isinstance(command, SecondOrderCommand):
                    # Explicit Euler integration of the double-integrator model.
                    # The acceleration is the agent's local output; velocity and
                    # pose are state, not coordinator commands.
                    robot.ax, robot.ay, robot.angular_accel = command.accel_x, command.accel_y, command.angular_accel
                    robot.vx += robot.ax * dt
                    robot.vy += robot.ay * dt
                    speed = math.hypot(robot.vx, robot.vy)
                    if speed > self.max_speed_mps:
                        scale = self.max_speed_mps / speed
                        robot.vx, robot.vy = robot.vx * scale, robot.vy * scale
                    robot.wz += robot.angular_accel * dt
                    robot.wz = max(-1.5, min(1.5, robot.wz))
                    robot.x += robot.vx * dt
                    robot.y += robot.vy * dt
                    robot.yaw_rad += robot.wz * dt
                else:
                    robot.ax = robot.ay = robot.angular_accel = 0.0
                    dx, dy = robot.target_x - robot.x, robot.target_y - robot.y
                    distance = math.hypot(dx, dy)
                    robot.vx, robot.vy, robot.wz = command.world_vx, command.world_vy, command.wz
                    travel = math.hypot(robot.vx, robot.vy) * dt
                    if distance > 1e-9 and travel >= distance:
                        robot.x, robot.y = robot.target_x, robot.target_y
                    else:
                        robot.x += robot.vx * dt
                        robot.y += robot.vy * dt
                    robot.yaw_rad += robot.wz * dt
            max_error = max(math.hypot(r.target_x - r.x, r.target_y - r.y) for r in self._robots)
            max_speed = max((math.hypot(r.vx, r.vy) for r in self._robots), default=0.0)
            second_order = bool(self._spec and self._spec.control_mode == "second_order")
            if max_error <= self.position_tolerance_m and (not second_order or max_speed <= 0.05):
                for robot in self._robots:
                    robot.x, robot.y = robot.target_x, robot.target_y
                    robot.vx = robot.vy = robot.wz = 0.0
                    robot.ax = robot.ay = robot.angular_accel = 0.0
                    robot.yaw_rad = robot.target_yaw_rad
                self._state = ExperimentState.HOLDING
                self._formed_at = time.time()
                self._message = "formation reached; holding"
            elif self._started_at and time.time() - self._started_at > self.forming_timeout_s:
                self._fail_locked("forming_timeout", "formation did not converge in time")
                return
        elif self._formed_at and self._spec and time.time() - self._formed_at >= self._spec.duration_s / self.time_scale:
            self._state = ExperimentState.FINISHED
            self._finished_at = time.time()
            self._message = "experiment completed"
            self._finalize_locked()
        if time.monotonic() - self._last_telemetry >= 0.2:
            self._append_telemetry_locked()
            self._last_telemetry = time.monotonic()

    def _safety_violation_locked(self) -> tuple[str, str] | None:
        for robot in self._robots:
            if not robot.online:
                return "robot_offline", f"{robot.robot_id} is offline"
            if not robot.localization_ok:
                return "localization_lost", f"{robot.robot_id} localization is invalid"
            if abs(robot.x) > self.arena_half_extent_m or abs(robot.y) > self.arena_half_extent_m:
                return "boundary_violation", f"{robot.robot_id} left the safety area"
        for i, first in enumerate(self._robots):
            for second in self._robots[i + 1 :]:
                if math.hypot(first.x - second.x, first.y - second.y) < self.min_distance_m:
                    return "separation_violation", f"{first.robot_id} and {second.robot_id} are too close"
        return None

    def _fail_locked(self, code: str, message: str) -> None:
        for agent in self._agents.values():
            agent.emergency_stop()
        for robot in self._robots:
            robot.vx = robot.vy = robot.wz = 0.0
            robot.ax = robot.ay = robot.angular_accel = 0.0
            robot.agent_safe = False
            robot.agent_reason = code
        self._state = ExperimentState.FAILED
        self._error_code = code
        self._message = message
        self._finished_at = time.time()
        self._finalize_locked()

    def _append_telemetry_locked(self) -> None:
        if not self._trajectory_path or not self._started_at:
            return
        elapsed = time.time() - self._started_at
        with self._trajectory_path.open("a", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            for robot in self._robots:
                writer.writerow([round(elapsed, 4), self._state.value, robot.robot_id, robot.x, robot.y, robot.yaw_rad, robot.target_x, robot.target_y, robot.target_yaw_rad, robot.vx, robot.vy, robot.wz, robot.ax, robot.ay, robot.angular_accel, robot.agent_safe, robot.agent_reason])

    def _finalize_locked(self) -> None:
        self._append_telemetry_locked()
        if self._spec:
            run_dir = self.data_dir / self._spec.experiment_id
            (run_dir / "result.json").write_text(json.dumps(self._snapshot_locked(), ensure_ascii=False, indent=2), encoding="utf-8")

    def close(self) -> None:
        self._shutdown = True
        self._wake.set()
        self._thread.join(timeout=2)
