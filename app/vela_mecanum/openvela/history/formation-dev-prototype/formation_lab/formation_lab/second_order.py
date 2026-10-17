from __future__ import annotations

"""Distributed double-integrator formation controller.

Each robot runs this controller independently.  The coordinator still sends
only a formation mission; position and velocity feedback are computed locally
from the robot's own odometry and the configured graph neighbours.

For the pinned graph H = L + B, the nominal error dynamics are

    e_ddot + k_d H e_dot + k_p H e = 0.

The simulator and graph certificate use the same gains and therefore expose a
direct, inspectable correspondence between the implementation and the model.
"""

import math
from dataclasses import dataclass
from typing import Iterable

from .agent import (
    AgentObservation,
    CONTROL_MODES,
    FORMATIONS,
    FormationMission,
    ROBOT_IDS,
    RobotFormationAgent,
    formation_offsets,
)
from .laplacian import GraphTopology, default_topology


@dataclass(frozen=True)
class SecondOrderCommand:
    accel_x: float
    accel_y: float
    angular_accel: float
    target_x: float
    target_y: float
    target_yaw_rad: float
    safe: bool
    reason: str


class SecondOrderFormationAgent(RobotFormationAgent):
    """Pinned graph controller for holonomic double-integrator agents."""

    def __init__(
        self,
        robot_id: str,
        max_linear_mps: float = 0.65,
        max_angular_radps: float = 1.5,
        arena_half_extent_m: float = 3.0,
        min_distance_m: float = 0.25,
        topology: GraphTopology | None = None,
        position_gain: float = 0.9,
        velocity_gain: float = 1.4,
        max_accel_mps2: float = 1.2,
        max_angular_accel_radps2: float = 3.0,
    ):
        super().__init__(
            robot_id,
            max_linear_mps=max_linear_mps,
            max_angular_radps=max_angular_radps,
            arena_half_extent_m=arena_half_extent_m,
            min_distance_m=min_distance_m,
            control_mode="second_order",
            topology=topology or default_topology(),
        )
        if position_gain <= 0.0 or velocity_gain <= 0.0:
            raise ValueError("position_gain and velocity_gain must be positive")
        if max_accel_mps2 <= 0.0 or max_angular_accel_radps2 <= 0.0:
            raise ValueError("acceleration limits must be positive")
        self.position_gain = float(position_gain)
        self.velocity_gain = float(velocity_gain)
        self.max_accel_mps2 = float(max_accel_mps2)
        self.max_angular_accel_radps2 = float(max_angular_accel_radps2)

    def accept_mission(self, mission: FormationMission) -> None:
        if mission.control_mode != "second_order":
            raise ValueError("SecondOrderFormationAgent requires control_mode=second_order")
        super().accept_mission(mission)

    def _zero(self, target_x: float, target_y: float, target_yaw: float, reason: str) -> SecondOrderCommand:
        return SecondOrderCommand(0.0, 0.0, 0.0, target_x, target_y, target_yaw, False, reason)

    def compute(self, own: AgentObservation, peers: Iterable[AgentObservation]) -> SecondOrderCommand:
        tx, ty, target_yaw = self.target_pose()
        if self.estop_latched:
            return self._zero(tx, ty, target_yaw, "emergency_stop")
        if not self.mission:
            return self._zero(tx, ty, target_yaw, "no_mission")
        if self.mission.control_mode != "second_order":
            return self._zero(tx, ty, target_yaw, "control_mode_mismatch")
        if not own.online or not own.localization_ok:
            return self._zero(tx, ty, target_yaw, "local_state_invalid")
        if abs(own.x) > self.arena_half_extent_m or abs(own.y) > self.arena_half_extent_m:
            return self._zero(tx, ty, target_yaw, "local_boundary_violation")

        peer_map = {peer.robot_id: peer for peer in peers}
        required = list(self.topology.neighbors(self.robot_id))
        if any(
            robot_id not in peer_map
            or not peer_map[robot_id].online
            or not peer_map[robot_id].localization_ok
            for robot_id in required
        ):
            return self._zero(tx, ty, target_yaw, "peer_state_invalid")
        if any(
            math.hypot(peer_map[robot_id].x - own.x, peer_map[robot_id].y - own.y) < self.min_distance_m
            for robot_id in required
        ):
            return self._zero(tx, ty, target_yaw, "local_separation_violation")

        offsets = formation_offsets(self.mission.formation, self.mission.spacing_m)
        own_offset = offsets[self.robot_id]
        cosine, sine = math.cos(self.mission.heading_rad), math.sin(self.mission.heading_rad)
        # e_i - e_j = (p_i-p_j) - (p_i^*-p_j^*), and likewise for velocity.
        relative_position_error_x = 0.0
        relative_position_error_y = 0.0
        relative_velocity_error_x = 0.0
        relative_velocity_error_y = 0.0
        for peer_id, weight in self.topology.neighbors(self.robot_id).items():
            peer = peer_map[peer_id]
            raw_dx = own_offset[0] - offsets[peer_id][0]
            raw_dy = own_offset[1] - offsets[peer_id][1]
            desired_dx = cosine * raw_dx - sine * raw_dy
            desired_dy = sine * raw_dx + cosine * raw_dy
            relative_position_error_x += weight * ((own.x - peer.x) - desired_dx)
            relative_position_error_y += weight * ((own.y - peer.y) - desired_dy)
            relative_velocity_error_x += weight * (own.vx - peer.vx)
            relative_velocity_error_y += weight * (own.vy - peer.vy)

        pinning = self.topology.pinning_weight(self.robot_id)
        position_error_x = pinning * (own.x - tx) + relative_position_error_x
        position_error_y = pinning * (own.y - ty) + relative_position_error_y
        velocity_error_x = pinning * own.vx + relative_velocity_error_x
        velocity_error_y = pinning * own.vy + relative_velocity_error_y
        accel_x = -self.position_gain * position_error_x - self.velocity_gain * velocity_error_x
        accel_y = -self.position_gain * position_error_y - self.velocity_gain * velocity_error_y
        norm = math.hypot(accel_x, accel_y)
        if norm > self.max_accel_mps2:
            scale = self.max_accel_mps2 / norm
            accel_x, accel_y = accel_x * scale, accel_y * scale

        yaw_error = math.atan2(math.sin(target_yaw - own.yaw_rad), math.cos(target_yaw - own.yaw_rad))
        angular_accel = 2.0 * yaw_error - self.velocity_gain * own.wz
        angular_accel = max(-self.max_angular_accel_radps2, min(self.max_angular_accel_radps2, angular_accel))
        return SecondOrderCommand(accel_x, accel_y, angular_accel, tx, ty, target_yaw, True, "tracking")

