"""Pure command gating logic; no ROS or motor interface is imported here."""

from __future__ import annotations

import math


class CommandGate:
    def __init__(self, max_speed: float = 0.12, max_yaw: float = 0.30):
        self.max_speed = max_speed
        self.max_yaw = max_yaw
        self.lease_id = None
        self.lease_started = 0.0
        self.latched_reason = None
        self.last_command = None
        self.command_time = -math.inf
        self.status_time = -math.inf
        self.status_safe = False
        self.last_conflict = -math.inf
        self.active = False
        self.zero_until = -math.inf
        self.lease_needs_zero = False

    def command(self, values: tuple[float, float, float], now: float) -> None:
        if len(values) != 3 or not all(math.isfinite(v) for v in values):
            self.latched_reason = "invalid_command"
            return
        vx, vy, wz = values
        speed = math.hypot(vx, vy)
        if speed > self.max_speed:
            vx *= self.max_speed / speed
            vy *= self.max_speed / speed
        wz = max(-self.max_yaw, min(self.max_yaw, wz))
        self.last_command = (vx, vy, wz)
        self.command_time = now

    def status(self, safe: bool, reason: str, now: float) -> None:
        self.status_safe = bool(safe) and reason in ("tracking", "lidar_slow")
        self.status_time = now

    def conflict(self, now: float, reason: str = "competing_controller") -> None:
        self.last_conflict = now
        if self.lease_id is not None:
            self.latched_reason = reason

    def step(
        self,
        now: float,
        lease_id: str | None,
        hardware_enabled: bool,
        source_unique: bool,
    ) -> tuple[tuple[float, float, float] | None, str]:
        was_active = self.active
        if lease_id != self.lease_id:
            self.lease_id = lease_id
            self.lease_started = now
            self.latched_reason = None
            self.active = False
            self.lease_needs_zero = bool(lease_id)
        reason = None
        if not hardware_enabled:
            reason = "hardware_disabled"
        elif lease_id is None:
            reason = "disarmed"
        elif self.latched_reason:
            reason = self.latched_reason
        elif not source_unique:
            reason = "command_source_not_unique"
        elif now - self.last_conflict < 2.0:
            reason = "competing_controller"
        elif self.command_time < self.lease_started or now - self.command_time > 0.25:
            reason = "command_stale"
        elif self.status_time < self.lease_started or now - self.status_time > 0.25:
            reason = "agent_status_stale"
        elif not self.status_safe:
            reason = "agent_unsafe"
        if reason is None:
            self.active = True
            return self.last_command, "forwarding"
        if was_active or self.lease_needs_zero:
            self.zero_until = max(self.zero_until, now + 0.5)
            self.lease_needs_zero = False
        self.active = False
        if now <= self.zero_until and hardware_enabled:
            return (0.0, 0.0, 0.0), reason
        return None, reason
