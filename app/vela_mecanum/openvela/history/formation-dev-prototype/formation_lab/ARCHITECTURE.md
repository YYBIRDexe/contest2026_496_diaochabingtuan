# Four-MentorPi formation architecture

The control system has a strict two-level boundary.

1. The openvela AI Agent converts natural language into a constrained mission:
   `action`, `experiment_id`, `formation`, `spacing_m`, and `duration_s`.
2. The mission gateway broadcasts that task unchanged. It has no wheel or
   chassis velocity output.
3. Each MentorPi runs the same `RobotFormationAgent` with its own `robot_id`.
   That Agent reads each `/robotXX/amcl_pose` in one shared `map` frame and
   `/robotXX/odom` only for velocity,
   computes the error of its assigned slot and the peer-relative formation
   error, then publishes only its own `vx`, `vy`, and `wz`. It also emits an
   Agent status heartbeat containing the mission id and local safety decision.
4. The local simulator uses four separate controller objects and the same
   mission/observation/command contract, so controller development can proceed
   before the cars arrive.

## Controller modes

The default `anchored` mode is the original absolute-slot plus peer-relative
controller. The opt-in `laplacian` mode uses the standard first-order
single-integrator displacement-consensus model on a fixed undirected graph:

```text
e_dot = -(k L + k_a B) e
```

`L` is the weighted graph Laplacian and `B` pins Robot01 to the virtual leader
slot. The default graph is the ring `01-02-03-04-01`, with Robot01 pinned. The
service publishes `L`, `L+B`, eigenvalues, and `lambda_min(L+B)` in its
capabilities and experiment state. A Laplacian experiment is accepted only when
`lambda_min(L+B) > 0`, which is the nominal exponential-stability certificate
for this model. Each agent uses only its configured graph neighbors in this
mode; the coordinator still sends missions and never sends velocity commands.

Example request:

```json
{"action":"start","formation":"square","spacing_m":0.8,
 "duration_s":30,"control_mode":"laplacian"}
```

The opt-in `second_order` mode uses the standard holonomic double-integrator
model. Each car integrates its own acceleration state and applies position and
velocity feedback over the same pinned graph:

```text
e_ddot + k_d (L+B) e_dot + k_p (L+B) e = 0
```

The default gains are `k_p=0.9`, `k_d=1.4`; the service reports every modal
pole and accepts a run only when all real parts are negative. The simulator
integrates acceleration to velocity and pose. On a real MentorPi, the ROS 2
adapter performs the same local integration before publishing velocity-level
`cmd_vel`, because the chassis interface is velocity based.

Example request:

```json
{"action":"start","formation":"square","spacing_m":0.8,
 "duration_s":30,"control_mode":"second_order"}
```

This is a standard-model implementation and runtime certificate, not a claim of
reproducing every assumption or proof in a particular paper. Communication
delays, switching graphs, dynamics, actuator saturation, and localization
noise remain engineering extensions for later paper-driven models.

Safety is local to every car: missing own localization, a stale or invalid peer,
an invalid mission, a stop mission, or process shutdown produces zero velocity.
The orchestration service adds arena, minimum-separation, timeout, idempotency,
logging, and experiment state checks.

Before enabling hardware output, run the CZ225 ROS graph and TF preflight,
establish a shared localization frame for all four cars, verify mecanum x/y/yaw
signs while wheels are raised, and only then use the deployment enable helper.
