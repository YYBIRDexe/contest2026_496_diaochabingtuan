# openvela Local Formation Lab

Pure-Python, local-only development backend for four CZ225 Hiwonder MentorPi M1
(Raspberry Pi 5, mecanum chassis) robots. The simulator and adapter contract use
holonomic `vx`, `vy`, and `wz` commands.

## Endpoints

- Dashboard: `http://127.0.0.1:8765/`
- Health: `GET /api/v1/health`
- State: `GET /api/v1/state`
- Commands: `POST /api/v1/formation`
- Local OpenAI-compatible stub: `POST /v1/chat/completions`

## CLI

```bash
PYTHONPATH=. python3 -m formation_lab.cli start --id demo-001 --formation square --spacing 0.8 --duration 30
PYTHONPATH=. python3 -m formation_lab.cli status
PYTHONPATH=. python3 -m formation_lab.cli stop
PYTHONPATH=. python3 -m formation_lab.cli reset
```

Experiment requests, trajectories, and results are written below `var/experiments/<experiment_id>/`.

Three controller modes are available: `anchored` (default), `laplacian`, and
`second_order`.
The latter uses a ring communication graph with Robot01 as a virtual-leader
pin and exposes the `lambda_min(L+B)>0` nominal stability certificate before
accepting a run. Select it from the CLI with `--control-mode laplacian` or in
the HTTP request with `"control_mode":"laplacian"`.

`second_order` is the standard pinned double-integrator mode. It uses local
position and velocity feedback, reports the modal poles of
`s² + k_d λ s + k_p λ`, and integrates acceleration to the velocity-level
`cmd_vel` interface. Select it with `--control-mode second_order` or
`"control_mode":"second_order"`.

Run the complete local acceptance sequence while the service is active:

```bash
PYTHONPATH=. python3 tests/acceptance.py
```

## Distributed MentorPi control boundary

`config/mentorpi.json` is deliberately shipped with
`hardware_output_enabled: false`. Its defaults follow the current M1 image but
remain gated until checked against the four actual robots.

`mission_gateway.py` is the upper layer: it broadcasts only the mission id,
formation, spacing, anchor and state. It never publishes velocity. The same
`mentorpi_agent.py` runs once on each car with a different `--robot-id`; every
instance consumes each peer's AMCL pose in the shared `map` frame and uses
odometry only for velocity, runs its own formation and consensus controller,
and publishes only its own REP-103 `/robotXX/controller/cmd_vel`. Wrong-frame
or high-covariance localization, missing
localization, peer timeout, invalid mission and shutdown all produce zero
velocity.

The mapping and conversion can be verified without ROS 2:

```bash
PYTHONPATH=. python3 -m formation_lab.mission_gateway --dry-run
PYTHONPATH=. python3 -m formation_lab.mentorpi_agent --robot-id Robot01 --dry-run
```
