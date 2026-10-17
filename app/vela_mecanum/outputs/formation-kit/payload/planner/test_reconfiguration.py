"""Offline regression checks using the saved four-car row and map."""

import math
from pathlib import Path
import tempfile
import unittest

from formation_planner import FormationPlanner, MIN_SEPARATION_M, OccupancyGrid, PlanningError, Pose, Request, ROBOT_IDS
from formation_lap import build_lap_plan
from reconfiguration_agent import _advance_trajectory, _body_velocity, _route_velocity, _scan_path_clear
from reconfiguration_session import ReconfigurationSession, Telemetry
from synchronized_formation import FormationTranslateSession, SquareTurnSession, SynchronizedFormationSession, TranslateThenLineSession, build_synchronized_plan


ROOT = Path(__file__).resolve().parents[1]
ROW = {
    "robot1": Pose(-2.529, -0.771, -0.076),
    "robot2": Pose(-2.544, 0.021, -0.108),
    "robot3": Pose(-2.556, -0.496, -0.094),
    "robot4": Pose(-2.550, -0.213, -0.094),
}

FIELD_POSES_2026_09_18 = {
    "robot1": Pose(-0.27, 0.93, 0.037),
    "robot2": Pose(-0.28, 0.28, -0.037),
    "robot3": Pose(-0.36, -0.81, 0.042),
    "robot4": Pose(-0.24, -0.40, 0.116),
}


def planner():
    grid = OccupancyGrid(ROOT / "evidence" / "classroom.pgm", 0.05, (-10.2, -5.04))
    return FormationPlanner(map_grid=grid)


def readings(poses, now, offline=None):
    return {robot: Telemetry(pose, now, robot != offline) for robot, pose in poses.items()}


class OfflineReconfigurationTests(unittest.TestCase):
    def test_local_trajectory_helpers_keep_route_continuous(self):
        route = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0))
        index, dx, dy, distance, complete = _advance_trajectory(route, 0, 0.1, 0.0)
        self.assertEqual(index, 1)
        self.assertAlmostEqual(dx, 0.9)
        self.assertAlmostEqual(dy, 0.0)
        self.assertAlmostEqual(distance, 0.9)
        self.assertFalse(complete)
        index, dx, dy, distance, complete = _advance_trajectory(route, index, 1.0, 0.1)
        self.assertEqual(index, 2)
        self.assertAlmostEqual(dx, 0.0)
        self.assertAlmostEqual(dy, 0.9)
        self.assertAlmostEqual(distance, 0.9)
        self.assertFalse(complete)
        index, dx, dy, distance, complete = _advance_trajectory(route, index, 1.0, 1.0)
        self.assertEqual((index, dx, dy, distance), (2, 0.0, 0.0, 0.0))
        self.assertTrue(complete)
        self.assertAlmostEqual(_body_velocity(math.pi / 2, 1.0, 0.0)[1], -1.0)
        world_vx, world_vy = _route_velocity(1.0, 0.0, 1.0, 0.875)
        self.assertAlmostEqual(world_vx, 0.875)
        self.assertAlmostEqual(world_vy, 0.0)

        scan = {"ranges": (1.0, 1.0, 1.0, 1.0, 1.0), "angle_min": -0.2, "angle_increment": 0.1}
        self.assertTrue(_scan_path_clear(scan, 0.0))
        scan["ranges"] = (1.0, 1.0, 0.28, 1.0, 1.0)
        self.assertTrue(_scan_path_clear(scan, 0.0))
        scan["ranges"] = (1.0, 1.0, 0.2, 1.0, 1.0)
        self.assertFalse(_scan_path_clear(scan, 0.0))

    def test_four_formations_and_auto_assignment(self):
        engine = planner()
        for shape in ("square", "line", "circle", "diamond", "triangle"):
            with self.subTest(shape=shape):
                plan = engine.plan(ROW, Request(shape, 0.5))
                engine.verify(ROW, plan)
                self.assertEqual(set(plan.targets), set(ROW))
                self.assertEqual(set(plan.slots.values()), set(range(4)))
                self.assertGreaterEqual(plan.final_separation_m, MIN_SEPARATION_M)
                self.assertTrue(any(step.purpose == "separate" for step in plan.steps))

    def test_field_square_plan_uses_a_fully_verified_candidate(self):
        engine = planner()
        plan = engine.plan(FIELD_POSES_2026_09_18, Request("square", 0.5))
        engine.verify(FIELD_POSES_2026_09_18, plan)

    def test_field_square_synchronized_plan_has_safe_sampled_gap(self):
        engine = planner()
        plan = build_synchronized_plan(engine, FIELD_POSES_2026_09_18, Request("square", 0.5))
        self.assertGreaterEqual(plan.final_separation_m, engine.separation)
        self.assertEqual(set(plan.routes), set(ROW))

    def test_synchronized_session_emits_four_commands(self):
        engine = planner()
        session = SynchronizedFormationSession(engine, Request("square", 0.5))
        initial = readings(FIELD_POSES_2026_09_18, 0.0)
        self.assertTrue(session.tick(0.0, initial).stop_all)
        decision = session.tick(2.1, readings(FIELD_POSES_2026_09_18, 2.1))
        self.assertEqual(decision.state, "RUNNING")
        self.assertFalse(decision.stop_all)
        self.assertEqual(set(decision.commands), set(ROW))

    def test_translate_then_line_keeps_geometry_through_pause(self):
        poses = {
            "robot1": Pose(-0.25, -0.25, 0.0),
            "robot2": Pose(-0.25, 0.25, 0.0),
            "robot3": Pose(0.25, 0.25, 0.0),
            "robot4": Pose(0.25, -0.25, 0.0),
        }
        session = TranslateThenLineSession(FormationPlanner(), 0.5, stable_reconnect_s=0.0)
        running = session.tick(0.0, readings(poses, 0.0))
        self.assertEqual(running.state, "RUNNING")
        self.assertEqual(set(running.commands), set(ROBOT_IDS))
        self.assertEqual(set(running.velocities), set(ROBOT_IDS))
        geometry = session.geometry
        paused = session.tick(0.1, readings(poses, 0.1, offline="robot2"))
        self.assertEqual(paused.state, "PAUSED")
        self.assertTrue(paused.stop_all)
        resumed = session.tick(0.2, readings(poses, 0.2))
        self.assertEqual(resumed.state, "RUNNING")
        self.assertIs(session.geometry, geometry)
        self.assertEqual(session.geometry.slots, {robot: index for index, robot in enumerate(ROBOT_IDS)})

    def test_formation_translate_preserves_existing_offsets(self):
        poses = {
            "robot1": Pose(-0.30, -0.20, 0.0),
            "robot2": Pose(-0.20, 0.30, 0.0),
            "robot3": Pose(0.35, 0.25, 0.0),
            "robot4": Pose(0.25, -0.25, 0.0),
        }
        initial_offsets = {
            robot: (
                poses[robot].x - sum(item.x for item in poses.values()) / len(poses),
                poses[robot].y - sum(item.y for item in poses.values()) / len(poses),
            )
            for robot in ROBOT_IDS
        }
        session = FormationTranslateSession(
            FormationPlanner(), 0.6, cruise_speed_mps=0.15, stable_reconnect_s=0.0,
        )
        minimum_gap = float("inf")
        for step in range(1000):
            now = step * 0.05
            decision = session.tick(now, readings(poses, now))
            if decision.state == "COMPLETE":
                break
            self.assertEqual(decision.state, "RUNNING")
            self.assertEqual(set(decision.velocities), set(ROBOT_IDS))
            self.assertEqual(set(decision.headings), set(ROBOT_IDS))
            poses = {
                robot: Pose(
                    poses[robot].x + decision.velocities[robot][0] * 0.05,
                    poses[robot].y + decision.velocities[robot][1] * 0.05,
                    poses[robot].yaw + max(
                        -0.06,
                        min(0.06, (decision.headings[robot] - poses[robot].yaw + math.pi) % (2 * math.pi) - math.pi),
                    ),
                )
                for robot in ROBOT_IDS
            }
            minimum_gap = min(
                minimum_gap,
                *(math.hypot(poses[first].x - poses[second].x, poses[first].y - poses[second].y)
                  for index, first in enumerate(ROBOT_IDS) for second in ROBOT_IDS[index + 1:]),
            )
        self.assertEqual(session.state, "COMPLETE")
        self.assertGreaterEqual(minimum_gap, MIN_SEPARATION_M - 1e-6)
        final_center = (
            sum(poses[robot].x for robot in ROBOT_IDS) / len(ROBOT_IDS),
            sum(poses[robot].y for robot in ROBOT_IDS) / len(ROBOT_IDS),
        )
        for robot in ROBOT_IDS:
            self.assertAlmostEqual(poses[robot].x - final_center[0], initial_offsets[robot][0], delta=0.05)
            self.assertAlmostEqual(poses[robot].y - final_center[1], initial_offsets[robot][1], delta=0.05)

    def test_translate_then_line_completes_with_four_car_commands(self):
        poses = {
            "robot1": Pose(-0.25, -0.25, 0.0),
            "robot2": Pose(-0.25, 0.25, 0.0),
            "robot3": Pose(0.25, 0.25, 0.0),
            "robot4": Pose(0.25, -0.25, 0.0),
        }
        session = TranslateThenLineSession(FormationPlanner(), 0.5, stable_reconnect_s=0.0)
        minimum_gap = float("inf")
        for step in range(1200):
            now = step * 0.05
            decision = session.tick(now, readings(poses, now))
            if decision.state == "COMPLETE":
                break
            self.assertEqual(decision.state, "RUNNING")
            self.assertEqual(set(decision.commands), set(ROBOT_IDS))
            self.assertEqual(set(decision.velocities), set(ROBOT_IDS))
            poses = {
                robot: Pose(
                    poses[robot].x + decision.velocities[robot][0] * 0.05,
                    poses[robot].y + decision.velocities[robot][1] * 0.05,
                    poses[robot].yaw,
                )
                for robot in ROBOT_IDS
            }
            minimum_gap = min(
                minimum_gap,
                *(math.hypot(poses[first].x - poses[second].x, poses[first].y - poses[second].y)
                  for index, first in enumerate(ROBOT_IDS) for second in ROBOT_IDS[index + 1:]),
            )
        self.assertEqual(session.state, "COMPLETE")
        self.assertGreaterEqual(minimum_gap, MIN_SEPARATION_M - 1e-6)
        self.assertIsNotNone(session.anchor_pose)
        self.assertIsNotNone(session.line_targets)
        self.assertEqual(session.line_targets["robot4"], session.anchor_pose)
        for index, first in enumerate(ROBOT_IDS):
            for second in ROBOT_IDS[index + 1:]:
                gap = math.hypot(
                    session.line_targets[first][0] - session.line_targets[second][0],
                    session.line_targets[first][1] - session.line_targets[second][1],
                )
                self.assertGreaterEqual(gap, MIN_SEPARATION_M)

    def test_square_turn_is_reusable_and_runs_longer_than_ten_seconds(self):
        poses = {
            "robot1": Pose(-0.75, 0.0, 0.0),
            "robot2": Pose(-0.25, 0.0, 0.0),
            "robot3": Pose(0.25, 0.0, 0.0),
            "robot4": Pose(0.75, 0.0, 0.0),
        }
        session = SquareTurnSession(
            FormationPlanner(), 0.5, straight_m=0.6, turn_radius_m=0.4,
            cruise_speed_mps=0.15, turn_direction="left", stable_reconnect_s=0.0,
        )
        minimum_gap = float("inf")
        for step in range(1000):
            now = step * 0.1
            decision = session.tick(now, readings(poses, now))
            if decision.state == "COMPLETE":
                break
            self.assertEqual(decision.state, "RUNNING")
            self.assertEqual(set(decision.velocities), set(ROBOT_IDS))
            self.assertEqual(set(decision.headings), set(ROBOT_IDS))
            poses = {
                robot: Pose(
                    poses[robot].x + decision.velocities[robot][0] * 0.1,
                    poses[robot].y + decision.velocities[robot][1] * 0.1,
                    poses[robot].yaw + max(
                        -0.06,
                        min(0.06, (decision.headings[robot] - poses[robot].yaw + math.pi) % (2 * math.pi) - math.pi),
                    ),
                )
                for robot in ROBOT_IDS
            }
            minimum_gap = min(
                minimum_gap,
                *(math.hypot(poses[first].x - poses[second].x, poses[first].y - poses[second].y)
                  for index, first in enumerate(ROBOT_IDS) for second in ROBOT_IDS[index + 1:]),
            )
        self.assertEqual(session.state, "COMPLETE")
        self.assertGreaterEqual(minimum_gap, MIN_SEPARATION_M - 1e-6)
        self.assertIsNotNone(session.motion_started_s)
        self.assertIsNotNone(session.motion_finished_s)
        self.assertGreater(session.motion_finished_s - session.motion_started_s, 10.0)
        self.assertEqual(set(session.square_slots), set(ROBOT_IDS))

    def test_offline_recovery_replans_from_fresh_pose(self):
        session = ReconfigurationSession(planner(), Request("square", 0.5))
        self.assertTrue(session.tick(0, readings(FIELD_POSES_2026_09_18, 0)).stop_all)
        first = session.tick(2.1, readings(FIELD_POSES_2026_09_18, 2.1))
        self.assertEqual(first.state, "RUNNING")
        self.assertFalse(first.stop_all)
        self.assertTrue(session.tick(2.2, readings(FIELD_POSES_2026_09_18, 2.2, offline="robot2")).stop_all)
        self.assertIsNone(session.plan)
        changed = dict(FIELD_POSES_2026_09_18)
        changed["robot2"] = Pose(-0.28, 0.34, -0.037)
        self.assertTrue(session.tick(3, readings(changed, 3)).stop_all)
        resumed = session.tick(5.1, readings(changed, 5.1))
        self.assertEqual(resumed.state, "RUNNING")
        self.assertFalse(resumed.stop_all)
        self.assertEqual(session.expected["robot2"], (changed["robot2"].x, changed["robot2"].y))

    def test_stale_lidar_and_invalid_pose_stop(self):
        session = ReconfigurationSession(planner(), Request("line", 0.5))
        bad = readings(ROW, 1)
        bad["robot3"] = Telemetry(ROW["robot3"], 1, True, lidar_fresh=False)
        self.assertTrue(session.tick(1, bad).stop_all)
        bad = readings(ROW, 2)
        bad["robot3"] = Telemetry(Pose(math.nan, 0), 2, True)
        self.assertTrue(session.tick(2, bad).stop_all)

    def test_blocked_arena_and_checkpoint_require_fresh_plan(self):
        blocked = FormationPlanner(arena=(-1, 1, -1, 1))
        with self.assertRaises(PlanningError):
            blocked.plan(ROW, Request("square", 0.5))
        session = ReconfigurationSession(planner(), Request("diamond", 0.5))
        session.tick(0, readings(ROW, 0))
        session.tick(2.1, readings(ROW, 2.1))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mission.json"
            session.checkpoint(path)
            restored = ReconfigurationSession.from_checkpoint(planner(), path)
            self.assertIsNone(restored.plan)
            self.assertTrue(restored.tick(0, readings(ROW, 0)).stop_all)

    def test_triangle_lap_route_is_closed_and_keeps_formation(self):
        map_path = ROOT / "evidence" / "current_map" / "classroom.pgm"
        grid = OccupancyGrid(map_path, 0.05, (-4.61, -4.1))
        engine = FormationPlanner(arena=(-3.3, 3.3, -3.3, 3.3), map_grid=grid)
        plan = build_lap_plan(engine, (-2.6, 2.6, -1.8, 2.6), "triangle", 0.5)
        self.assertEqual(plan.center_route[0], plan.center_route[-1])
        self.assertEqual({len(plan.robot_routes[robot]) for robot in plan.robot_routes}, {5})
        for first_index, first in enumerate(ROBOT_IDS):
            for second in ROBOT_IDS[first_index + 1:]:
                gaps = [
                    math.hypot(a[0] - b[0], a[1] - b[1])
                    for a, b in zip(plan.robot_routes[first], plan.robot_routes[second])
                ]
                self.assertGreaterEqual(min(gaps), engine.separation)


if __name__ == "__main__":
    unittest.main()
