# CZ225 / MentorPi M1 deployment bundle

This directory installs the tested ROS2 code onto the Hiwonder Raspberry Pi 5
Mecanum image. It does not replace the vendor image, controller, lidar driver,
or calibrated URDF.

## Verified stock layout for all four cars

All CZ225 cars in this fleet use the same structure:

- Debian 12 runs on the Raspberry Pi host as user `pi`.
- Docker container `MentorPi` uses image `ros:humble`, host networking, and a
  privileged device mapping.
- ROS2 Humble, the vendor workspace, and the runtime user live inside the
  container at `/opt/ros/humble`, `/home/ubuntu/ros2_ws`, and user `ubuntu`.
- The vendor bringup currently uses `ROS_DOMAIN_ID=0` and unnamespaced topics
  such as `/controller/cmd_vel`.

The installer must be run on the Debian host. It copies and builds the ROS2
package inside the running `MentorPi` container, while installing only the
Docker wrapper services on the host. It verifies the container layout and host
network mode before writing anything.

Do not enable multiple physical cars on one ROS domain until the vendor
bringup, command topics, odometry, laser topics, and TF frames have unique robot
namespaces. Installation is safe because motor output remains disabled.

## Install one copy on each car

Extract the bundle on a car, then assign a different identity:

```bash
sudo ./deploy/install_on_robot.sh Robot01
# use Robot02, Robot03, Robot04 on the other cars
```

The installer builds only `mentorpi_formation_bringup` inside Docker, installs
the formation controller, writes the robot identity and container configuration,
and installs the host systemd wrapper units. It deliberately leaves
localization and motor output disabled.

## Lidar handling for the Mecanum chassis

The stock `sclidar_node` reads `/dev/ttyUSB0` and publishes `LaserScan` on
`/scan_raw` in `lidar_frame`. The installed controller adds two separate
closed-loop protections:

- A local scan guard checks freshness and the sector in the commanded travel
  direction. A stale/invalid scan or an obstacle inside the stop radius sends
  zero velocity; clearance between the stop and slow radii scales velocity.
- AMCL uses scan, odometry, and TF against a shared map to correct accumulated
  wheel slip in the global pose. The raw scan guard avoids obstacles but does
  not by itself correct pose drift.

The guarded motion test is capped at 0.10 m/s and 1.0 second and always sends
several zero commands on exit:

The distance service now targets 1.0 m and remains disabled after installation.
Its initial clearance requirement is therefore 1.45 m. The first field
run on 2026-09-15 aborted after the vendor command-integrated odometry reported
0.50 m despite observed rotation; SLAM then corrected by more than 0.20 m.
The repaired distance node instead compares RF2O measured travel with SLAM
travel, refuses >0.12 m disagreement or >0.12 rad heading deviation, and never
publishes nonzero angular velocity. Re-arm only after live laser frames and
wheels-up forward/yaw direction tests pass. The reported tolerance is a
software stopping threshold, not a verified physical distance guarantee.

Robot01's physical lidar speaks the SC lidar serial protocol. A stale
`LIDAR_TYPE=MS200` setting produced a detected publisher but zero scan frames:
the MS200 parser expects `54 2C`, while the device stream uses `AA 55`.
The verified fix is `LIDAR_TYPE=sclidar` in the host bind-mounted
`/home/pi/docker/tmp/.typerc`; the vendor restart then restored `/scan_raw`
at about 10 Hz. Back up each car's own `.typerc` and identify its actual lidar
protocol before changing this setting. The mission wrapper checks live RF2O
and SLAM processes rather than stale ROS graph node names and uses Fast DDS
UDPv4 for its own participants to avoid damaged SHM port locks.

Robot01's laser odometry had a second, independent fault. `rf2o_laser_odometry`
never reads `angle_min`: `CLaserOdometry2D::init` takes the field of view from
`|angle_max - angle_min|` alone and the range-flow solver then places beam `u`
at `-fovh/2 + u * fovh/(cols-1)`, which only holds for a scan whose declared
angles already run symmetrically about the frame x axis. The sclidar driver
publishes `angle_min = 0` over 0 ... 2*pi instead, so every azimuth rf2o assumed
was about half a turn out and it integrated chassis motion in a frame rotated
by pi. On 2026-09-15, before the fix, an in-place `+0.30 rad/s` command produced
`+0.5505 rad` on the IMU against `+0.5232 rad` on rf2o. Equal signs rule out a
mirrored scan and leave the half-turn rotation as the only consistent cause,
because a mirrored scan would have inverted the yaw as well. During the
preceding forward run the raw scan sectors showed the object behind receding
and the front clearance shrinking, so the chassis really did move forward,
while rf2o reported `-0.147 m`. `/odom_raw` cannot settle that question:
`odom_publisher` integrates the received `cmd_vel`
(`delta_x = linear_x * dt * cos(pose_yaw)`) with no wheel measurement at all, so
it only reports what was commanded, and it keeps its own `pose_yaw` until
something calls `/set_odom`. Do not "fix" this in the guards: the guards were
reading `/scan_raw` correctly. `scan_symmetric`
re-parameterises `/scan_raw` into `/scan_symmetric` - the beam array rotated by
half a turn with the declared angles shifted by the same half turn, which
leaves the set of measured points untouched - and `odometry.launch.py` runs the
vendor rf2o parameters against that topic instead of `/scan_raw`. Check it with
`python3 -m pytest test/test_scan_symmetric.py` and with
`ros2 param get /rf2o_laser_odometry laser_scan_topic`.

After that fix a 1 m mission completed with rf2o reporting 0.965 m and the SLAM
map pose 0.941 m of forward progress, while the raw scan independently showed
the wall ahead 0.93 m nearer and the object behind 0.90 m farther.

A repeat of the same 1 m mission on the evening of 2026-09-15 stopped after
0.70 m with `SLAM yaw jump`. The recorded SLAM map pose moved 0.20 rad of yaw
for a single sample and returned to its previous value on the next one, while
RF2O yaw and the raw scan both showed a smooth forward run; the guard compares
consecutive samples with no filtering, so one correcting `map -> odom` sample is
enough to end the run. The car stopped on the spot and the raw scan confirmed
0.75 m of real travel. Whether slam_toolbox should be allowed to correct that
fast, or the guard needs a correction to persist before it faults, is still
open.

The orbit mission (`run_orbit_mission.sh`) is the second lidar-only manoeuvre. It
follows a single lidar contact, holds it at a fixed range and bearing and keeps
driving forward, which traces a circle around that contact; a contact held at
+90 degrees to the left makes that circle counter-clockwise at a steady-state
yaw rate of `speed / range`. Nothing about the circle is defined against a map,
so the wrapper starts `odometry.launch.py` only - no slam_toolbox, no `map`
frame - and the control loop is closed on the raw scan plus laser odometry:

```bash
sudo /opt/openvela-formation/scripts/run_orbit_mission.sh 1.0 0.70
sudo /opt/openvela-formation/scripts/run_orbit_mission.sh 0 0.70 --observe-only
```

The second form never publishes velocity; it only reports the contact it would
follow. Turns are counted from the unwrapped angle of the car around the contact
- the RF2O yaw plus the measured bearing to that contact - so the alignment turn
at the start of a run does not count towards the lap, while one lap adds 2*pi.
The node refuses to move unless a fresh scan, fresh RF2O odometry and a contact
inside the acquisition sector are all present, and it stops the wheels and
reports a fault when the contact leaves the range envelope (`--min-range`,
`--max-track-range`), is lost for more than 1 s, comes inside the
travel-direction stop radius, leaves less than 0.30 m of clearance anywhere
around the car, or the RF2O yaw jumps by more than 0.12 rad in one sample.
Contact tracking keeps a 0.6 m association window around the range already being
followed, so a nearer wall entering the same sector cannot silently take over
the orbit. The stop wrappers kill a mission by the installed executable path,
because a ROS node name never appears in the process command line.

The orbit has two heading modes. The default `rotating` keeps the contact on one
side of the car and turns the heading, so the chassis mostly drives forward.
`--heading-mode fixed` uses the mecanum wheels' omnidirectional property instead:
it holds the initial heading with a small yaw correction and traces the circle
with translation alone, `speed * (sin, -cos)` of the contact bearing, so the
contact sweeps the whole scan while the car never turns - a left contact is
driven past, one dead ahead is strafed right, one behind is strafed left.
Because the contact then moves through every bearing, that mode tracks it by
following its last bearing instead of a fixed target:

```bash
sudo /opt/openvela-formation/scripts/run_orbit_mission.sh 1.0 0.70 "--heading-mode fixed"
```

The fixed mode is unit tested but has not had a field run yet; the rotating mode
is the one measured below.

The first field run on 2026-09-15 (one turn, hold 0.70 m) acquired the box at
1.107 m and bearing 54 degrees, circled it and reported
`{"status":"completed","turns_completed":1.0006,"final_range_m":0.704,
"final_bearing_deg":90.9}` after 87 s. A read-only observer recorded the lidar
holding the box at 0.700 m within 0.015 m and 90 degrees within 5 degrees for the
whole lap, and the raw scan afterwards showed the box 0.700 m away at
92.7 degrees against 1.109 m at 53.1 degrees before it. That build counted the
lap from the heading alone, so the 36 degree alignment turn was included in it;
the counter now adds the bearing to the contact, which leaves that turn out.


```bash
docker exec --user ubuntu MentorPi bash -lc '
  source /opt/ros/humble/setup.bash
  source /home/ubuntu/ros2_ws/install/setup.bash
  ros2 run mentorpi_formation_bringup lidar_guarded_motion_test \
    --direction forward --speed 0.05 --duration 0.5
'
```

Do not claim slip correction is active until the map, AMCL pose, and complete
`map -> odom -> base_link -> lidar_frame` transform chain have been verified.

Copy the same classroom map pair to every car:

```text
/opt/openvela-formation/maps/classroom.yaml
/opt/openvela-formation/maps/classroom.pgm
```

The `image:` entry in `classroom.yaml` must resolve to the copied PGM. Start
the vendor controller/lidar with the car's namespace and frame prefix, then:

```bash
sudo systemctl enable --now mentorpi-localization.service
```

Set that car's initial pose in the shared `map` frame. Verify the graph before
the wheels touch the floor:

```bash
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 run mentorpi_formation_bringup hardware_probe \
  --namespace robot01 --require-localization
ros2 run mentorpi_formation_bringup tf_audit --robots robot01
```

When the start coordinates are measured, initialize without RViz guessing:

```bash
ros2 run mentorpi_formation_bringup set_initial_pose \
  --namespace robot01 --x 1.20 --y -0.75 --yaw 1.5708
```

The probe expects the verified CZ225 contract:

- `/robot01/controller/cmd_vel` (`geometry_msgs/msg/Twist`), with one chassis subscriber and no competing command publisher;
- `/robot01/odom` (`nav_msgs/msg/Odometry`);
- `/robot01/scan_raw` (`sensor_msgs/msg/LaserScan`);
- `/robot01/amcl_pose` (`geometry_msgs/msg/PoseWithCovarianceStamped`, frame `map`).

Only after calibration, wheels-up direction testing, and a valid AMCL pose:

```bash
sudo /opt/openvela-formation/scripts/enable_formation_agent.sh
```

Emergency/maintenance disable:

```bash
sudo /opt/openvela-formation/scripts/disable_formation_agent.sh
```

The enable script refuses to arm when the driver, scan, AMCL pose or TF chain
is absent. It also refuses a competing velocity publisher, so stop the vendor
APP/teleop service before enabling formation control.

## Fleet check

On a ROS2 computer in the same LAN, use the same domain as the cars. The
verified stock configuration currently uses `ROS_DOMAIN_ID=0`:

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0
bash deploy/check_fleet.sh
```

All four cars must expose unique namespaced topics and this TF tree:

```text
map
├── robot01/odom ── robot01/base_link ── robot01/laser
├── robot02/odom ── robot02/base_link ── robot02/laser
├── robot03/odom ── robot03/base_link ── robot03/laser
└── robot04/odom ── robot04/base_link ── robot04/laser
```

The same occupancy grid bytes and origin must be used on all cars. Each AMCL
instance publishes its own `map -> robotXX/odom`; wheel odometry publishes only
`robotXX/odom -> robotXX/base_link`. There must be exactly one publisher for
each edge.
