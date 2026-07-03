import os

from omni.isaac.lab.managers import ObservationGroupCfg as ObsGroup
from omni.isaac.lab.managers import ObservationTermCfg as ObsTerm
from omni.isaac.lab.managers import SceneEntityCfg
from omni.isaac.lab.utils import configclass
from omni.isaac.lab.utils.noise import AdditiveUniformNoiseCfg as Unoise
from omni.isaac.lab.sensors import CameraCfg, ContactSensorCfg, RayCasterCfg, patterns
from omni.isaac.lab.sensors.ray_caster import RayCasterCameraCfg, patterns
import omni.isaac.lab.sim as sim_utils

import omni.isaac.vlnce.vlnce.mdp as mdp

from .go2_matterport_base_cfg import Go2MatterportBaseCfg, TerrainSceneCfg, Go2RoughPPORunnerCfg


@configclass
class Go2VisionRoughPPORunnerCfg(Go2RoughPPORunnerCfg):
    experiment_name = "go2_vision"


@configclass
class ObservationsCfg:
    """Observation specifications for the MDP."""

    @configclass
    class PolicyCfg(ObsGroup):
        """Observations for policy group."""

        # observation terms (order preserved)
        # base_lin_vel = ObsTerm(func=mdp.base_lin_vel, noise=Unoise(n_min=-0.1, n_max=0.1))
        base_ang_vel = ObsTerm(func=mdp.base_ang_vel, noise=Unoise(n_min=-0.2, n_max=0.2))
        base_rpy = ObsTerm(func=mdp.base_rpy, noise=Unoise(n_min=-0.1, n_max=0.1))
        
        velocity_commands = ObsTerm(func=mdp.generated_commands, params={"command_name": "base_velocity"})
        joint_pos = ObsTerm(func=mdp.joint_pos_rel, noise=Unoise(n_min=-0.01, n_max=0.01))
        joint_vel = ObsTerm(func=mdp.joint_vel_rel, noise=Unoise(n_min=-1.5, n_max=1.5))
        actions = ObsTerm(func=mdp.last_action)

        height_map = ObsTerm(
            func=mdp.height_map_lidar,
            params={"sensor_cfg": SceneEntityCfg("lidar_sensor"), "offset": 0.0},
            clip=(-10.0, 10.0),
            noise=Unoise(n_min=-0.02, n_max=0.02),
        )

        def __post_init__(self):
            self.enable_corruption = False
            self.concatenate_terms = True

    
    @configclass
    class ProprioCfg(ObsGroup):
        """Observations for proprioceptive group."""

        # observation terms
        base_ang_vel = ObsTerm(func=mdp.base_ang_vel, noise=Unoise(n_min=-0.2, n_max=0.2))
        base_rpy = ObsTerm(func=mdp.base_rpy, noise=Unoise(n_min=-0.1, n_max=0.1))
        
        velocity_commands = ObsTerm(func=mdp.generated_commands, params={"command_name": "base_velocity"})
        joint_pos = ObsTerm(func=mdp.joint_pos_rel, noise=Unoise(n_min=-0.01, n_max=0.01))
        joint_vel = ObsTerm(func=mdp.joint_vel_rel, noise=Unoise(n_min=-1.5, n_max=1.5))
        actions = ObsTerm(func=mdp.last_action)


        def __post_init__(self):
            self.enable_corruption = False
            self.concatenate_terms = True
    
    @configclass
    class CriticObsCfg(ObsGroup):
        # observation terms (order preserved)
        base_lin_vel = ObsTerm(func=mdp.base_lin_vel, noise=Unoise(n_min=-0.1, n_max=0.1))
        base_ang_vel = ObsTerm(func=mdp.base_ang_vel, noise=Unoise(n_min=-0.2, n_max=0.2))
        base_rpy = ObsTerm(func=mdp.base_rpy, noise=Unoise(n_min=-0.1, n_max=0.1))
        
        velocity_commands = ObsTerm(func=mdp.generated_commands, params={"command_name": "base_velocity"})
        joint_pos = ObsTerm(func=mdp.joint_pos_rel, noise=Unoise(n_min=-0.01, n_max=0.01))
        joint_vel = ObsTerm(func=mdp.joint_vel_rel, noise=Unoise(n_min=-1.5, n_max=1.5))
        actions = ObsTerm(func=mdp.last_action)
        height_scan = ObsTerm(
            func=mdp.height_scan,
            params={"sensor_cfg": SceneEntityCfg("height_scanner")},
            clip=(-1.0, 1.0),
        )

        def __post_init__(self):
            self.enable_corruption = False
            self.concatenate_terms = True


    @configclass
    class CameraObsCfg(ObsGroup):
        """Observations for camera group."""

        # observation terms (order preserved)
        # depth_measurement = ObsTerm(
        #     func=mdp.process_depth_image,
        #     params={"sensor_cfg": SceneEntityCfg("lidar_sensor"), "data_type": "distance_to_image_plane"},
        # )
        rgb_measurement = ObsTerm(
            func=mdp.isaac_camera_data,
            params={"sensor_cfg": SceneEntityCfg("rgbd_camera"), "data_type": "rgb"},
        )

        def __post_init__(self):
            self.enable_corruption = False
            self.concatenate_terms = True
    
    @configclass
    class VizCameraObsCfg(ObsGroup):
        """Observations for visualization camera group."""
        rgb_measurement = ObsTerm(
            func=mdp.isaac_camera_data,
            params={"sensor_cfg": SceneEntityCfg("viz_rgb_camera"), "data_type": "rgb"},
        )

        def __post_init__(self):
            self.enable_corruption = False
            self.concatenate_terms = True
            
    @configclass
    class DepthObsCfg(ObsGroup):
        """Observations for visualization camera group."""
        depth_measurement = ObsTerm(
            func=mdp.process_depth_image,
            params={"sensor_cfg": SceneEntityCfg("rgbd_camera"), "data_type": "distance_to_image_plane"},
        )

        def __post_init__(self):
            self.enable_corruption = False
            self.concatenate_terms = True

    @configclass
    class RearCameraObsCfg(ObsGroup):
        """RGB from rear-facing camera (body -x direction) for return-phase relocalization."""
        rgb_measurement = ObsTerm(
            func=mdp.isaac_camera_data,
            params={"sensor_cfg": SceneEntityCfg("rear_rgbd_camera"), "data_type": "rgb"},
        )

        def __post_init__(self):
            self.enable_corruption = False
            self.concatenate_terms = True

    @configclass
    class RearDepthObsCfg(ObsGroup):
        """Depth from rear-facing camera for return-phase relocalization."""
        depth_measurement = ObsTerm(
            func=mdp.process_depth_image,
            params={"sensor_cfg": SceneEntityCfg("rear_rgbd_camera"), "data_type": "distance_to_image_plane"},
        )

        def __post_init__(self):
            self.enable_corruption = False
            self.concatenate_terms = True

    @configclass
    class RouteMemoryObsCfg(ObsGroup):
        """Non-concatenated local geometry for route-memory anchor matching."""
        height_map = ObsTerm(
            func=mdp.height_map_lidar,
            params={"sensor_cfg": SceneEntityCfg("lidar_sensor"), "offset": 0.0},
            clip=(-10.0, 10.0),
        )
        height_scan = ObsTerm(
            func=mdp.height_scan,
            params={"sensor_cfg": SceneEntityCfg("height_scanner")},
            clip=(-1.0, 1.0),
        )

        def __post_init__(self):
            self.enable_corruption = False
            self.concatenate_terms = False

    # observation groups
    policy: PolicyCfg = PolicyCfg()
    proprio: ProprioCfg = ProprioCfg()
    critic: CriticObsCfg = CriticObsCfg()
    camera_obs: CameraObsCfg = CameraObsCfg()
    viz_camera_obs: VizCameraObsCfg = VizCameraObsCfg()
    depth_obs: DepthObsCfg = DepthObsCfg()
    rear_camera_obs: RearCameraObsCfg = RearCameraObsCfg()
    rear_depth_obs: RearDepthObsCfg = RearDepthObsCfg()
    route_memory_obs: RouteMemoryObsCfg = RouteMemoryObsCfg()


##
# Scene configuration
##
class Go2VisionSceneCfg(TerrainSceneCfg):
    # Rear-facing camera (body -x direction) for return-phase relocalization.
    # rot=(-0.5, 0.5, 0.5, -0.5) [w,x,y,z]: camera +Z maps to body -x.
    rear_rgbd_camera = CameraCfg(
        prim_path="{ENV_REGEX_NS}/Robot/base/rear_rgbd_camera",
        offset=CameraCfg.OffsetCfg(pos=(-0.1, 0.0, 0.5), rot=(-0.5, 0.5, 0.5, -0.5)),
        spawn=sim_utils.PinholeCameraCfg(horizontal_aperture=54.0),
        width=512,
        height=512,
        data_types=["rgb", "distance_to_image_plane"],
    )
    lidar_sensor = RayCasterCfg(
        prim_path="{ENV_REGEX_NS}/Robot/Head_lower",
        # offset=RayCasterCfg.OffsetCfg(pos=(0.28945, 0.0, -0.046), rot=(0., -0.991,0.0,-0.131)),
        offset=RayCasterCfg.OffsetCfg(pos=(0.0, 0.0, -0.0), rot=(0., -0.991,0.0,-0.131)),
        attach_yaw_only=False,
        # 2026-07-03: DO NOT change vertical_fov_range/horizontal_res/
        # max_distance on THIS sensor. It looked like a pure room-mapping
        # sensor but ObservationsCfg.PolicyCfg.height_map (below in this file)
        # also reads it as the locomotion policy's terrain/height-map input,
        # and that policy (checkpoints/.../model_26499.pt) was trained against
        # this exact ray geometry. Narrowing vertical_fov_range to improve
        # route-memory's obstacle-band coverage was tried and reverted: it
        # fed the policy out-of-distribution height-map values and caused
        # reproducible early falls (robot height collapsing from ~0.3 m to
        # ~0.07-0.10 m within the first ~10 steps) on ep187/680/994, confirmed
        # against a same-day baseline run where all three started and stayed
        # at a normal ~0.3 m standing height under this unchanged config. Any
        # future improvement to route-memory's LiDAR coverage needs its own
        # separate RayCasterCfg, not a change to this one.
        pattern_cfg=patterns.LidarPatternCfg(
            channels=32, vertical_fov_range=(0.0, 90.0), horizontal_fov_range=(-180, 180.0), horizontal_res=4.0
        ),
        debug_vis=False, # set to True to visualize the lidar rays
        mesh_prim_paths=["/World/matterport"],
    )
    # 2026-07-03: dedicated sensor for route-memory/LiDAR anchor matching,
    # separate from `lidar_sensor` above (which is load-bearing for the
    # locomotion policy's height-map observation and must not be
    # reconfigured -- see the comment on `lidar_sensor`). Uses an identity
    # offset rotation, unlike `lidar_sensor`'s rot=(0,-0.991,0,-0.131): with
    # IsaacLab's lidar_pattern ray-generation convention (local ray direction
    # = (cos(v)cos(h), cos(v)sin(h), sin(v)), v=elevation, h=azimuth --
    # see patterns.py), elevation 0 is already local-frame-horizontal, so a
    # symmetric vertical_fov_range needs no compensating rotation to cover a
    # genuinely useful floor-to-ceiling obstacle band. Validate with the same
    # per-channel diagnostic used to debug `lidar_sensor` before trusting this
    # blindly (attach_yaw_only/offset assumptions on a real prim can still
    # surprise you -- see 2026-07-03 memory notes on that debugging episode).
    route_memory_lidar = RayCasterCfg(
        prim_path="{ENV_REGEX_NS}/Robot/Head_lower",
        offset=RayCasterCfg.OffsetCfg(pos=(0.0, 0.0, 0.0), rot=(1.0, 0.0, 0.0, 0.0)),
        attach_yaw_only=False,
        max_distance=20.0,
        pattern_cfg=patterns.LidarPatternCfg(
            channels=32, vertical_fov_range=(-15.0, 15.0), horizontal_fov_range=(-180, 180.0), horizontal_res=1.0
        ),
        debug_vis=False,
        mesh_prim_paths=["/World/matterport"],
    )

##
# Environment configuration
##

@configclass
class Go2MatterportVisionCfg(Go2MatterportBaseCfg):
    """Configuration for the locomotion velocity-tracking environment."""

    # Basic settings
    observations: ObservationsCfg = ObservationsCfg()
    scene: Go2VisionSceneCfg = Go2VisionSceneCfg(num_envs=1, env_spacing=2.5)

    def __post_init__(self):
        """Post initialization."""
        super().__post_init__()
        # general settings
        self.scene.lidar_sensor.update_period = 4*self.sim.dt
        self.scene.route_memory_lidar.update_period = 4*self.sim.dt
        self.scene.height_scanner.pattern_cfg.size = [3.0, 2.0]
