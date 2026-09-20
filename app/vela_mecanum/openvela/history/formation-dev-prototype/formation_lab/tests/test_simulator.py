import tempfile
import time
import unittest
import math
import json
from pathlib import Path

from formation_lab.simulator import FormationSimulator, LabError
from formation_lab.agent import AgentObservation, FormationMission, ROBOT_IDS, RobotFormationAgent
from formation_lab.laplacian import GraphTopology, default_topology
from formation_lab.second_order import SecondOrderFormationAgent, SecondOrderCommand
from formation_lab.mentorpi_agent import localization_covariance_ok, world_to_body
from formation_lab.mission_gateway import mission_from_experiment
from formation_lab.llm_stub import create_chat_completion


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.sim = FormationSimulator(Path(self.temp.name), tick_s=0.005, time_scale=100)

    def tearDown(self):
        self.sim.close()
        self.temp.cleanup()

    def test_square_completes_and_is_idempotent(self):
        request = {"action": "start", "experiment_id": "unit-square", "formation": "square", "spacing_m": 0.8, "duration_s": 2}
        first = self.sim.handle_command(request)
        replay = self.sim.handle_command(request)
        self.assertEqual(first["experiment"]["experiment_id"], "unit-square")
        self.assertTrue(replay["experiment"]["idempotent_replay"])
        deadline = time.time() + 2
        while time.time() < deadline and self.sim.snapshot()["state"] not in ("FINISHED", "FAILED"):
            time.sleep(0.01)
        self.assertEqual(self.sim.snapshot()["state"], "FINISHED")

    def test_unsafe_spacing_rejected(self):
        with self.assertRaises(LabError):
            self.sim.handle_command({"action": "start", "spacing_m": 9})

    def test_fault_stops_experiment(self):
        self.sim.handle_command({"action": "start", "experiment_id": "unit-fault", "duration_s": 30})
        self.sim.handle_command({"action": "inject_fault", "fault": "offline", "robot_id": "Robot02"})
        deadline = time.time() + 1
        while time.time() < deadline and self.sim.snapshot()["state"] != "FAILED":
            time.sleep(0.01)
        result = self.sim.snapshot()
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(result["error_code"], "robot_offline")

    def test_holonomic_command_contract(self):
        body_vx, body_vy = world_to_body(1.0, 0.0, math.pi / 2)
        self.assertAlmostEqual(body_vx, 0.0, places=5)
        self.assertAlmostEqual(body_vy, -1.0, places=5)

    def test_amcl_covariance_gate(self):
        covariance = [0.0] * 36
        covariance[0], covariance[7], covariance[35] = 0.04, 0.05, 0.03
        self.assertTrue(localization_covariance_ok(covariance, 0.25, 0.25))
        covariance[7] = 0.5
        self.assertFalse(localization_covariance_ok(covariance, 0.25, 0.25))

    def test_inactive_state_publishes_stop(self):
        mission = mission_from_experiment({"state": "FAILED", "experiment_id": "x"})
        self.assertFalse(mission["enabled"])

    def test_each_robot_owns_an_independent_controller(self):
        mission = FormationMission("distributed-unit", "square", 0.8)
        observations = {
            "Robot01": AgentObservation("Robot01", -1.4, -1.0),
            "Robot02": AgentObservation("Robot02", -1.4, 1.0),
            "Robot03": AgentObservation("Robot03", 1.4, 1.0),
            "Robot04": AgentObservation("Robot04", 1.4, -1.0),
        }
        agents = [RobotFormationAgent(robot_id) for robot_id in ROBOT_IDS]
        commands = []
        for agent in agents:
            agent.accept_mission(mission)
            commands.append(agent.compute(observations[agent.robot_id], (value for key, value in observations.items() if key != agent.robot_id)))
        self.assertEqual(len({id(agent) for agent in agents}), 4)
        self.assertTrue(all(command.safe for command in commands))

    def test_peer_loss_stops_local_agent(self):
        agent = RobotFormationAgent("Robot01")
        agent.accept_mission(FormationMission("peer-loss", "line", 0.8))
        peers = [AgentObservation("Robot02", 0, 0), AgentObservation("Robot03", 0, 0, online=False), AgentObservation("Robot04", 0, 0)]
        command = agent.compute(AgentObservation("Robot01", 0, 0), peers)
        self.assertFalse(command.safe)
        self.assertEqual((command.world_vx, command.world_vy, command.wz), (0.0, 0.0, 0.0))

    def test_local_agent_enforces_separation(self):
        agent = RobotFormationAgent("Robot01")
        agent.accept_mission(FormationMission("separation", "square", 0.8))
        peers = [AgentObservation("Robot02", 0.1, 0.0), AgentObservation("Robot03", 1.0, 1.0), AgentObservation("Robot04", 1.0, -1.0)]
        command = agent.compute(AgentObservation("Robot01", 0.0, 0.0), peers)
        self.assertFalse(command.safe)
        self.assertEqual(command.reason, "local_separation_violation")

    def test_all_supported_formations_converge(self):
        for index, formation in enumerate(("square", "line", "circle", "diamond")):
            with self.subTest(formation=formation):
                if self.sim.snapshot()["state"] != "IDLE":
                    self.sim.handle_command({"action": "reset"})
                self.sim.handle_command({"action": "start", "experiment_id": f"shape-{index}", "formation": formation, "spacing_m": 0.8, "duration_s": 1})
                deadline = time.time() + 2
                while time.time() < deadline and self.sim.snapshot()["state"] not in ("FINISHED", "FAILED"):
                    time.sleep(0.01)
                self.assertEqual(self.sim.snapshot()["state"], "FINISHED")

    def test_laplacian_graph_has_positive_pinned_spectrum(self):
        report = default_topology().stability_report()
        self.assertEqual(report["laplacian"], [[2.0, -1.0, 0.0, -1.0], [-1.0, 2.0, -1.0, 0.0], [0.0, -1.0, 2.0, -1.0], [-1.0, 0.0, -1.0, 2.0]])
        self.assertGreater(report["lambda_min"], 0.0)
        self.assertTrue(report["exponentially_stable_nominal_model"])

    def test_laplacian_mode_converges_with_ring_neighbors(self):
        self.sim.handle_command({"action": "start", "experiment_id": "laplacian-square", "formation": "square", "spacing_m": 0.8, "duration_s": 1, "control_mode": "laplacian"})
        deadline = time.time() + 2
        while time.time() < deadline and self.sim.snapshot()["state"] not in ("FINISHED", "FAILED"):
            time.sleep(0.01)
        result = self.sim.snapshot()
        self.assertEqual(result["state"], "FINISHED")
        self.assertEqual(result["control_mode"], "laplacian")
        self.assertEqual(result["consensus_graph"]["topology"], "ring_virtual_leader")
        self.assertEqual(result["max_error_m"], 0.0)
        self.assertAlmostEqual(result["minimum_distance_m"], 0.8, places=4)

    def test_laplacian_agent_only_requires_graph_neighbors(self):
        topology = default_topology()
        agent = RobotFormationAgent("Robot01", control_mode="laplacian", topology=topology)
        agent.accept_mission(FormationMission("local-neighbors", "square", 0.8, control_mode="laplacian"))
        # Robot03 is not a Robot01 neighbor in the ring and may be absent.
        peers = [AgentObservation("Robot02", -0.4, 0.4), AgentObservation("Robot04", 0.4, -0.4)]
        command = agent.compute(AgentObservation("Robot01", -0.4, -0.4), peers)
        self.assertTrue(command.safe)

    def test_unpinned_disconnected_graph_is_not_stable(self):
        topology = GraphTopology.from_edges(edges=(("Robot01", "Robot02"),), pinning={}, name="bad")
        report = topology.stability_report()
        self.assertFalse(report["exponentially_stable_nominal_model"])

    def test_local_llm_selects_laplacian_mode(self):
        response = create_chat_completion({"messages": [{"role": "user", "content": "用经典拉普拉斯一致性启动正方形编队，间距0.8米，运行2秒"}]})
        arguments = json.loads(response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(arguments["control_mode"], "laplacian")

    def test_second_order_spectrum_is_hurwitz(self):
        report = default_topology().stability_report()["second_order"]
        self.assertGreater(report["position_gain"], 0.0)
        self.assertGreater(report["velocity_gain"], 0.0)
        self.assertLess(report["max_real_pole"], 0.0)
        self.assertTrue(report["exponentially_stable_nominal_model"])

    def test_second_order_agent_uses_velocity_damping(self):
        agent = SecondOrderFormationAgent("Robot01", topology=default_topology())
        agent.accept_mission(FormationMission("second-order-agent", "square", 0.8, control_mode="second_order"))
        own = AgentObservation("Robot01", -0.4, -0.4, vx=0.5, vy=0.0)
        peers = [
            AgentObservation("Robot02", -0.4, 0.4),
            AgentObservation("Robot04", 0.4, -0.4),
        ]
        command = agent.compute(own, peers)
        self.assertIsInstance(command, SecondOrderCommand)
        self.assertLess(command.accel_x, 0.0)
        self.assertTrue(command.safe)

    def test_second_order_mode_converges(self):
        temp = tempfile.TemporaryDirectory()
        simulator = FormationSimulator(Path(temp.name), tick_s=0.005, time_scale=10)
        try:
            simulator.handle_command({"action": "start", "experiment_id": "second-order-square", "formation": "square", "spacing_m": 0.8, "duration_s": 1, "control_mode": "second_order"})
            deadline = time.time() + 4
            while time.time() < deadline and simulator.snapshot()["state"] not in ("FINISHED", "FAILED"):
                time.sleep(0.01)
            result = simulator.snapshot()
            self.assertEqual(result["state"], "FINISHED")
            self.assertEqual(result["control_mode"], "second_order")
            self.assertTrue(result["consensus_graph"]["second_order"]["exponentially_stable_nominal_model"])
            self.assertEqual(result["max_error_m"], 0.0)
            self.assertAlmostEqual(result["minimum_distance_m"], 0.8, places=4)
        finally:
            simulator.close()
            temp.cleanup()

    def test_second_order_supported_formations_converge(self):
        for formation in ("square", "line", "circle", "diamond"):
            with self.subTest(formation=formation):
                temp = tempfile.TemporaryDirectory()
                simulator = FormationSimulator(Path(temp.name), tick_s=0.005, time_scale=10)
                try:
                    simulator.handle_command({"action": "start", "experiment_id": f"second-order-{formation}", "formation": formation, "spacing_m": 0.8, "duration_s": 1, "control_mode": "second_order"})
                    deadline = time.time() + 4
                    while time.time() < deadline and simulator.snapshot()["state"] not in ("FINISHED", "FAILED"):
                        time.sleep(0.01)
                    result = simulator.snapshot()
                    self.assertEqual(result["state"], "FINISHED")
                    self.assertEqual(result["max_error_m"], 0.0)
                finally:
                    simulator.close()
                    temp.cleanup()

    def test_local_llm_selects_second_order_mode(self):
        response = create_chat_completion({"messages": [{"role": "user", "content": "用二阶双积分一致性启动正方形编队，间距0.8米，运行2秒"}]})
        arguments = json.loads(response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(arguments["control_mode"], "second_order")


if __name__ == "__main__":
    unittest.main()
