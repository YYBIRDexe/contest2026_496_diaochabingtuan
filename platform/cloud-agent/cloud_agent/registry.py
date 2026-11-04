"""Local route and fleet registries.

These files are intentionally *registries*, not live telemetry.  Every result
therefore carries its source and ``is_live: false``.  No code in this module
invents a position, a battery level or an online state.
"""

import hashlib
import json
from pathlib import Path

from . import SERVICE_NAME, __version__
from .errors import RegistryError
from .util import isoformat, new_id, utc_now


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _error(code, message, details=None, clarification=None):
    payload = {
        "ok": False,
        "error": {"code": code, "message": message},
        "clarification_required": clarification is not None,
    }
    if details:
        payload["error"]["details"] = details
    if clarification:
        payload["clarification"] = clarification
    return payload


class Registry(object):
    def __init__(self, data_dir, now_fn=None):
        self.data_dir = Path(data_dir)
        self.routes_path = self.data_dir / "routes.json"
        self.fleet_path = self.data_dir / "fleet.json"
        self._now = now_fn or utc_now
        self.loaded_at = isoformat(self._now())
        self.routes = []
        self.robots = []
        self.routes_source = "local_registry"
        self.fleet_source = "local_registry"
        self.routes_sha256 = ""
        self.fleet_sha256 = ""
        self.registry_name = ""
        self.fleet_name = ""
        self._load()

    def _load(self):
        routes_doc = self._read_json(self.routes_path)
        fleet_doc = self._read_json(self.fleet_path)
        self.routes_sha256 = _sha256_file(self.routes_path)
        self.fleet_sha256 = _sha256_file(self.fleet_path)
        self.routes_source = str(routes_doc.get("source") or "local_registry")
        self.fleet_source = str(fleet_doc.get("source") or "local_registry")
        self.registry_name = str(routes_doc.get("registry_name") or "route_registry")
        self.fleet_name = str(fleet_doc.get("registry_name") or "fleet_registry")

        seen = set()
        for index, route in enumerate(routes_doc.get("routes") or []):
            if not isinstance(route, dict):
                raise RegistryError("routes.json 第 %d 项不是对象" % index)
            route_id = str(route.get("id") or "").strip()
            if not route_id or route_id in seen:
                raise RegistryError("routes.json 路线 id 缺失或重复: %r" % route_id)
            seen.add(route_id)
            checks = []
            check_ids = set()
            for raw_check in route.get("checks") or []:
                check_id = str(raw_check.get("id") or "").strip()
                label = str(raw_check.get("label") or "").strip()
                if not check_id or not label or check_id in check_ids:
                    raise RegistryError("路线 %s 的检查项 id/label 缺失或重复" % route_id)
                check_ids.add(check_id)
                checks.append({"id": check_id, "label": label})
            if not checks:
                raise RegistryError("路线 %s 没有任何检查项" % route_id)
            checkpoints = [str(item) for item in (route.get("checkpoints") or []) if str(item).strip()]
            if not checkpoints:
                raise RegistryError("路线 %s 没有检查点" % route_id)
            self.routes.append(
                {
                    "id": route_id,
                    "name": str(route.get("name") or route_id),
                    "zone": str(route.get("zone") or ""),
                    "enabled": bool(route.get("enabled", True)),
                    "checkpoints": checkpoints,
                    "checks": checks,
                }
            )

        robot_ids = set()
        for index, robot in enumerate(fleet_doc.get("robots") or []):
            if not isinstance(robot, dict):
                raise RegistryError("fleet.json 第 %d 项不是对象" % index)
            robot_id = str(robot.get("id") or "").strip()
            if not robot_id or robot_id in robot_ids:
                raise RegistryError("fleet.json 车辆 id 缺失或重复: %r" % robot_id)
            robot_ids.add(robot_id)
            capabilities = [str(item) for item in (robot.get("capabilities") or []) if str(item).strip()]
            self.robots.append(
                {
                    "id": robot_id,
                    "name": str(robot.get("name") or robot_id),
                    "model": str(robot.get("model") or ""),
                    "enabled": bool(robot.get("enabled", True)),
                    "status": str(robot.get("status") or "registered"),
                    "telemetry": str(robot.get("telemetry") or "not_connected"),
                    "last_seen": robot.get("last_seen"),
                    "capabilities": capabilities,
                }
            )

    @staticmethod
    def _read_json(path):
        try:
            with open(str(path), "r", encoding="utf-8-sig") as handle:
                value = json.load(handle)
        except OSError as exc:
            raise RegistryError("无法读取注册表 %s: %s" % (path, exc.strerror or exc))
        except ValueError as exc:
            raise RegistryError("注册表 %s 不是合法 JSON: %s" % (path, exc))
        if not isinstance(value, dict):
            raise RegistryError("注册表 %s 顶层必须是对象" % path)
        return value

    def get_route(self, route_id):
        for route in self.routes:
            if route["id"] == route_id:
                return route
        return None

    def get_robot(self, robot_id):
        for robot in self.robots:
            if robot["id"] == robot_id:
                return robot
        return None

    def route_index(self):
        return [
            {
                "id": route["id"],
                "name": route["name"],
                "zone": route["zone"],
                "enabled": route["enabled"],
                "checkpoints": list(route["checkpoints"]),
                "checks": [dict(item) for item in route["checks"]],
            }
            for route in self.routes
        ]

    def public_routes(self):
        return {
            "ok": True,
            "source": self.routes_source,
            "registry_name": self.registry_name,
            "registry_sha256": self.routes_sha256,
            "loaded_at": self.loaded_at,
            "calibration": self.calibration_status()["routes"],
            "routes": self.route_index(),
        }

    def calibration_status(self):
        """Make the absence of verified field data explicit to tools and UI."""
        route_count = len(self.routes)
        robot_count = len(self.robots)
        return {
            "routes": {
                "registered": route_count,
                "status": "uncalibrated" if route_count == 0 else "local_registry_only",
                "message": (
                    "尚无已核验的标定路线。需要维护者完成现场标定并登记后才能生成计划。"
                    if route_count == 0
                    else "路线来自本地注册表；是否已现场标定仍需维护者确认。"
                ),
            },
            "fleet": {
                "registered": robot_count,
                "status": "unregistered" if robot_count == 0 else "local_registry_only",
                "message": (
                    "尚无已核验的登记车辆。需要维护者核对车辆型号、能力和使用状态后登记。"
                    if robot_count == 0
                    else "车辆来自本地登记表；未连接实时遥测，能力与状态仍需维护者确认。"
                ),
            },
        }

    def fleet_snapshot(self):
        robots = [
            {
                "id": robot["id"],
                "name": robot["name"],
                "model": robot["model"],
                "enabled": robot["enabled"],
                "status": robot["status"],
                "telemetry": robot["telemetry"],
                "last_seen": robot["last_seen"],
                "capabilities": list(robot["capabilities"]),
            }
            for robot in self.robots
        ]
        return {
            "ok": True,
            "snapshot": {
                "captured_at": isoformat(self._now()),
                "source": self.fleet_source,
                "registry_name": self.fleet_name,
                "registry_sha256": self.fleet_sha256,
                "is_live": False,
                "telemetry": "not_connected",
                "calibration": self.calibration_status()["fleet"],
                "counts": {
                    "total": len(robots),
                    "enabled": sum(1 for item in robots if item["enabled"]),
                    "disabled": sum(1 for item in robots if not item["enabled"]),
                },
                "robots": robots,
                "disclaimer": (
                    "这是本地登记表，不是在线遥测。车辆位置、电量、在线状态和健康状态均未读取；"
                    "不要据此称车辆在线或可执行。"
                ),
            },
        }

    def capabilities(self, tool_names=None, limits=None, llm_configured=False):
        return {
            "ok": True,
            "capabilities": {
                "service": SERVICE_NAME,
                "version": __version__,
                "llm_configured": bool(llm_configured),
                "tools": list(tool_names or []),
                "execution": {
                    "available": False,
                    "executor": "none_v1",
                    "reason": "首版未接入运动执行器。计划可以被确认，但确认不会下发车辆，也不代表已执行。",
                },
                "calibration": self.calibration_status(),
                "routes": self.route_index(),
                "fleet": {
                    "source": self.fleet_source,
                    "registry_sha256": self.fleet_sha256,
                    "is_live": False,
                    "telemetry": "not_connected",
                    "robots": [
                        {
                            "id": robot["id"],
                            "name": robot["name"],
                            "enabled": robot["enabled"],
                            "status": robot["status"],
                            "telemetry": robot["telemetry"],
                            "capabilities": list(robot["capabilities"]),
                        }
                        for robot in self.robots
                    ],
                },
                "check_catalog": self._check_catalog(),
                "limits": dict(limits or {}),
                "data_sources": {
                    "routes": {
                        "source": self.routes_source,
                        "sha256": self.routes_sha256,
                        "is_live": False,
                    },
                    "fleet": {
                        "source": self.fleet_source,
                        "sha256": self.fleet_sha256,
                        "is_live": False,
                    },
                },
                "registry_loaded_at": self.loaded_at,
            },
        }

    def _check_catalog(self):
        catalog = {}
        for route in self.routes:
            for check in route["checks"]:
                catalog.setdefault(check["id"], check["label"])
        return [{"id": key, "label": catalog[key]} for key in sorted(catalog)]

    def _route_choices(self):
        return [
            {"id": route["id"], "name": route["name"], "enabled": route["enabled"]}
            for route in self.routes
        ]

    def _unknown_route(self, route_id):
        known = "；".join(
            "%s（%s%s）"
            % (route["name"], route["id"], "" if route["enabled"] else "，当前停用")
            for route in self.routes
        )
        if known:
            clarification = (
                "没有找到路线 %r。我不会猜测路线。请确认是以下哪条已登记路线：%s"
                % (route_id, known)
            )
        else:
            clarification = (
                "没有找到路线 %r。当前没有已核验的标定路线，我不会猜测；"
                "需要维护者完成现场标定并登记后才能生成计划。" % route_id
            )
        return _error(
            "unknown_route",
            "路线 %r 未登记，不能生成计划。" % route_id,
            details={"route_id": route_id, "known_routes": self._route_choices()},
            clarification=clarification,
        )

    def validate_mission(self, payload):
        """Validate a mission request against the local registry.

        The returned object is also the tool result, so failures remain
        machine-readable and never create a proposal.
        """
        if not isinstance(payload, dict):
            return _error("invalid_mission", "任务参数必须是对象。")

        route_id = payload.get("route_id")
        if not isinstance(route_id, str) or not route_id.strip():
            return _error("invalid_route_id", "route_id 必须是非空字符串。")
        route_id = route_id.strip()
        route = self.get_route(route_id)
        if route is None:
            return self._unknown_route(route_id)
        if not route["enabled"]:
            return _error(
                "route_disabled",
                "路线 %s 当前已停用，不能生成计划。" % route["name"],
                details={"route_id": route_id, "route": {"id": route_id, "name": route["name"]}},
            )

        raw_checks = payload.get("checks")
        if not isinstance(raw_checks, list) or not raw_checks:
            return _error(
                "invalid_checks",
                "checks 必须是至少包含一个检查项的数组。",
                details={"route_id": route_id, "allowed_checks": route["checks"]},
            )
        selected = []
        unknown_checks = []
        seen_checks = set()
        for item in raw_checks:
            if not isinstance(item, str) or not item.strip():
                unknown_checks.append(repr(item))
                continue
            check_id = item.strip()
            if check_id in seen_checks:
                continue
            seen_checks.add(check_id)
            match = next((check for check in route["checks"] if check["id"] == check_id), None)
            if match is None:
                unknown_checks.append(check_id)
            else:
                selected.append(dict(match))
        if unknown_checks:
            return _error(
                "unknown_check",
                "路线 %s 不包含检查项：%s。未执行任何计划创建。"
                % (route["name"], ", ".join(unknown_checks)),
                details={
                    "route_id": route_id,
                    "unknown_checks": unknown_checks,
                    "allowed_checks": route["checks"],
                },
                clarification="请确认检查项；这条路线只登记了：%s。"
                % "、".join("%s（%s）" % (item["label"], item["id"]) for item in route["checks"]),
            )
        if not selected:
            return _error("invalid_checks", "没有可用的检查项。")

        robot_id = payload.get("robot_id")
        robot = None
        if robot_id is not None:
            if not isinstance(robot_id, str) or not robot_id.strip():
                return _error("invalid_robot_id", "robot_id 必须是非空字符串或不提供。")
            robot_id = robot_id.strip()
            robot = self.get_robot(robot_id)
            if robot is None:
                return _error(
                    "unknown_robot",
                    "车辆 %r 未登记。" % robot_id,
                    details={
                        "robot_id": robot_id,
                        "known_robots": [{"id": item["id"], "name": item["name"]} for item in self.robots],
                    },
                    clarification="没有找到车辆 %r。请确认车辆编号，或先不指定车辆。" % robot_id,
                )
            if not robot["enabled"]:
                return _error(
                    "robot_unavailable",
                    "车辆 %s 当前处于停用/维护状态，不能指定为执行车辆。" % robot["name"],
                    details={"robot_id": robot_id, "status": robot["status"]},
                )
            required_capabilities = ("inspection", "navigation")
            missing_capabilities = [
                capability
                for capability in required_capabilities
                if capability not in robot["capabilities"]
            ]
            if missing_capabilities:
                return _error(
                    "robot_capability_missing",
                    "车辆 %s 缺少执行巡检路线所需能力：%s。"
                    % (robot["name"], ", ".join(missing_capabilities)),
                    details={
                        "robot_id": robot_id,
                        "capabilities": robot["capabilities"],
                        "missing_capabilities": missing_capabilities,
                    },
                )

        scheduled_for = payload.get("scheduled_for")
        scheduled_iso = None
        if scheduled_for is not None:
            from .util import parse_iso8601

            if not isinstance(scheduled_for, str) or not scheduled_for.strip():
                return _error("invalid_scheduled_for", "scheduled_for 必须是带时区的 ISO-8601 字符串。")
            try:
                scheduled_dt = parse_iso8601(scheduled_for)
            except ValueError as exc:
                return _error("invalid_scheduled_for", "scheduled_for 不合法：%s" % exc)
            now = self._now()
            if scheduled_dt < now:
                return _error(
                    "scheduled_in_past",
                    "scheduled_for 早于当前服务时间，不能生成计划。",
                    details={"scheduled_for": isoformat(scheduled_dt), "now": isoformat(now)},
                )
            scheduled_iso = isoformat(scheduled_dt)

        warnings = [
            {
                "code": "planning_only",
                "message": "本结果只完成计划校验；没有探测车辆状态，也不代表车辆可执行。",
            }
        ]
        if robot is None:
            warnings.append(
                {
                    "code": "robot_not_assigned",
                    "message": "未指定车辆。计划确认后仍需人工分配车辆并做执行前检查。",
                }
            )
        else:
            warnings.append(
                {
                    "code": "telemetry_not_connected",
                    "message": "车辆 %s 的在线/位置/电量未读取；本地注册表不能证明车辆可用。" % robot["name"],
                }
            )

        return {
            "ok": True,
            "clarification_required": False,
            "validation_id": new_id("val"),
            "validated_at": isoformat(self._now()),
            "route": {
                "id": route["id"],
                "name": route["name"],
                "zone": route["zone"],
                "checkpoints": list(route["checkpoints"]),
            },
            "robot": (
                {
                    "id": robot["id"],
                    "name": robot["name"],
                    "status": robot["status"],
                    "telemetry": robot["telemetry"],
                }
                if robot
                else None
            ),
            "checks": selected,
            "scheduled_for": scheduled_iso,
            "warnings": warnings,
            "registry": {
                "routes_source": self.routes_source,
                "routes_sha256": self.routes_sha256,
                "fleet_source": self.fleet_source,
                "fleet_sha256": self.fleet_sha256,
                "is_live": False,
            },
        }
