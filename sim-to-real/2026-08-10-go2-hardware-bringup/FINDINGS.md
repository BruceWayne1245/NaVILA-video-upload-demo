# Sim-to-real kickoff: Go2 hardware bring-up (2026-08-10)

First session moving from pure Isaac Sim evaluation toward testing on the
physical Unitree Go2. No robot motion was commanded from this session --
everything below is read-only diagnostics (DDS discovery, SSH into the
companion computer, code inspection) plus one architecture decision.

## What the sim currently uses for low-level locomotion

Confirmed by reading the actual config, not assumed: the low-level gait
controller used throughout all prior Isaac Sim evaluation runs is **NaVILA-Bench's
own RL-trained policy**, not a Unitree-provided controller.

- Checkpoint: `NaVILA-Bench/logs/rsl_rl/go2_vision/2024-09-25_23-22-02/model_26499.pt`
  (rsl_rl/PPO, `experiment_name=go2_vision`, ships with the `yang-zj1026/VLN-CE-Isaac`
  fork this project is built on).
- Observations: `base_ang_vel`, `base_rpy`, `joint_pos_rel`, `joint_vel_rel`,
  `last_action`, `velocity_commands`, plus a `height_map` term from a specific
  32-channel LiDAR raycaster geometry (`go2_matterport_vision_cfg.py`'s
  `lidar_sensor`) -- the policy was trained against this exact ray geometry and
  is known to fail (early falls) if that geometry changes.
- Control: joint-position PD, `stiffness=40.0`, `damping=1.0`, `action_scale=0.5`,
  50 Hz (`decimation=4` at `sim.dt=0.005`).
- This is a completely separate thing from Unitree's own onboard "sport mode"
  walking controller.

## Decision: real-robot low-level control path

For the first physical integration, decided to use **Unitree's official
sport-mode controller** (`unitree_sdk2py`'s `SportClient`/velocity commands)
rather than porting `model_26499.pt` to the real robot. Rationale: no
observation/action bridge exists yet for the sim-trained policy on real
hardware (would need a real substitute for the height-map LiDAR term, correct
joint ordering, etc. -- real engineering work, not started), whereas sport-mode
has ready-made SDK examples and gets a physical loop closed fastest. This means
early real-robot runs will **not** be using the same locomotion dynamics that
were validated in simulation -- that gap stays open until/unless we port the
trained policy later.

Separately: user has a **Livox Mid-360 LiDAR** on hand, planned to be mounted on
the physical Go2 later as the real-world replacement for the sim's
`route_memory_lidar` raycaster (local map / anchor maintenance). Not yet
mounted; USB/mounting work not started.

## Hardware inventory (confirmed via live diagnostics)

- **Go2 EDU variant**, confirmed via SSH to the companion computer's
  `/etc/nv_tegra_release` (`tegra234` = Jetson Orin family) and the device-tree
  filename referencing `tegra234-p3767-...` -- Jetson Orin NX, JetPack 5.1.1
  (L4T R35.3.1), 16 GB RAM, Ubuntu 20.04.
- Network: two Ethernet ports on the robot body -- front port is for the RGB
  camera, rear port is the SDK/dev connection (what we're using). Two hosts on
  `192.168.123.0/24`: `.161` (motion-control board, no open TCP ports, DDS-only
  by design) and `.18` (Jetson companion computer, SSH+HTTP open, default
  creds `unitree`/`123` still work).
- **Jetson system clock is unsynced** (`date` returns 1970-01-01, no RTC
  battery / no NTP) -- fix before relying on any timestamped logging from that
  board.
- No external USB devices currently attached (`lsusb` clean) -- Mid-360 not
  mounted yet. No `/dev/video*` V4L2 node on the Jetson; front camera is not
  exposed as a local V4L2 device there (likely reached via Unitree's own DDS
  image topic instead, unconfirmed).

## Pre-existing SLAM/VIO environment found on the Jetson (not ours, not used)

`/unitree/module/` on the companion computer has two environments, both dated
Aug-Nov 2023 (long before this project's 2026 timeline, likely vendor/previous-team
setup, not this project's):
- `graph_pid_ws/0_unitree_slam.sh` -> `ros2 run QT_Server UnitreeSlam`
  (Unitree's own factory SLAM/mapping service).
- `Odometer_service/src/rpg_svo_pro_open` -- ETH Zurich RPG's SVO Pro visual-inertial
  odometry, ROS1/catkin.

**Decision: leave this alone for now**, proceed with the sport-mode plan above.
Revisit only if/when it looks worth salvaging.

## Open blocker: robot's DDS bus is not reachable from an external PC

Set up `unitree_sdk2_python` on the workstation (new conda env `unitree-rl`,
Python 3.8 -- cyclonedds' Python bindings don't support Python 3.13, which is
what the base conda env runs; had to build cyclonedds' C library from source
too since no prebuilt wheel exists without it). Confirmed DDS/multicast
plumbing itself works (discovered the Jetson's own `ros2 daemon`, which turned
out to be a red herring -- just the daemon auto-spawned by a `ros2 topic list`
someone ran locally, not a Unitree bridge).

**But: zero DDS traffic of any kind was ever observed from `192.168.123.161`
(the motion-control board)**, confirmed at multiple levels:
- `unitree_sdk2py` subscription to `rt/lowstate`: 0 messages over repeated
  20s+ windows.
- CycloneDDS builtin participant/publication discovery: 0 publications from
  `.161` on domain 0 or domain 1.
- Raw UDP multicast socket bound directly to `239.255.0.1:7400` (bypassing
  CycloneDDS entirely): 0 packets from `.161` across a 12s window, vs. 2
  packets from `.18` in the same window.

This is while the robot is fully operational via the physical remote (stands,
walks normally) -- so the remote-control path is confirmed independent of the
SDK's Ethernet/DDS path.

**Ruled out:**
- Wrong network interface, wrong domain ID (tried 0 and 1)
- Cable routed through an expansion dock (confirmed: cable is in the robot
  body's own rear port, not a dock)
- Non-EDU limitation (confirmed EDU, which official docs say is required for
  CycloneDDS to work "out of the box")
- Workstation IP scheme (192.168.123.222 matches officially-documented valid
  addresses)

**Still open / next step:** checking the Unitree companion app for a
developer-mode/SDK-enable toggle and the robot's exact firmware version.
Live hypothesis worth checking once we have the firmware version: some Unitree
SDK2 documentation snippets suggest newer firmware may route external
low-level state reads through **WebRTC** instead of raw DDS in some
configurations -- if so, `unitree_sdk2_python`'s raw-DDS approach may be the
wrong tool entirely for this unit, and a WebRTC-based client
(`go2_webrtc_connect`-style) would be needed instead.

## Environment reference

- New conda env: `unitree-rl` (Python 3.8) -- has `cyclonedds==0.10.2` and
  `unitree_sdk2py` (editable install of `/home/teambruce/unitree_sdk2_python`)
  installed. cyclonedds C library was built from source under
  `/tmp/.../scratchpad/cyclonedds` (a session scratch dir, not persistent --
  if `LD_LIBRARY_PATH`/`CYCLONEDDS_HOME` errors show up next session, rebuild
  it or install `libcyclonedds-dev` system-wide instead).
- SSH access to the companion computer: `ssh unitree@192.168.123.18`, password
  `123` (still the factory default on this unit).
