from __future__ import annotations

"""Small, dependency-free graph/Laplacian utilities for standard formation mode.

The standard mode models each holonomic robot as a first-order single-integrator
in the shared map frame.  For an undirected graph G and a virtual leader pinning
matrix B, the displacement error dynamics are

    e_dot = -(k L + k_a B) e

where L is the graph Laplacian.  A positive smallest eigenvalue of L+B is the
runtime certificate used by the lab before accepting a Laplacian experiment.
"""

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


DEFAULT_ROBOT_IDS = ("Robot01", "Robot02", "Robot03", "Robot04")


def _symmetric_eigenvalues(matrix: Sequence[Sequence[float]], tolerance: float = 1e-12) -> tuple[float, ...]:
    """Return eigenvalues of a small real symmetric matrix using Jacobi rotations."""

    size = len(matrix)
    if size == 0:
        return ()
    values = [[float(matrix[row][column]) for column in range(size)] for row in range(size)]
    if any(len(row) != size for row in values):
        raise ValueError("matrix must be square")
    for _ in range(max(20, size * size * 20)):
        pivot_row, pivot_column = 0, 1 if size > 1 else 0
        largest = 0.0
        for row in range(size):
            for column in range(row + 1, size):
                if abs(values[row][column]) > largest:
                    largest = abs(values[row][column])
                    pivot_row, pivot_column = row, column
        if largest <= tolerance or size == 1:
            break
        theta = 0.5 * math.atan2(
            2.0 * values[pivot_row][pivot_column],
            values[pivot_column][pivot_column] - values[pivot_row][pivot_row],
        )
        cosine, sine = math.cos(theta), math.sin(theta)
        for index in range(size):
            if index in (pivot_row, pivot_column):
                continue
            row_value = values[index][pivot_row]
            column_value = values[index][pivot_column]
            values[index][pivot_row] = values[pivot_row][index] = cosine * row_value - sine * column_value
            values[index][pivot_column] = values[pivot_column][index] = sine * row_value + cosine * column_value
        diagonal_row = values[pivot_row][pivot_row]
        diagonal_column = values[pivot_column][pivot_column]
        off_diagonal = values[pivot_row][pivot_column]
        values[pivot_row][pivot_row] = cosine * cosine * diagonal_row - 2.0 * sine * cosine * off_diagonal + sine * sine * diagonal_column
        values[pivot_column][pivot_column] = sine * sine * diagonal_row + 2.0 * sine * cosine * off_diagonal + cosine * cosine * diagonal_column
        values[pivot_row][pivot_column] = values[pivot_column][pivot_row] = 0.0
    return tuple(sorted(round(values[index][index], 12) for index in range(size)))


@dataclass(frozen=True)
class GraphTopology:
    """Weighted undirected graph plus virtual-leader pinning weights."""

    robot_ids: tuple[str, ...]
    adjacency: tuple[tuple[float, ...], ...]
    pinning: tuple[float, ...]
    name: str = "ring_virtual_leader"

    def __post_init__(self) -> None:
        size = len(self.robot_ids)
        if len(self.adjacency) != size or any(len(row) != size for row in self.adjacency):
            raise ValueError("adjacency must match robot_ids")
        if len(self.pinning) != size:
            raise ValueError("pinning must match robot_ids")
        for row in range(size):
            if self.adjacency[row][row] != 0.0:
                raise ValueError("adjacency diagonal must be zero")
            for column in range(size):
                if self.adjacency[row][column] < 0.0:
                    raise ValueError("adjacency weights must be non-negative")
                if abs(self.adjacency[row][column] - self.adjacency[column][row]) > 1e-9:
                    raise ValueError("standard mode requires an undirected graph")
        if any(value < 0.0 for value in self.pinning):
            raise ValueError("pinning weights must be non-negative")

    @classmethod
    def from_edges(
        cls,
        robot_ids: Iterable[str] = DEFAULT_ROBOT_IDS,
        edges: Iterable[Sequence[object]] = (),
        pinning: Mapping[str, float] | None = None,
        name: str = "custom",
    ) -> "GraphTopology":
        ids = tuple(robot_ids)
        indices = {robot_id: index for index, robot_id in enumerate(ids)}
        matrix = [[0.0 for _ in ids] for _ in ids]
        for edge in edges:
            if len(edge) not in (2, 3):
                raise ValueError("graph edges must be [robot_i, robot_j] or [robot_i, robot_j, weight]")
            first, second = str(edge[0]), str(edge[1])
            if first not in indices or second not in indices or first == second:
                raise ValueError(f"invalid graph edge: {first}, {second}")
            weight = float(edge[2]) if len(edge) == 3 else 1.0
            if weight <= 0.0:
                raise ValueError("graph edge weights must be positive")
            matrix[indices[first]][indices[second]] = weight
            matrix[indices[second]][indices[first]] = weight
        pinning_map = pinning or {}
        pinning_values = tuple(float(pinning_map.get(robot_id, 0.0)) for robot_id in ids)
        return cls(ids, tuple(tuple(row) for row in matrix), pinning_values, name)

    def index(self, robot_id: str) -> int:
        try:
            return self.robot_ids.index(robot_id)
        except ValueError as exc:
            raise ValueError(f"unknown robot id: {robot_id}") from exc

    def neighbors(self, robot_id: str) -> dict[str, float]:
        row = self.adjacency[self.index(robot_id)]
        return {peer_id: row[index] for index, peer_id in enumerate(self.robot_ids) if row[index] > 0.0}

    def pinning_weight(self, robot_id: str) -> float:
        return self.pinning[self.index(robot_id)]

    def laplacian(self) -> tuple[tuple[float, ...], ...]:
        return tuple(
            tuple(
                (sum(self.adjacency[row]) if row == column else 0.0) - self.adjacency[row][column]
                for column in range(len(self.robot_ids))
            )
            for row in range(len(self.robot_ids))
        )

    def pinned_matrix(self) -> tuple[tuple[float, ...], ...]:
        laplacian = self.laplacian()
        return tuple(
            tuple(laplacian[row][column] + (self.pinning[row] if row == column else 0.0) for column in range(len(self.robot_ids)))
            for row in range(len(self.robot_ids))
        )

    def stability_report(self, tolerance: float = 1e-9) -> dict[str, object]:
        laplacian = self.laplacian()
        pinned = self.pinned_matrix()
        eigenvalues = _symmetric_eigenvalues(pinned)
        lambda_min = eigenvalues[0] if eigenvalues else 0.0
        return {
            "topology": self.name,
            "robot_ids": list(self.robot_ids),
            "adjacency": [list(row) for row in self.adjacency],
            "laplacian": [list(row) for row in laplacian],
            "pinning": list(self.pinning),
            "pinned_matrix": [list(row) for row in pinned],
            "eigenvalues_L_plus_B": list(eigenvalues),
            "lambda_min": lambda_min,
            "exponentially_stable_nominal_model": lambda_min > tolerance,
            "criterion": "lambda_min(L+B)>0 for e_dot=-(kL+k_aB)e",
            "second_order": self.second_order_stability_report(),
        }

    def second_order_stability_report(
        self,
        position_gain: float = 0.9,
        velocity_gain: float = 1.4,
        tolerance: float = 1e-9,
    ) -> dict[str, object]:
        """Check the standard double-integrator characteristic roots.

        For every eigenvalue lambda of H=L+B, the modal polynomial is
        ``s^2 + velocity_gain*lambda*s + position_gain*lambda``.
        """

        if position_gain <= 0.0 or velocity_gain <= 0.0:
            return {
                "position_gain": position_gain,
                "velocity_gain": velocity_gain,
                "eigenvalues_L_plus_B": [],
                "max_real_pole": 0.0,
                "exponentially_stable_nominal_model": False,
                "criterion": "lambda_min(L+B)>0 and k_p>0 and k_d>0",
            }
        eigenvalues = _symmetric_eigenvalues(self.pinned_matrix())
        poles: list[list[float]] = []
        max_real = float("-inf")
        for eigenvalue in eigenvalues:
            discriminant = (velocity_gain * eigenvalue) ** 2 - 4.0 * position_gain * eigenvalue
            if discriminant >= 0.0:
                root = math.sqrt(discriminant)
                roots = ((-velocity_gain * eigenvalue + root) / 2.0, (-velocity_gain * eigenvalue - root) / 2.0)
                poles.append([[round(value, 12), 0.0] for value in roots])
                max_real = max(max_real, *roots)
            else:
                real = -velocity_gain * eigenvalue / 2.0
                imag = math.sqrt(-discriminant) / 2.0
                poles.append([[round(real, 12), round(imag, 12)], [round(real, 12), round(-imag, 12)]])
                max_real = max(max_real, real)
        stable = bool(eigenvalues) and eigenvalues[0] > tolerance and max_real < -tolerance
        return {
            "position_gain": position_gain,
            "velocity_gain": velocity_gain,
            "eigenvalues_L_plus_B": list(eigenvalues),
            "modal_poles_real_imag": poles,
            "max_real_pole": round(max_real, 12) if poles else 0.0,
            "exponentially_stable_nominal_model": stable,
            "criterion": "lambda_min(L+B)>0 and k_p>0 and k_d>0",
        }


def default_topology() -> GraphTopology:
    """Ring communication graph with Robot01 as the virtual leader pin."""

    return GraphTopology.from_edges(
        edges=(
            ("Robot01", "Robot02"),
            ("Robot02", "Robot03"),
            ("Robot03", "Robot04"),
            ("Robot04", "Robot01"),
        ),
        pinning={"Robot01": 1.0},
        name="ring_virtual_leader",
    )


def topology_from_config(config: Mapping[str, object] | None) -> GraphTopology:
    graph = (config or {}).get("consensus_graph", {})
    if not isinstance(graph, Mapping):
        return default_topology()
    edges = graph.get("edges")
    pinning = graph.get("pinning")
    if not isinstance(edges, list) or not isinstance(pinning, Mapping):
        return default_topology()
    return GraphTopology.from_edges(
        edges=edges,
        pinning={str(key): float(value) for key, value in pinning.items()},
        name=str(graph.get("name") or "custom"),
    )
