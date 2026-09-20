from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

from .laplacian import DEFAULT_ROBOT_IDS, GraphTopology, default_topology


# Single source of truth, defined next to the graph utilities so the default
# ring topology and the agent's slot ordering can never drift apart.
ROBOT_IDS = DEFAULT_ROBOT_IDS
FORMATIONS = ("square", "line", "circle", "diamond")
CONTROL_MODES = ("anchored", "laplacian", "second_order")


def arena_bounds_from_config(limits: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return configured map-frame bounds as (min_x, max_x, min_y, max_y)."""
    configured = limits.get("arena_bounds_m")
    if configured is None:
        half = float(limits.get("arena_half_extent_m", 3.0))
        bounds = (-half, half, -half, half)
    else:
        bounds = tuple(float(configured[key]) for key in ("min_x", "max_x", "min_y", "max_y"))
    if (
        len(bounds) != 4
        or not all(math.isfinite(value) for value in bounds)
        or bounds[0] >= bounds[1]
        or bounds[2] >= bounds[3]
    ):
        raise ValueError("invalid arena bounds")
    return bounds


def point_in_arena(x: float, y: float, bounds: tuple[float, float, float, float]) -> bool:
    return math.isfinite(x) and math.isfinite(y) and bounds[0] <= x <= bounds[1] and bounds[2] <= y <= bounds[3]


@dataclass(frozen=True)
class FormationMission:
    experiment_id: str
    formation: str
    spacing_m: float
    center_x: float = 0.0
    center_y: float = 0.0
    heading_rad: float = 0.0
    control_mode: str = "anchored"


@dataclass(frozen=True)
class AgentObservation:
    robot_id: str
    x: float
    y: float
    yaw_rad: float = 0.0
    online: bool = True
    localization_ok: bool = True
    # World-frame velocity is optional so existing callers that only provide
    # pose data remain source-compatible.  The second-order controller uses
    # these terms for velocity damping.
    vx: float = 0.0
    vy: float = 0.0
    wz: float = 0.0


@dataclass(frozen=True)
class AgentCommand:
    world_vx: float
    world_vy: float
    wz: float
    target_x: float
    target_y: float
    target_yaw_rad: float
    safe: bool
    reason: str


def formation_offsets(formation: str, spacing: float) -> dict[str, tuple[float, float]]:
    half = spacing / 2.0
    if formation == "square":
        values = [(-half, -half), (-half, half), (half, half), (half, -half)]
    elif formation == "line":
        values = [(-1.5 * spacing, 0.0), (-0.5 * spacing, 0.0), (0.5 * spacing, 0.0), (1.5 * spacing, 0.0)]
    elif formation == "circle":
        radius = spacing / math.sqrt(2.0)
        values = [(-radius, 0.0), (0.0, radius), (radius, 0.0), (0.0, -radius)]
    elif formation == "diamond":
        radius = spacing / math.sqrt(2.0)
        values = [(0.0, -radius), (-radius, 0.0), (0.0, radius), (radius, 0.0)]
    else:
        raise ValueError(f"unsupported formation: {formation}")
    return dict(zip(ROBOT_IDS, values))


class RobotFormationAgent:
    """Controller intended to run independently on one MentorPi.

    The coordinator supplies only a mission. Each instance combines its own
    absolute slot error with relative formation errors observed from peers and
    produces a holonomic velocity command for its own chassis.
    """

    def __init__(
        self,
        robot_id: str,
        max_linear_mps: float = 0.875,
        max_angular_radps: float = 1.5,
        arena_half_extent_m: float = 3.0,
        min_distance_m: float = 0.25,
        control_mode: str = "anchored",
        topology: GraphTopology | None = None,
        laplacian_gain: float = 0.55,
        pinning_gain: float = 0.9,
        arena_bounds_m: tuple[float, float, float, float] | None = None,
    ):
        if robot_id not in ROBOT_IDS:
            raise ValueError(f"unknown robot id: {robot_id}")
        self.robot_id = robot_id
        self.max_linear_mps = max_linear_mps
        self.max_angular_radps = max_angular_radps
        self.arena_half_extent_m = arena_half_extent_m
        self.arena_bounds_m = arena_bounds_m or arena_bounds_from_config({"arena_half_extent_m": arena_half_extent_m})
        self.min_distance_m = min_distance_m
        if control_mode not in CONTROL_MODES:
            raise ValueError(f"unsupported control mode: {control_mode}")
        self.control_mode = control_mode
        self.topology = topology or default_topology()
        self.laplacian_gain = float(laplacian_gain)
        self.pinning_gain = float(pinning_gain)
        self.mission: FormationMission | None = None
        self.estop_latched = False

    def accept_mission(self, mission: FormationMission) -> None:
        if mission.formation not in FORMATIONS:
            raise ValueError(f"unsupported formation: {mission.formation}")
        if mission.control_mode not in CONTROL_MODES:
            raise ValueError(f"unsupported control mode: {mission.control_mode}")
        self.mission = mission
        self.estop_latched = False

    def emergency_stop(self) -> None:
        self.estop_latched = True

    def clear(self) -> None:
        self.mission = None
        self.estop_latched = False

    def target_pose(self) -> tuple[float, float, float]:
        if not self.mission:
            return 0.0, 0.0, 0.0
        offsets = formation_offsets(self.mission.formation, self.mission.spacing_m)
        ox, oy = offsets[self.robot_id]
        cosine, sine = math.cos(self.mission.heading_rad), math.sin(self.mission.heading_rad)
        return (
            self.mission.center_x + cosine * ox - sine * oy,
            self.mission.center_y + sine * ox + cosine * oy,
            self.mission.heading_rad,
        )

    def compute(self, own: AgentObservation, peers: Iterable[AgentObservation]) -> AgentCommand:
        tx, ty, target_yaw = self.target_pose()
        if self.estop_latched:
            return AgentCommand(0.0, 0.0, 0.0, tx, ty, target_yaw, False, "emergency_stop")
        if not self.mission:
            return AgentCommand(0.0, 0.0, 0.0, tx, ty, target_yaw, False, "no_mission")
        if self.mission.control_mode == "second_order":
            return AgentCommand(0.0, 0.0, 0.0, tx, ty, target_yaw, False, "second_order_requires_second_order_agent")
        if not own.online or not own.localization_ok:
            return AgentCommand(0.0, 0.0, 0.0, tx, ty, target_yaw, False, "local_state_invalid")
        if not point_in_arena(own.x, own.y, self.arena_bounds_m):
            return AgentCommand(0.0, 0.0, 0.0, tx, ty, target_yaw, False, "local_boundary_violation")

        peer_map = {peer.robot_id: peer for peer in peers}
        if self.mission.control_mode == "laplacian":
            # The standard graph mode only consumes the configured neighbors.
            required = list(self.topology.neighbors(self.robot_id))
        else:
            required = [robot_id for robot_id in ROBOT_IDS if robot_id != self.robot_id]
        if any(robot_id not in peer_map or not peer_map[robot_id].online or not peer_map[robot_id].localization_ok for robot_id in required):
            return AgentCommand(0.0, 0.0, 0.0, tx, ty, target_yaw, False, "peer_state_invalid")
        if any(math.hypot(peer_map[robot_id].x - own.x, peer_map[robot_id].y - own.y) < self.min_distance_m for robot_id in required):
            return AgentCommand(0.0, 0.0, 0.0, tx, ty, target_yaw, False, "local_separation_violation")

        offsets = formation_offsets(self.mission.formation, self.mission.spacing_m)
        own_offset = offsets[self.robot_id]
        cosine, sine = math.cos(self.mission.heading_rad), math.sin(self.mission.heading_rad)
        relative_error_x = 0.0
        relative_error_y = 0.0
        weights = self.topology.neighbors(self.robot_id) if self.mission.control_mode == "laplacian" else {peer_id: 1.0 for peer_id in required}
        for peer_id in required:
            peer = peer_map[peer_id]
            raw_dx = offsets[peer_id][0] - own_offset[0]
            raw_dy = offsets[peer_id][1] - own_offset[1]
            desired_dx = cosine * raw_dx - sine * raw_dy
            desired_dy = sine * raw_dx + cosine * raw_dy
            relative_error_x += weights[peer_id] * ((peer.x - own.x) - desired_dx)
            relative_error_y += weights[peer_id] * ((peer.y - own.y) - desired_dy)

        if self.mission.control_mode == "laplacian":
            # Standard displacement-consensus with virtual-leader pinning:
            # e_dot = -(k L + k_a B)e for the nominal single-integrator model.
            pinning = self.topology.pinning_weight(self.robot_id)
            vx = self.pinning_gain * pinning * (tx - own.x) + self.laplacian_gain * relative_error_x
            vy = self.pinning_gain * pinning * (ty - own.y) + self.laplacian_gain * relative_error_y
        else:
            # Every car owns this calculation. Absolute anchoring prevents
            # group drift; the consensus term maintains peer-to-peer geometry.
            relative_error_x /= len(required)
            relative_error_y /= len(required)
            vx = 0.9 * (tx - own.x) + 0.55 * relative_error_x
            vy = 0.9 * (ty - own.y) + 0.55 * relative_error_y
        norm = math.hypot(vx, vy)
        if norm > self.max_linear_mps:
            scale = self.max_linear_mps / norm
            vx, vy = vx * scale, vy * scale
        yaw_error = math.atan2(math.sin(target_yaw - own.yaw_rad), math.cos(target_yaw - own.yaw_rad))
        wz = max(-self.max_angular_radps, min(self.max_angular_radps, yaw_error * 2.0))
        return AgentCommand(vx, vy, wz, tx, ty, target_yaw, True, "tracking")
