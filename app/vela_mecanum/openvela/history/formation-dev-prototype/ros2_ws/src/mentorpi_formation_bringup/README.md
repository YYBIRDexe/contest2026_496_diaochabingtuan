# MentorPi SLAM / localization / multi-robot bringup

This package is the hardware-side bridge for product CZ225: the Hiwonder
Raspberry Pi 5 MentorPi M1 mecanum chassis. It assumes the vendor drivers
publish standard ROS 2 interfaces, but it does not guess their final topic or
frame names. Verify them on the first car before enabling motion.

## 0. Network and driver contract

On every car and the operator laptop, source `scripts/set_multi_robot_env.sh`
with the same `ROS_DOMAIN_ID` (the template defaults to 42). Keep
`ROS_LOCALHOST_ONLY=0`. Start the MentorPi base/chassis driver, wheel-encoder
odometry and the 2D lidar driver first. The contract needed by this package is:

| Interface | Type | Required frame/topic |
| --- | --- | --- |
| velocity command | `geometry_msgs/Twist` | `<robot>/controller/cmd_vel` |
| wheel/IMU odometry | `nav_msgs/Odometry` | `<robot>/odom`, child `<robot>/base_link` |
| planar laser | `sensor_msgs/LaserScan` | `<robot>/scan_raw`, frame `<robot>/laser` |
| global pose | `geometry_msgs/PoseWithCovarianceStamped` | `<robot>/amcl_pose`, frame `map` |

The exact vendor topics may differ. Use `ros2 topic list`,
`ros2 topic type`, `ros2 topic echo`, and `ros2 run tf2_tools view_frames` to
fill the mapping before touching the formation node.

## 1. One-car classroom mapping (teleoperation)

Install this package in the car's `ros2_ws`, then run the vendor base and lidar
launch files. Verify the laser in RViz2 before mapping:

```bash
ros2 topic hz /robot01/scan_raw
ros2 topic echo /robot01/scan_raw --once
ros2 run tf2_ros tf2_echo robot01/base_link robot01/laser
```

The lidar transform must be measured, not copied from this template. If the
vendor URDF does not provide it, launch the fallback after replacing `z` and
`yaw` with measured values:

```bash
ros2 launch mentorpi_formation_bringup lidar_static_tf.launch.py \
  parent:=robot01/base_link child:=robot01/laser z:=0.15 yaw:=0.0
```

Then start asynchronous 2D SLAM:

```bash
ros2 launch mentorpi_formation_bringup mapping.launch.py \
  namespace:=robot01 scan_topic:=scan_raw \
  odom_frame:=robot01/odom base_frame:=robot01/base_link
```

Drive the car slowly with the vendor joystick/teleop node. Use RViz2 with
Fixed Frame `map`, display `Map`, `LaserScan`, and `TF`. Close loops around
the classroom and avoid fast spins; mecanum lateral slip makes odometry less
reliable, so scan matching and loop closure must do the final correction.
Save the map only after the complete loop is stable:

```bash
# The helper is installed as package data; invoke it through bash:
bash "$(ros2 pkg prefix mentorpi_formation_bringup)/share/mentorpi_formation_bringup/scripts/save_classroom_map.sh" ~/maps/classroom
# or directly:
ros2 run nav2_map_server map_saver_cli -f ~/maps/classroom
```

The stock Hiwonder image also supplies the official one-car workflow
`ros2 launch slam slam.launch.py` and teleoperation command
`ros2 launch peripherals teleop_key_control.launch.py`. The recommended mapper
is `slam_toolbox` async mode: it is the maintained ROS2
2D SLAM package and provides loop closure and a serialized pose graph. This is
preferable to writing a new lidar SLAM algorithm for this classroom-scale map.

## 2. Single-car map localization

After the map is saved, stop mapping and start AMCL with the same calibrated
TF and odometry frames:

```bash
ros2 launch mentorpi_formation_bringup localization.launch.py \
  namespace:=robot01 map:=~/maps/classroom.yaml \
  odom_frame:=robot01/odom base_frame:=robot01/base_link
ros2 topic pub --once /robot01/initialpose \
  geometry_msgs/PoseWithCovarianceStamped "..."
```

Use RViz2 `2D Pose Estimate` to initialize, then verify `map -> robot01/odom`
and `robot01/odom -> robot01/base_link`. AMCL is the default static-map
localizer here because it is robust to kidnapped-robot recovery and does not
continue changing the classroom map. If continuous pose-graph localization is
desired, use slam_toolbox localization mode with the serialized pose graph
instead; do not run AMCL and slam_toolbox localization simultaneously.

The AMCL configuration uses `nav2_amcl::OmniMotionModel`, not the differential
model, because the M1 mecanum chassis has real lateral velocity. The formation
agent consumes `/robotXX/amcl_pose` for global `map` position and covariance;
`/robotXX/odom` supplies body-frame velocity only. It rejects stale poses,
wrong frame IDs and excessive x/y/yaw covariance before publishing motion.
For a measured initial pose, the bundled publisher waits for the correct AMCL
subscriber before sending it:

```bash
ros2 run mentorpi_formation_bringup set_initial_pose \
  --namespace robot01 --x 1.20 --y -0.75 --yaw 1.5708
```

For better odometry, the optional `config/ekf_odom_imu.yaml` documents a
two-dimensional `robot_localization` EKF. Enable it only after replacing its
placeholder `/odom/raw` and `/imu/data` topics and deciding which node owns
the `odom -> base_link` transform. There must be exactly one TF publisher for
that edge.

## 3. Four cars on one map

Copy the same map YAML/PGM to the operator host or a map-server car. Start:

```bash
ros2 launch mentorpi_formation_bringup multi_robot_localization.launch.py \
  map:=/home/vela/maps/classroom.yaml
ros2 run mentorpi_formation_bringup tf_audit
```

The launch creates one global `map` and four isolated AMCL nodes. The required
tree is:

```text
map
├── robot01/odom ── robot01/base_link ── robot01/laser
├── robot02/odom ── robot02/base_link ── robot02/laser
├── robot03/odom ── robot03/base_link ── robot03/laser
└── robot04/odom ── robot04/base_link ── robot04/laser
```

Only `map` is shared. Every odom, base, laser, cmd_vel, scan and status topic
must be namespaced. Initialize each car separately in RViz2 and run
`tf_audit` until all four `map -> odom -> base_link` chains are present,
finite, and distinct. If two cars start at the same physical location, use
AprilTag/known landmarks or a measured tape/grid to disambiguate their initial
poses; simply copying one initial pose to all four is not accurate localization.

When the graph is stable, launch one `mentorpi_agent.py` per car with its
matching namespace and the shared-map odometry. Only then enable the existing
formation mission gateway and choose `anchored`, `laplacian`, or `second_order`.

## 4. QEMU virtual hardware acceptance

The package includes a deterministic four-car stand-in that publishes the same
topic and TF contract and integrates each car's own holonomic command:

```bash
ros2 run mentorpi_formation_bringup virtual_fleet
ros2 run mentorpi_formation_bringup hardware_probe \
  --namespace robot01 --require-localization
ros2 run mentorpi_formation_bringup tf_audit
ros2 run mentorpi_formation_bringup virtual_acceptance \
  --control-mode laplacian
```

This proves ROS discovery, topic types, namespace isolation, TF composition,
AMCL-pose consumption and distributed command flow. Synthetic poses/scans do
not prove physical lidar accuracy or produce a real classroom map.

## 5. Acceptance gates before formation

1. One car: scan rate stable, laser TF measured, mapping closes its loop, and
   saved map is readable.
2. One car: AMCL covariance settles while driving a rectangle; no TF jumps or
   duplicate publishers.
3. Four cars: same `ROS_DOMAIN_ID`, all topics discoverable, four unique TF
   chains, each robot's covariance and map pose logged.
4. Wheels raised: verify `cmd_vel` x/y signs and mecanum lateral motion.
5. Floor test: low speed, large separation, hardware output enabled only after
   the preceding gates pass.

The QEMU formation lab can validate graph/controller mathematics now, but it
cannot produce a classroom map or certify real lidar/odometry accuracy.

For a four-car installable handoff, use `deploy/install_on_robot.sh` from the
bundle root. It installs disabled-by-default systemd services and runs a
hardware/TF preflight before allowing formation output.
