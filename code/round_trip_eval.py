# Copyright (c) 2022-2024, The lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Script to play a checkpoint if an RL agent from RSL-RL."""

"""Launch Isaac Sim Simulator first."""

import argparse
import gymnasium as gym
import os
import json
import math
import torch
import numpy as np
import imageio
from PIL import Image
import cv2
import time
import base64
import io
import socket
import json

from omni.isaac.lab.app import AppLauncher

# local imports
import cli_args  # isort: skip
from instruction_rewriter import InstructionRewriteError, InstructionRewriter
from hint_action_arbiter import HintActionArbiter, HintActionArbiterConfig
from route_memory_agent import AnchorRelocalization, RelativeStartProgress, RouteMemoryAgent
from stop_gate import GateDecision, ReturnStopGate
from topdown_route_map import capture_occupancy_floor_slice, save_topdown_route_map
from relocalization import (
    backproject_points as _backproject_points,
    camera_point_to_body as _camera_point_to_body,
    create_feature_detector as _create_feature_detector,
    descriptor_camera_pose as _descriptor_camera_pose,
    descriptor_camera_to_body as _descriptor_camera_to_body,
    descriptor_depth as _descriptor_depth,
    descriptor_intrinsics as _descriptor_intrinsics,
    descriptor_rgb_gray as _descriptor_rgb_gray,
    feature_depth_anchor_relocalization,
    feature_matcher_config as _feature_matcher_config,
    gt_covisibility,
    local_map_anchor_relocalization,
    loftr_match_points as _loftr_match_points,
    matched_uv_points as _matched_uv_points,
    quat_wxyz_to_matrix as _quat_wxyz_to_matrix,
    ransac_rigid_transform as _ransac_rigid_transform,
    rigid_transform_3d as _rigid_transform_3d,
    _append_covisibility_record,
    _diagnostic_inc,
)

# isaaclab argparse arguments
parser = argparse.ArgumentParser(description="Run a single-episode outbound-confirm-return VLN benchmark.")
parser.add_argument(
    "--disable_fabric", action="store_true", default=False, help="Disable fabric and use USD I/O operations."
)
parser.add_argument("--num_envs", type=int, default=None, help="Number of environments to simulate.")
parser.add_argument("--task", type=str, default=None, help="Name of the task.")
parser.add_argument("--seed", type=int, default=None, help="Seed used for the environment")

parser.add_argument("--history_length", default=0, type=int, help="Length of history buffer.")
parser.add_argument("--use_cnn", action="store_true", default=None, help="Name of the run folder to resume from.")
parser.add_argument("--use_rnn", action="store_true", default=False, help="Use RNN in the actor-critic model.")
parser.add_argument("--visualize_path", action="store_true", default=False, help="Visualize the path in the simulator.")

# navila argparse arguments
parser.add_argument("--device", type=str, default="cuda")
parser.add_argument("--vlm_host", type=str, default="localhost")
parser.add_argument("--vlm_port", type=int, default=54321)
parser.add_argument(
    "--round_trip_mode",
    type=str,
    default="static_long_instruction",
    choices=("static_long_instruction", "phase_prompt"),
    help=(
        "static_long_instruction: always query NaVILA with the full outbound-confirm-return instruction. "
        "phase_prompt: use phase-specific language prompts while still providing no route-memory hints."
    ),
)
parser.add_argument("--confirm_turn_seconds", type=float, default=6.0)
parser.add_argument(
    "--success_radius",
    type=float,
    default=None,
    help="Success radius for outbound and return. Defaults to episode['goals'][0]['radius'].",
)
parser.add_argument(
    "--return_success_radius",
    type=float,
    default=None,
    help="Deprecated alias for --success_radius.",
)
parser.add_argument("--max_return_seconds", type=float, default=100.0)
parser.add_argument(
    "--instruction_rewriter_provider",
    choices=("legacy", "cache_only", "ollama", "openai_compatible"),
    default="legacy",
    help=(
        "legacy preserves the original abstract return prompt. Other modes use a generated, "
        "explicit reverse instruction. Use cache_only for reproducible benchmark runs."
    ),
)
parser.add_argument("--instruction_rewriter_model", default="reviewed")
parser.add_argument(
    "--instruction_rewriter_cache",
    default=os.path.join(os.path.dirname(__file__), "generated", "reversed_instructions.json"),
)
parser.add_argument("--instruction_llm_endpoint", default=None)
parser.add_argument("--instruction_llm_api_key_env", default="OPENAI_API_KEY")
parser.add_argument("--instruction_llm_timeout", type=float, default=120.0)
parser.add_argument(
    "--return_instruction_override",
    default="",
    help="Human-authored return instruction used instead of the generated return instruction.",
)
parser.add_argument(
    "--return_instruction_file",
    default="",
    help="Path to a UTF-8 text file containing a human-authored return instruction.",
)
parser.add_argument(
    "--oracle_return_pose",
    action="store_true",
    default=False,
    help="At the start of return, place the robot at the expert goal facing the reversed reference path.",
)
parser.add_argument(
    "--oracle_align_return_yaw_to_anchor_segment",
    action="store_true",
    default=False,
    help="At the start of return, keep position fixed but align yaw to the nearest outbound anchor segment reversed.",
)
parser.add_argument(
    "--result_suffix",
    default="",
    help="Optional suffix for the result directory, used to preserve prior runs.",
)
parser.add_argument(
    "--route_memory",
    action="store_true",
    default=False,
    help="Enable return-stage relative-start hints during round-trip evaluation.",
)
parser.add_argument(
    "--route_hint_mode",
    choices=("none", "compact", "verbose"),
    default="compact",
    help="Prompt-hint verbosity for route memory.",
)
parser.add_argument(
    "--route_hint_source",
    choices=("integrated", "isaac", "oracle"),
    default="integrated",
    help="Source for return-stage route hints. 'oracle' injects exact simulator bearing to the next reverse-route anchor.",
)
parser.add_argument("--route_anchor_spacing_m", type=float, default=1.0, help=argparse.SUPPRESS)
parser.add_argument("--route_min_relocalization_confidence", type=float, default=0.35, help=argparse.SUPPRESS)
parser.add_argument(
    "--route_relocalization_backend",
    choices=("none", "oracle_anchor", "feature_depth", "sift_depth", "loftr_depth", "lidar_local_map"),
    default="none",
    help=argparse.SUPPRESS,
)
parser.add_argument("--route_relocalization_window", type=int, default=0, help=argparse.SUPPRESS)
parser.add_argument("--route_relocalization_interval_updates", type=int, default=25, help=argparse.SUPPRESS)
parser.add_argument("--route_fallback", action="store_true", default=False, help=argparse.SUPPRESS)
parser.add_argument(
    "--vio_bridge",
    action="store_true",
    default=True,
    help="Enable VIO bridge: suppress visual particle-filter updates in the corridor dead zone "
         "(filter std > vio_bridge_std_m) away from path feature anchors (corners/doorways).",
)
parser.add_argument("--no_vio_bridge", action="store_false", dest="vio_bridge", help=argparse.SUPPRESS)
parser.add_argument("--vio_bridge_std_m", type=float, default=2.5, help=argparse.SUPPRESS)
parser.add_argument("--vio_bridge_feature_radius_m", type=float, default=2.0, help=argparse.SUPPRESS)
parser.add_argument(
    "--stop_gate",
    action="store_true",
    default=False,
    help=(
        "Enable the return-phase stop-gate arbiter.  Vetoes premature stops "
        "(d > r_out, high conf) and forces terminal when robot stays within "
        "r_in for confirm_steps consecutive VLM steps.  Off by default."
    ),
)
parser.add_argument("--stop_gate_r_in", type=float, default=3.0, help=argparse.SUPPRESS)
parser.add_argument("--stop_gate_r_out", type=float, default=3.0, help=argparse.SUPPRESS)
parser.add_argument("--stop_gate_confirm_steps", type=int, default=3, help=argparse.SUPPRESS)
parser.add_argument("--stop_gate_min_confidence", type=float, default=0.5, help=argparse.SUPPRESS)
parser.add_argument(
    "--hint_action_arbiter",
    action="store_true",
    default=False,
    help=(
        "Enable return-phase hint-following action arbitration. If the VLM action clearly conflicts "
        "with the next-anchor route hint and the hinted local path is clear, replace the VLM output "
        "with a matching NaVILA action string."
    ),
)
parser.add_argument("--hint_arbiter_forward_cone_deg", type=float, default=15.0, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_forward_conflict_bearing_deg", type=float, default=30.0, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_turn_step_deg", type=float, default=45.0, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_forward_distance_cm", type=int, default=75, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_max_clear_path_distance_m", type=float, default=1.0, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_robot_radius_m", type=float, default=0.30, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_clearance_margin_m", type=float, default=0.12, help=argparse.SUPPRESS)
parser.add_argument(
    "--hint_arbiter_allow_without_clear_path",
    action="store_true",
    default=False,
    help=argparse.SUPPRESS,
)
parser.add_argument("--route_fallback_window", type=int, default=4, help=argparse.SUPPRESS)
parser.add_argument("--route_fallback_duration_seconds", type=float, default=0.5, help=argparse.SUPPRESS)
parser.add_argument(
    "--topdown_route_map",
    action="store_true",
    default=False,
    help="Save a USD floor-slice occupancy map with outbound/return trajectories and route anchors.",
)
parser.add_argument("--topdown_map_resolution", type=float, default=0.05, help=argparse.SUPPRESS)
parser.add_argument("--topdown_map_padding_m", type=float, default=3.0, help=argparse.SUPPRESS)
parser.add_argument("--topdown_map_z_min", type=float, default=0.08, help=argparse.SUPPRESS)
parser.add_argument("--topdown_map_z_max", type=float, default=2.2, help=argparse.SUPPRESS)
parser.add_argument("--topdown_map_max_size_px", type=int, default=2400, help=argparse.SUPPRESS)


# r2r argparse arguments
parser.add_argument("--episode_idx", type=int, default=0)

# RSL-RL cli arguments
cli_args.add_rsl_rl_args(parser)
# append AppLauncher cli args
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()


# launch omniverse app
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

from rsl_rl.runners import OnPolicyRunner

import omni.isaac.lab_tasks  # noqa: F401
from omni.isaac.lab_tasks.utils import get_checkpoint_path, parse_env_cfg
from omni.isaac.lab.utils.io import load_yaml
import omni.isaac.lab.utils.math as math_utils
from omni.isaac.lab.markers import VisualizationMarkers, VisualizationMarkersCfg
from omni.isaac.lab.utils import update_class_from_dict
from omni.isaac.lab_tasks.utils.wrappers.rsl_rl import (
    RslRlOnPolicyRunnerCfg,
    RslRlVecEnvWrapper,
)
import omni.isaac.lab.sim as sim_utils

from omni.isaac.vlnce.config import *
from omni.isaac.vlnce.utils import ASSETS_DIR, RslRlVecEnvHistoryWrapper, VLNEnvWrapper
from omni.isaac.vlnce.utils.eval_utils import (
    get_vel_command, 
    read_episodes, 
    add_instruction_on_img,
    InstructionData, 
)
from omni.isaac.vlnce.utils.measures import PathLength, DistanceToGoal, Success, SPL, OracleNavigationError, OracleSuccess, MeasureManager


def quat2eulers(q0, q1, q2, q3):
    """
    Calculates the roll, pitch, and yaw angles from a quaternion.

    Args:
        q0: The scalar component of the quaternion.
        q1: The x-component of the quaternion.
        q2: The y-component of the quaternion.
        q3: The z-component of the quaternion.

    Returns:
        A tuple containing the roll, pitch, and yaw angles in radians.
    """

    roll = math.atan2(2 * (q2 * q3 + q0 * q1), q0**2 - q1**2 - q2**2 + q3**2)
    pitch = math.asin(2 * (q1 * q3 - q0 * q2))
    yaw = math.atan2(2 * (q1 * q2 + q0 * q3), q0**2 + q1**2 - q2**2 - q3**2)

    return roll, pitch, yaw


def define_markers() -> VisualizationMarkers:
    """Define path markers with various different shapes."""
    marker_cfg = VisualizationMarkersCfg(
        prim_path="/Visuals/pathMarkers",
        markers={
            "waypoint": sim_utils.SphereCfg(
                radius=0.1,
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.0, 1.0, 0.0)),
            ),
        },
    )
    return VisualizationMarkers(marker_cfg)


def reset_start_pos_rot(env_cfg, args_cli, episode):
    scene_id = os.path.splitext(os.path.basename(episode["scene_id"]))[0]
    env_cfg.scene.terrain.obj_filepath = os.path.join(ASSETS_DIR, f"matterport_usd/{scene_id}/{scene_id}.usd")
    
    start_pos, start_rot, goal_pos = episode["start_position"], episode["start_rotation"], episode["reference_path"][-1]
    env_cfg.scene.robot.init_state.rot = start_rot

    if "go2" in args_cli.task:
        env_cfg.scene.robot.init_state.pos = (start_pos[0], start_pos[1], start_pos[2]+0.4)
    elif "h1" in args_cli.task:
        env_cfg.scene.robot.init_state.pos = (start_pos[0], start_pos[1], start_pos[2]+1.0)
    else:
        env_cfg.scene.robot.init_state.pos = (start_pos[0], start_pos[1], start_pos[2]+0.5)

    env_cfg.scene.terrain.origins = env_cfg.scene.robot.init_state.pos

    env_cfg.scene.disk_1.init_state.pos = ([start_pos[0], start_pos[1], start_pos[2] + 2.5])
    env_cfg.scene.disk_2.init_state.pos = ([goal_pos[0], goal_pos[1], goal_pos[2] + 2.5])

    return env_cfg


def add_measurement(env, episode):
    measure_manager = MeasureManager()
    measure_names = ["PathLength", "DistanceToGoal", "Success", "SPL", "OracleNavigationError", "OracleSuccess"]
    for measure_name in measure_names:
        measure = eval(measure_name)(env, episode, measure_manager)
        measure_manager.register_measure(measure)
    
    env.measure_manager = measure_manager
    return


def sample_images_and_send_to_vlm(image_list, vlm_host, vlm_port, query):
    if len(image_list) == 0:
        print("Did not receive any images.")
        return None
    elif len(image_list) < 8:
        print("Not enough images received, padding.")
        image_list = image_list.copy()
        # append image value=0, in front of the existing images, image size equal to the last one
        for _ in range(8 - len(image_list)):
            image_list.insert(0, Image.new('RGB', image_list[-1].size, (0, 0, 0)))
    else:
        image_list = image_list.copy()
        
    num_images = len(image_list)
    indices = [int(i * (num_images - 1) / 7) for i in range(7)]
    sampled_images = [image_list[i] for i in indices]
    sampled_images.append(image_list[-1])

    # save sampled images
    # time_stamp = time.strftime("%Y%m%d-%H%M%S")
    # if not os.path.exists("test_images"):
    #     os.makedirs("test_images")
    # for i, img in enumerate(sampled_images):
    #     # convert to PIL Image
    #     img = Image.fromarray(img)
    #     img.save(os.path.join("test_images", f"{time_stamp}_image_{i}.jpg"))

    # Convert images to base64 for transmission
    encoded_images = []
    for image in sampled_images:
        # Ensure PIL Image for JPEG encoding
        if isinstance(image, np.ndarray):
            array_image = image
            if array_image.dtype != np.uint8:
                # Convert to uint8. If values are 0-1, scale; otherwise clip to 0-255
                if array_image.max() <= 1.0:
                    array_image = (array_image * 255.0).clip(0, 255).astype(np.uint8)
                else:
                    array_image = array_image.clip(0, 255).astype(np.uint8)
            pil_image = Image.fromarray(array_image)
        elif isinstance(image, Image.Image):
            pil_image = image
        else:
            # Fallback: try to construct a PIL image from whatever object is provided
            pil_image = Image.fromarray(np.array(image, dtype=np.uint8))

        np_image = np.array(pil_image)
        np_bgr = cv2.cvtColor(np_image, cv2.COLOR_RGB2BGR)
        _, buf = cv2.imencode(".jpg", np_bgr)
        encoded_images.append(base64.b64encode(buf.tobytes()).decode())

    # Prepare request data
    request_data = {
        'images': encoded_images,
        'query': query
    }

    # Send to VLM server
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((vlm_host, vlm_port))
        
        # Send data
        data_bytes = json.dumps(request_data).encode()
        s.sendall(len(data_bytes).to_bytes(8, 'big'))
        s.sendall(data_bytes)
        
        # Receive response
        size_data = s.recv(8)
        size = int.from_bytes(size_data, 'big')
        
        response_data = b''
        while len(response_data) < size:
            packet = s.recv(4096)
            if not packet:
                break
            response_data += packet
            
        response = json.loads(response_data.decode())
        return response


def get_robot_position(env):
    return env.unwrapped.scene["robot"].data.root_pos_w[0].detach().cpu().numpy().copy()


def get_robot_pose(env):
    root_pose = env.unwrapped.scene["robot"].data.root_state_w[0, :7]
    return root_pose.detach().cpu().numpy().copy()


def get_oracle_return_pose(env, episode):
    reference_path = np.asarray(episode["reference_path"], dtype=np.float32)
    if len(reference_path) < 2:
        raise RuntimeError("Oracle return pose requires at least two reference path points.")

    current_pose = get_robot_pose(env)
    goal = reference_path[-1]
    previous = reference_path[-2]
    reverse_direction = previous[:2] - goal[:2]
    yaw = math.atan2(float(reverse_direction[1]), float(reverse_direction[0]))

    pose = current_pose.copy()
    pose[:2] = goal[:2]
    pose[2] = goal[2] + max(float(current_pose[2] - goal[2]), 0.25)
    pose[3:] = np.array(
        [math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)],
        dtype=np.float32,
    )
    return pose


def oracle_anchor_segment_return_yaw(env, route_agent):
    route_anchors = [
        anchor for anchor in route_agent.anchors
        if anchor.metadata.get("world_pose") is not None
    ]
    if len(route_anchors) < 2:
        return None

    pose_xy = np.asarray(get_robot_position(env)[:2], dtype=np.float32)
    best_distance2 = None
    best_segment = None
    for a, b in zip(route_anchors[:-1], route_anchors[1:]):
        a_xy = np.asarray(a.metadata["world_pose"][:2], dtype=np.float32)
        b_xy = np.asarray(b.metadata["world_pose"][:2], dtype=np.float32)
        segment = b_xy - a_xy
        denom = float(np.dot(segment, segment))
        if denom <= 1e-9:
            continue
        t = float(np.clip(np.dot(pose_xy - a_xy, segment) / denom, 0.0, 1.0))
        projected = a_xy + t * segment
        distance2 = float(np.dot(pose_xy - projected, pose_xy - projected))
        if best_distance2 is None or distance2 < best_distance2:
            best_distance2 = distance2
            best_segment = (a, b)

    if best_segment is None:
        return None
    a, b = best_segment
    a_xy = np.asarray(a.metadata["world_pose"][:2], dtype=np.float32)
    b_xy = np.asarray(b.metadata["world_pose"][:2], dtype=np.float32)
    # Outbound segment direction is A_low -> A_high. Return direction is reversed.
    reverse_direction = a_xy - b_xy
    if float(np.dot(reverse_direction, reverse_direction)) <= 1e-9:
        return None
    yaw = math.atan2(float(reverse_direction[1]), float(reverse_direction[0]))
    return {
        "yaw_rad": float(yaw),
        "yaw_deg": float(math.degrees(yaw)),
        "segment_anchor_indices": [int(a.index), int(b.index)],
        "distance_to_segment_m": float(math.sqrt(max(0.0, best_distance2 or 0.0))),
    }


def align_return_yaw_to_anchor_segment(env, route_agent):
    alignment = oracle_anchor_segment_return_yaw(env, route_agent)
    if alignment is None:
        return None
    pose = get_robot_pose(env)
    before_yaw = pose_yaw(pose)
    yaw = alignment["yaw_rad"]
    aligned_pose = pose.copy()
    aligned_pose[3:] = np.asarray(
        [math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)],
        dtype=np.float32,
    )
    reset_navigation_memory(env, aligned_pose)
    after_pose = get_robot_pose(env)
    alignment.update({
        "before_yaw_rad": float(before_yaw),
        "before_yaw_deg": float(math.degrees(before_yaw)),
        "after_yaw_rad": float(pose_yaw(after_pose)),
        "after_yaw_deg": float(math.degrees(pose_yaw(after_pose))),
        "yaw_delta_rad": float(signed_angle_diff(yaw, before_yaw)),
        "yaw_delta_deg": float(math.degrees(signed_angle_diff(yaw, before_yaw))),
        "pose_after_alignment": [float(x) for x in after_pose],
    })
    return alignment


def pose_yaw(pose):
    quat = pose[3:]
    _, _, yaw = quat2eulers(float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3]))
    return yaw


def signed_angle_diff(a, b):
    return math.atan2(math.sin(a - b), math.cos(a - b))


def pose_delta_body(previous_pose, current_pose):
    previous_pose = np.asarray(previous_pose, dtype=np.float32)
    current_pose = np.asarray(current_pose, dtype=np.float32)
    previous_yaw = pose_yaw(previous_pose)
    current_yaw = pose_yaw(current_pose)
    delta_world = current_pose[:2] - previous_pose[:2]
    cos_yaw = math.cos(previous_yaw)
    sin_yaw = math.sin(previous_yaw)
    return [
        float(cos_yaw * delta_world[0] + sin_yaw * delta_world[1]),
        float(-sin_yaw * delta_world[0] + cos_yaw * delta_world[1]),
        float(signed_angle_diff(current_yaw, previous_yaw)),
    ]


def isaac_relative_start_progress(env, start_pos):
    pose = get_robot_pose(env)
    position = get_robot_position(env)
    yaw = pose_yaw(pose)
    dx_world = float(start_pos[0] - position[0])
    dy_world = float(start_pos[1] - position[1])
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    target_dx = float(cos_yaw * dx_world + sin_yaw * dy_world)
    target_dy = float(-sin_yaw * dx_world + cos_yaw * dy_world)
    distance = float(math.hypot(target_dx, target_dy))
    bearing = float(math.degrees(math.atan2(target_dy, target_dx))) if distance > 1e-6 else 0.0
    current_pose_from_start = [
        float(position[0] - start_pos[0]),
        float(position[1] - start_pos[1]),
        float(yaw),
    ]
    return RelativeStartProgress(
        target_dx_m=target_dx,
        target_dy_m=target_dy,
        distance_to_start_m=distance,
        bearing_to_start_deg=bearing,
        current_pose_from_start=current_pose_from_start,
        return_pose_from_return_start=[],
        return_start_pose_from_start=[],
    )


def direct_oracle_start_progress(env, start_pos):
    progress = isaac_relative_start_progress(env, start_pos)
    progress.source = "direct_oracle_start"
    progress.relocalization_backend = "oracle_direct"
    progress.relocalization_confidence = 1.0
    progress.filter_std_m = None
    return progress


def _body_frame_vector_to_world_point(env, start_pos, target_xy):
    pose = get_robot_pose(env)
    position = get_robot_position(env)
    yaw = pose_yaw(pose)
    dx_world = float(target_xy[0] - position[0])
    dy_world = float(target_xy[1] - position[1])
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    target_dx = float(cos_yaw * dx_world + sin_yaw * dy_world)
    target_dy = float(-sin_yaw * dx_world + cos_yaw * dy_world)
    distance = float(math.hypot(target_dx, target_dy))
    bearing = float(math.degrees(math.atan2(target_dy, target_dx))) if distance > 1e-6 else 0.0
    current_pose_from_start = [
        float(position[0] - start_pos[0]),
        float(position[1] - start_pos[1]),
        float(yaw),
    ]
    return target_dx, target_dy, distance, bearing, current_pose_from_start


def _project_current_position_to_oracle_route(env, anchors):
    pose_xy = np.asarray(get_robot_position(env)[:2], dtype=np.float32)
    route_anchors = [
        anchor for anchor in anchors
        if anchor.metadata.get("world_pose") is not None
    ]
    if not route_anchors:
        return None
    if len(route_anchors) == 1:
        return float(route_anchors[0].distance_from_start_m)

    best_distance2 = None
    best_route_s = float(route_anchors[-1].distance_from_start_m)
    for a, b in zip(route_anchors[:-1], route_anchors[1:]):
        a_xy = np.asarray(a.metadata["world_pose"][:2], dtype=np.float32)
        b_xy = np.asarray(b.metadata["world_pose"][:2], dtype=np.float32)
        segment = b_xy - a_xy
        denom = float(np.dot(segment, segment))
        if denom <= 1e-9:
            t = 0.0
        else:
            t = float(np.clip(np.dot(pose_xy - a_xy, segment) / denom, 0.0, 1.0))
        projected = a_xy + t * segment
        distance2 = float(np.dot(pose_xy - projected, pose_xy - projected))
        route_s = float(
            a.distance_from_start_m
            + t * (b.distance_from_start_m - a.distance_from_start_m)
        )
        if best_distance2 is None or distance2 < best_distance2:
            best_distance2 = distance2
            best_route_s = route_s
    return best_route_s


def direct_oracle_route_anchor_progress(env, start_pos, route_agent):
    if route_agent is None or not route_agent.anchors:
        return direct_oracle_start_progress(env, start_pos)

    current_s = _project_current_position_to_oracle_route(env, route_agent.anchors)
    if current_s is None:
        return direct_oracle_start_progress(env, start_pos)

    # Return follows the outbound route in reverse. Use the simulator/global
    # route position to pick an anchor ahead along that reverse route, not the
    # nearest/sideways anchor that can make the VLM spin in place.
    target_lookahead_m = max(
        1.0,
        float(getattr(route_agent, "route_progress_lookahead_m", getattr(route_agent, "anchor_spacing_m", 1.0))),
    )
    target_s = max(0.0, current_s - target_lookahead_m)
    target_anchor = route_agent.target_anchor_for_route_position(
        target_s,
        require_world_pose=True,
    )
    if target_anchor is None:
        return direct_oracle_start_progress(env, start_pos)

    target_xy = np.asarray(target_anchor.metadata["world_pose"][:2], dtype=np.float32)
    target_dx, target_dy, anchor_distance, anchor_bearing, current_pose_from_start = (
        _body_frame_vector_to_world_point(env, start_pos, target_xy)
    )
    anchor_remaining = float(target_anchor.route_remaining_to_start_m)
    return RelativeStartProgress(
        target_dx_m=target_dx,
        target_dy_m=target_dy,
        distance_to_start_m=float(anchor_distance + anchor_remaining),
        bearing_to_start_deg=anchor_bearing,
        current_pose_from_start=current_pose_from_start,
        return_pose_from_return_start=[],
        return_start_pose_from_start=[],
        source="direct_oracle_route_anchor",
        target_anchor_index=int(target_anchor.index),
        anchor_dx_m=target_dx,
        anchor_dy_m=target_dy,
        distance_to_anchor_m=anchor_distance,
        bearing_to_anchor_deg=anchor_bearing,
        anchor_route_remaining_m=anchor_remaining,
        anchor_heading_reliable=True,
        relocalization_confidence=1.0,
        relocalization_backend="oracle_direct_route_anchor",
        filter_std_m=None,
        oracle_route_current_s_m=float(current_s),
        oracle_route_target_s_m=float(target_s),
        oracle_route_lookahead_m=float(target_lookahead_m),
    )


def route_progress_override(source, env, start_pos, route_agent=None):
    if source == "isaac":
        return isaac_relative_start_progress(env, start_pos)
    if source == "oracle":
        return direct_oracle_route_anchor_progress(env, start_pos, route_agent)
    return None


def oracle_anchor_relocalization(env, route_agent):
    current_pose = get_robot_pose(env)
    current_yaw = pose_yaw(current_pose)
    best_anchor = None
    best_distance = None
    best_pose = None
    for anchor in route_agent.anchors:
        world_pose = anchor.metadata.get("world_pose")
        if world_pose is None:
            continue
        anchor_pose = np.asarray(world_pose, dtype=np.float32)
        distance = float(np.linalg.norm(anchor_pose[:2] - current_pose[:2]))
        if best_distance is None or distance < best_distance:
            best_anchor = anchor
            best_distance = distance
            best_pose = anchor_pose
    if best_anchor is None or best_pose is None:
        return None

    dx_world = float(best_pose[0] - current_pose[0])
    dy_world = float(best_pose[1] - current_pose[1])
    cos_yaw = math.cos(current_yaw)
    sin_yaw = math.sin(current_yaw)
    anchor_dx = float(cos_yaw * dx_world + sin_yaw * dy_world)
    anchor_dy = float(-sin_yaw * dx_world + cos_yaw * dy_world)
    anchor_dtheta = float(signed_angle_diff(pose_yaw(best_pose), current_yaw))
    return AnchorRelocalization(
        anchor_index=int(best_anchor.index),
        anchor_dx_m=anchor_dx,
        anchor_dy_m=anchor_dy,
        anchor_dtheta_rad=anchor_dtheta,
        confidence=1.0,
        backend="oracle_anchor",
    )




def summarize_pose_error(pose, reference_pose):
    if pose is None or reference_pose is None:
        return None
    pose = np.asarray(pose, dtype=np.float32)
    reference_pose = np.asarray(reference_pose, dtype=np.float32)
    return {
        "xy_error_m": float(np.linalg.norm(pose[:2] - reference_pose[:2])),
        "z_error_m": float(abs(float(pose[2]) - float(reference_pose[2]))),
        "yaw_error_rad": float(signed_angle_diff(pose_yaw(pose), pose_yaw(reference_pose))),
        "yaw_error_deg": float(math.degrees(signed_angle_diff(pose_yaw(pose), pose_yaw(reference_pose)))),
    }


def get_robot_velocity(env):
    return env.unwrapped.scene["robot"].data.root_vel_w[0].detach().cpu().numpy().copy()


def nearest_path_point(position_xy, path_xy):
    if len(path_xy) == 0:
        return {"index": None, "distance_m": None}
    deltas = path_xy - np.asarray(position_xy, dtype=np.float32)[None, :]
    distances = np.linalg.norm(deltas, axis=1)
    index = int(np.argmin(distances))
    return {
        "index": index,
        "distance_m": float(distances[index]),
    }


def make_trajectory_record(
    step,
    phase,
    env,
    command,
    stream_output,
    start_pos,
    goal_pos,
    reference_path_xy,
    return_path_xy,
    last_vlm_step,
    route_memory_progress=None,
):
    pose = get_robot_pose(env)
    position = get_robot_position(env)
    velocity = get_robot_velocity(env)
    yaw = pose_yaw(pose)
    return {
        "step": int(step),
        "phase": phase,
        "position": [float(x) for x in position],
        "quaternion_wxyz": [float(x) for x in pose[3:]],
        "yaw_rad": float(yaw),
        "yaw_deg": float(math.degrees(yaw)),
        "root_velocity": [float(x) for x in velocity],
        "speed_mps": float(np.linalg.norm(velocity[:2])),
        "command": [float(x) for x in command],
        "last_vlm_step": int(last_vlm_step) if last_vlm_step is not None else None,
        "last_vlm_output": stream_output,
        "distance_to_start_m": float(np.linalg.norm(position[:2] - start_pos[:2])),
        "distance_to_outbound_goal_m": float(np.linalg.norm(position[:2] - goal_pos[:2])),
        "nearest_reference_path": nearest_path_point(position[:2], reference_path_xy),
        "nearest_return_path": nearest_path_point(position[:2], return_path_xy),
        "route_memory": route_memory_progress,
    }


def route_progress_to_record(progress, configured_source):
    if progress is None:
        return None
    return {
        "source": progress.source,
        "configured_source": configured_source,
        "target_dx_m": progress.target_dx_m,
        "target_dy_m": progress.target_dy_m,
        "distance_to_start_m": progress.distance_to_start_m,
        "bearing_to_start_deg": progress.bearing_to_start_deg,
        "current_pose_from_start": progress.current_pose_from_start,
        "return_pose_from_return_start": progress.return_pose_from_return_start,
        "return_start_pose_from_start": progress.return_start_pose_from_start,
        "target_anchor_index": progress.target_anchor_index,
        "anchor_dx_m": progress.anchor_dx_m,
        "anchor_dy_m": progress.anchor_dy_m,
        "distance_to_anchor_m": progress.distance_to_anchor_m,
        "bearing_to_anchor_deg": progress.bearing_to_anchor_deg,
        "anchor_route_remaining_m": progress.anchor_route_remaining_m,
        "anchor_heading_reliable": progress.anchor_heading_reliable,
        "relocalization_confidence": progress.relocalization_confidence,
        "relocalization_backend": progress.relocalization_backend,
        "filter_std_m": progress.filter_std_m,
        "oracle_route_current_s_m": progress.oracle_route_current_s_m,
        "oracle_route_target_s_m": progress.oracle_route_target_s_m,
        "oracle_route_lookahead_m": progress.oracle_route_lookahead_m,
    }


def route_progress_alignment_record(primary, shadow):
    if primary is None or shadow is None:
        return None
    primary_anchor = primary.target_anchor_index
    shadow_anchor = shadow.target_anchor_index
    anchor_index_error = (
        None if primary_anchor is None or shadow_anchor is None
        else int(shadow_anchor) - int(primary_anchor)
    )
    bearing_error = None
    if primary.bearing_to_anchor_deg is not None and shadow.bearing_to_anchor_deg is not None:
        bearing_error = float(
            math.degrees(math.atan2(
                math.sin(math.radians(shadow.bearing_to_anchor_deg - primary.bearing_to_anchor_deg)),
                math.cos(math.radians(shadow.bearing_to_anchor_deg - primary.bearing_to_anchor_deg)),
            ))
        )
    distance_error = None
    if primary.distance_to_anchor_m is not None and shadow.distance_to_anchor_m is not None:
        distance_error = float(shadow.distance_to_anchor_m - primary.distance_to_anchor_m)
    target_vector_error = None
    if (
        primary.target_dx_m is not None and primary.target_dy_m is not None
        and shadow.target_dx_m is not None and shadow.target_dy_m is not None
    ):
        target_vector_error = float(math.hypot(
            shadow.target_dx_m - primary.target_dx_m,
            shadow.target_dy_m - primary.target_dy_m,
        ))
    return {
        "primary_source": primary.source,
        "shadow_source": shadow.source,
        "anchor_index_error": anchor_index_error,
        "bearing_to_anchor_error_deg": bearing_error,
        "distance_to_anchor_error_m": distance_error,
        "target_vector_error_m": target_vector_error,
        "shadow_confidence": shadow.relocalization_confidence,
        "shadow_filter_std_m": shadow.filter_std_m,
        "shadow_backend": shadow.relocalization_backend,
    }


def _to_numpy_descriptor(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    if isinstance(value, np.ndarray) and value.shape[0] == 1:
        value = value[0]
    if isinstance(value, np.ndarray):
        return value.copy()
    return value


def denormalize_depth_obs(value, near_clip=0.3, far_clip=5.0):
    depth = _to_numpy_descriptor(value)
    if isinstance(depth, np.ndarray):
        depth = np.asarray(depth, dtype=np.float32)
        depth = np.squeeze(depth)
        if depth.size > 0 and np.nanmin(depth) >= -0.55 and np.nanmax(depth) <= 0.55:
            depth = (depth + 0.5) * (far_clip - near_clip) + near_clip
    return depth


def camera_intrinsics_from_env(env, width=512, height=512):
    try:
        sensor = env.unwrapped.scene.sensors["rgbd_camera"]
        matrix = sensor.data.intrinsic_matrices.detach().cpu().numpy()[0]
        return matrix.astype(np.float32).copy()
    except Exception:
        focal = 0.5 * float(width) / math.tan(math.radians(90.0) / 2.0)
        return np.asarray(
            [[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]],
            dtype=np.float32,
        )


def camera_pose_from_env(env):
    try:
        sensor = env.unwrapped.scene.sensors["rgbd_camera"]
        position = sensor.data.pos_w.detach().cpu().numpy()[0]
        quat = sensor.data.quat_w_world.detach().cpu().numpy()[0]
        return {
            "position_w": position.astype(np.float32).copy(),
            "quat_wxyz": quat.astype(np.float32).copy(),
        }
    except Exception:
        return None


def camera_extrinsic_body_from_env(env):
    try:
        camera_pose = camera_pose_from_env(env)
        if camera_pose is None:
            return None
        robot_pose = get_robot_pose(env)
        robot_position = np.asarray(robot_pose[:3], dtype=np.float32)
        robot_quat = np.asarray(robot_pose[3:7], dtype=np.float32)
        robot_rotation = _quat_wxyz_to_matrix(robot_quat)
        camera_rotation = _quat_wxyz_to_matrix(camera_pose["quat_wxyz"])
        rotation_body_camera = robot_rotation.T @ camera_rotation
        position_body = robot_rotation.T @ (camera_pose["position_w"] - robot_position)
        return {
            "rotation_body_camera": rotation_body_camera.astype(np.float32).copy(),
            "position_body": position_body.astype(np.float32).copy(),
        }
    except Exception:
        return None


def rear_camera_intrinsics_from_env(env, width=512, height=512):
    try:
        sensor = env.unwrapped.scene.sensors["rear_rgbd_camera"]
        matrix = sensor.data.intrinsic_matrices.detach().cpu().numpy()[0]
        return matrix.astype(np.float32).copy()
    except Exception:
        return camera_intrinsics_from_env(env, width, height)


def rear_camera_pose_from_env(env):
    try:
        sensor = env.unwrapped.scene.sensors["rear_rgbd_camera"]
        position = sensor.data.pos_w.detach().cpu().numpy()[0]
        quat = sensor.data.quat_w_world.detach().cpu().numpy()[0]
        return {
            "position_w": position.astype(np.float32).copy(),
            "quat_wxyz": quat.astype(np.float32).copy(),
        }
    except Exception:
        return None


def rear_camera_extrinsic_body_from_env(env):
    try:
        rear_pose = rear_camera_pose_from_env(env)
        if rear_pose is None:
            return None
        robot_pose = get_robot_pose(env)
        robot_position = np.asarray(robot_pose[:3], dtype=np.float32)
        robot_quat = np.asarray(robot_pose[3:7], dtype=np.float32)
        robot_rotation = _quat_wxyz_to_matrix(robot_quat)
        rear_rotation = _quat_wxyz_to_matrix(rear_pose["quat_wxyz"])
        rotation_body_rear = robot_rotation.T @ rear_rotation
        position_body_rear = robot_rotation.T @ (rear_pose["position_w"] - robot_position)
        return {
            "rotation_body_camera": rotation_body_rear.astype(np.float32).copy(),
            "position_body": position_body_rear.astype(np.float32).copy(),
        }
    except Exception:
        return None


def local_map_descriptor_from_env(env):
    """Best-effort local map extraction from Isaac sensors.

    Real LiDAR/RayCaster integrations should expose body-frame obstacle points
    as ``local_map_points_body``.  The fallback below handles common IsaacLab
    RayCaster data fields and filters ground hits later in ``local_map.py``.
    """
    try:
        sensors = getattr(env.unwrapped.scene, "sensors", {})
    except Exception:
        return None
    sensor = None
    for name in ("lidar", "local_lidar", "height_scanner", "ray_caster"):
        try:
            if name in sensors:
                sensor = sensors[name]
                break
        except Exception:
            continue
    if sensor is None:
        return None
    hits = None
    try:
        data = sensor.data
        for attr in ("ray_hits_w", "pointcloud_w", "points_w"):
            value = getattr(data, attr, None)
            if value is not None:
                hits = _to_numpy_descriptor(value)
                break
    except Exception:
        hits = None
    if not isinstance(hits, np.ndarray):
        return None
    hits = np.asarray(hits, dtype=np.float32)
    if hits.ndim == 3:
        hits = hits[0]
    if hits.ndim != 2 or hits.shape[1] < 3:
        return None
    valid = np.isfinite(hits).all(axis=1)
    hits = hits[valid]
    if len(hits) == 0:
        return None
    robot_pose = get_robot_pose(env)
    robot_position = np.asarray(robot_pose[:3], dtype=np.float32)
    robot_rotation = _quat_wxyz_to_matrix(np.asarray(robot_pose[3:7], dtype=np.float32))
    points_body = (robot_rotation.T @ (hits[:, :3] - robot_position).T).T.astype(np.float32)
    return {
        "local_map_points_body": points_body,
        "local_map_source": "isaac_sensor",
    }


def route_memory_descriptor_from_infos(infos, env=None):
    observations = infos.get("observations", {}) if isinstance(infos, dict) else {}
    descriptor = {}
    rgb_obs = observations.get("camera_obs")
    if isinstance(rgb_obs, dict):
        rgb_obs = rgb_obs.get("rgb_measurement")
    if rgb_obs is not None:
        rgb = _to_numpy_descriptor(rgb_obs)
        if isinstance(rgb, np.ndarray):
            rgb = np.asarray(rgb)
            if rgb.ndim == 3:
                descriptor["rgb"] = rgb[:, :, :3].copy()

    route_obs = observations.get("route_memory_obs")
    if isinstance(route_obs, dict):
        for key, value in route_obs.items():
            descriptor[key] = _to_numpy_descriptor(value)
    elif route_obs is not None:
        descriptor["route_memory_obs"] = _to_numpy_descriptor(route_obs)

    local_map_obs = observations.get("local_map_obs")
    if isinstance(local_map_obs, dict):
        for key, value in local_map_obs.items():
            descriptor[f"local_map_{key}"] = _to_numpy_descriptor(value)
    elif local_map_obs is not None:
        descriptor["local_map_obs"] = _to_numpy_descriptor(local_map_obs)

    depth_obs = observations.get("depth_obs")
    if isinstance(depth_obs, dict):
        for key, value in depth_obs.items():
            descriptor[f"depth_{key}"] = denormalize_depth_obs(value)
    elif depth_obs is not None:
        descriptor["depth_obs"] = denormalize_depth_obs(depth_obs)

    # Rear camera RGB
    rear_rgb_obs = observations.get("rear_camera_obs")
    if isinstance(rear_rgb_obs, dict):
        rear_rgb_obs = rear_rgb_obs.get("rgb_measurement")
    if rear_rgb_obs is not None:
        rear_rgb = _to_numpy_descriptor(rear_rgb_obs)
        if isinstance(rear_rgb, np.ndarray) and rear_rgb.ndim == 3:
            descriptor["rear_rgb"] = rear_rgb[:, :, :3].copy()

    # Rear camera depth
    rear_depth_obs = observations.get("rear_depth_obs")
    if isinstance(rear_depth_obs, dict):
        for key, value in rear_depth_obs.items():
            descriptor[f"rear_depth_{key}"] = denormalize_depth_obs(value)
    elif rear_depth_obs is not None:
        descriptor["rear_depth_obs"] = denormalize_depth_obs(rear_depth_obs)

    if env is not None:
        descriptor["camera_intrinsics"] = camera_intrinsics_from_env(env)
        camera_pose = camera_pose_from_env(env)
        if camera_pose is not None:
            descriptor["camera_position_w"] = camera_pose["position_w"]
            descriptor["camera_quat_wxyz"] = camera_pose["quat_wxyz"]
        camera_extrinsic = camera_extrinsic_body_from_env(env)
        if camera_extrinsic is not None:
            descriptor["camera_rotation_body"] = camera_extrinsic["rotation_body_camera"]
            descriptor["camera_position_body"] = camera_extrinsic["position_body"]

        descriptor["rear_camera_intrinsics"] = rear_camera_intrinsics_from_env(env)
        rear_pose = rear_camera_pose_from_env(env)
        if rear_pose is not None:
            descriptor["rear_camera_position_w"] = rear_pose["position_w"]
            descriptor["rear_camera_quat_wxyz"] = rear_pose["quat_wxyz"]
        rear_extrinsic = rear_camera_extrinsic_body_from_env(env)
        if rear_extrinsic is not None:
            descriptor["rear_camera_rotation_body"] = rear_extrinsic["rotation_body_camera"]
            descriptor["rear_camera_position_body"] = rear_extrinsic["position_body"]
        local_map = local_map_descriptor_from_env(env)
        if local_map is not None:
            descriptor.update(local_map)

    return descriptor or None


def refresh_low_level_observation(env):
    with torch.inference_mode(False):
        if isinstance(env.env, RslRlVecEnvHistoryWrapper):
            if hasattr(env.env.unwrapped, "observation_manager"):
                obs_dict = env.env.unwrapped.observation_manager.compute()
            else:
                obs_dict = env.env.unwrapped._get_observations()
            proprio_obs, obs = obs_dict["proprio"], obs_dict["policy"]
            env.env.proprio_obs_buf.zero_()
            zero_history = env.env.proprio_obs_buf.view(env.env.num_envs, -1)
            env.low_level_obs = torch.cat([obs, zero_history], dim=1).detach().clone()
        else:
            env.low_level_obs, _ = env.env.get_observations()
            env.low_level_obs = env.low_level_obs.detach().clone()
    env.low_level_action = None


def set_robot_pose(env, pose):
    robot = env.unwrapped.scene["robot"]
    pose_tensor = torch.as_tensor(pose, dtype=robot.data.root_state_w.dtype, device=robot.device).unsqueeze(0)
    velocity = torch.zeros((1, 6), dtype=robot.data.root_state_w.dtype, device=robot.device)
    robot.write_root_pose_to_sim(pose_tensor)
    robot.write_root_velocity_to_sim(velocity)
    if hasattr(env.unwrapped.sim, "write_data_to_sim"):
        env.unwrapped.sim.write_data_to_sim()

    if isinstance(env.env, RslRlVecEnvHistoryWrapper):
        env.env.proprio_obs_buf.zero_()


def reset_navigation_memory(env, pose):
    set_robot_pose(env, pose)
    env.prev_pos = torch.as_tensor(pose[:3], dtype=env.unwrapped.scene["robot"].data.root_state_w.dtype, device=env.unwrapped.device)
    env.same_pos_count = 0
    env.set_stop_called(False)
    refresh_low_level_observation(env)


def parse_vlm_command(text):
    text = "" if text is None else str(text)
    lower_text = text.lower()
    is_valid = any(keyword in lower_text for keyword in ("turn left", "turn right", "move forward", "move", "stop"))
    command, duration = get_vel_command(text)
    return command, duration, is_valid


def build_round_trip_instruction(episode):
    original_instruction = InstructionData(**episode["instruction"]).instruction_text.strip()
    return (
        f"{original_instruction} "
        "After confirming the target, turn around and return to the original starting point by retracing the same route in reverse. "
        "Stop when you are back at the starting point."
    )


def build_phase_instruction(episode, phase):
    original_instruction = InstructionData(**episode["instruction"]).instruction_text.strip()
    if phase == "outbound":
        return (
            f"{original_instruction} "
            "This is the outbound phase of a round-trip task. Stop at the described target before returning."
        )
    if phase == "return":
        return (
            "Return to the original starting point by retracing the route you just traveled in reverse. "
            "Use the visual scene to go back through the same rooms and corridors, then stop at the starting point. "
            f"The outbound instruction was: {original_instruction}"
        )
    return "Confirm the target by scanning in place."


def get_query_instruction(episode, phase, round_trip_instruction):
    if args_cli.round_trip_mode == "static_long_instruction":
        return round_trip_instruction
    return build_phase_instruction(episode, phase)


def build_episode_instructions(episode, dataset_path):
    if args_cli.instruction_rewriter_provider == "legacy":
        return {
            "round_trip": build_round_trip_instruction(episode),
            "outbound": build_phase_instruction(episode, "outbound"),
            "return": build_phase_instruction(episode, "return"),
            "source": "legacy",
            "model": "",
        }

    original_instruction = InstructionData(**episode["instruction"]).instruction_text.strip()
    rewriter = InstructionRewriter(
        provider=args_cli.instruction_rewriter_provider,
        model=args_cli.instruction_rewriter_model,
        cache_path=args_cli.instruction_rewriter_cache,
        endpoint=args_cli.instruction_llm_endpoint,
        api_key=os.getenv(args_cli.instruction_llm_api_key_env),
        timeout=args_cli.instruction_llm_timeout,
        dataset_path=dataset_path,
        episode_index=args_cli.episode_idx,
    )
    try:
        instructions = rewriter.rewrite(original_instruction)
    except InstructionRewriteError as exc:
        raise RuntimeError(f"Unable to prepare round-trip instruction: {exc}") from exc
    return {
        "round_trip": instructions.round_trip_instruction,
        "outbound": instructions.outbound_instruction,
        "return": instructions.return_instruction,
        "source": instructions.provider,
        "model": instructions.model,
    }


def main():
    """IsaacSim round-trip evaluation using NaVILA and trained low-level policy."""

    # read R2R test episodes
    r2r_data_path = os.path.join(ASSETS_DIR, "vln_ce_isaac_v1.json.gz")
    all_episodes = read_episodes(r2r_data_path)
    episode = all_episodes[args_cli.episode_idx]

    env_cfg = parse_env_cfg(args_cli.task, num_envs=args_cli.num_envs)

    # reset the position and rotation of the robot
    env_cfg = reset_start_pos_rot(env_cfg, args_cli, episode)

    agent_cfg: RslRlOnPolicyRunnerCfg = cli_args.parse_rsl_rl_cfg(
        args_cli.task, args_cli, play=True
    )

    # specify directory for logging experiments
    log_root_path = os.path.join(os.path.dirname(__file__),"../logs", "rsl_rl", agent_cfg.experiment_name)
    log_root_path = os.path.abspath(log_root_path)
    log_dir = os.path.join(log_root_path, args_cli.load_run)
    print(f"[INFO] Loading run from directory: {log_dir}")

    # update agent config with the one from the loaded run
    log_agent_cfg_file_path = os.path.join(log_dir, "params", "agent.yaml")
    assert os.path.exists(log_agent_cfg_file_path), f"Agent config file not found: {log_agent_cfg_file_path}"
    log_agent_cfg_dict = load_yaml(log_agent_cfg_file_path)
    update_class_from_dict(agent_cfg, log_agent_cfg_dict)

    # specify directory for logging experiments
    resume_path = get_checkpoint_path(log_root_path, args_cli.load_run, agent_cfg.load_checkpoint)
    print(f"[INFO]: Loading model checkpoint from: {resume_path}")

    # create isaac environment
    env = gym.make(args_cli.task, cfg=env_cfg, render_mode=None)
    # wrap around environment for rsl-rl
    if args_cli.history_length > 0:
        env = RslRlVecEnvHistoryWrapper(env, history_length=args_cli.history_length)
    else:
        env = RslRlVecEnvWrapper(env)

    # load previously trained model
    ppo_runner = OnPolicyRunner(env, agent_cfg.to_dict(), log_dir=None, device=agent_cfg.device)
    ppo_runner.load(resume_path)
    print(f"[INFO]: Loading model checkpoint from: {resume_path}")
    policy = ppo_runner.get_inference_policy(device=env.unwrapped.device)

    all_measures = ["PathLength", "DistanceToGoal", "Success", "SPL", "OracleNavigationError", "OracleSuccess"]
    env = VLNEnvWrapper(env, policy, args_cli.task, episode, high_level_obs_key="camera_obs",
                        measure_names=all_measures)
    
    # set view pos and target
    robot_pos_w = env.unwrapped.scene["robot"].data.root_pos_w[0].detach().cpu().numpy()
    robot_quat_w = env.unwrapped.scene["robot"].data.root_quat_w[0].detach().cpu().numpy()
    roll, pitch, yaw = quat2eulers(robot_quat_w[0], robot_quat_w[1], robot_quat_w[2], robot_quat_w[3])
    cam_eye = (robot_pos_w[0] - 0.8 * math.sin(-yaw), robot_pos_w[1] - 0.8 * math.cos(-yaw), robot_pos_w[2] + 0.8)
    cam_target = (robot_pos_w[0], robot_pos_w[1], robot_pos_w[2])
    # set the camera view
    env.unwrapped.sim.set_camera_view(eye=cam_eye, target=cam_target)
    
    # step with zeros actions to get the initial frame
    obs, infos = env.reset()

    # NaViLA training gets image observations each 0.5s, visualize every 0.1s
    steps_per_image = 0.5 / (env.unwrapped.cfg.sim.dt * env.unwrapped.cfg.decimation)
    steps_per_viz_image = 0.1 / (env.unwrapped.cfg.sim.dt * env.unwrapped.cfg.decimation)

    rgb_obs = infos["observations"]["camera_obs"]
    init_frame = rgb_obs[0, :, :, :3].cpu().numpy()
    # init_frame = cv2.rotate(init_frame, cv2.ROTATE_90_CLOCKWISE)
    instruction = InstructionData(**episode["instruction"])
    episode_instructions = build_episode_instructions(episode, r2r_data_path)
    round_trip_instruction = episode_instructions["round_trip"]
    outbound_instruction = episode_instructions["outbound"]
    return_instruction = episode_instructions["return"]
    if args_cli.return_instruction_file:
        with open(args_cli.return_instruction_file, "r", encoding="utf-8") as instruction_file:
            return_instruction = instruction_file.read().strip()
        if not return_instruction:
            raise RuntimeError("Return instruction file is empty.")
    elif args_cli.return_instruction_override.strip():
        return_instruction = args_cli.return_instruction_override.strip()
    current_instruction_text = (
        round_trip_instruction
        if args_cli.round_trip_mode == "static_long_instruction"
        else outbound_instruction
    )
    image_observations = []
    image_observations.append(Image.fromarray(init_frame))

    add_instruction_on_img(init_frame, f"[outbound] {current_instruction_text}")
    vis_frame = infos["observations"]["viz_camera_obs"][0, :, :, :3].cpu().numpy()
    # vis_frame = cv2.rotate(vis_frame, cv2.ROTATE_90_CLOCKWISE)
    add_instruction_on_img(vis_frame, "")
    rgb_obses = [np.concatenate([init_frame, vis_frame], axis=1)]

    num_steps = 0
    target_steps = 0
    same_pos_count = 0
    prev_pos = env.unwrapped.scene["robot"].data.root_pos_w[0].detach().cpu().numpy()
    control_dt = env.unwrapped.cfg.sim.dt * env.unwrapped.cfg.decimation
    max_episode_steps = 100 * 0.5 / control_dt
    max_return_steps = args_cli.max_return_seconds / control_dt
    confirm_turn_steps = int(args_cli.confirm_turn_seconds / control_dt)
    start_pos = np.array(episode["start_position"], dtype=np.float32)
    goal_pos = np.array(episode["reference_path"][-1], dtype=np.float32)
    episode_goal_radius = float(episode["goals"][0]["radius"])
    success_radius = (
        float(args_cli.success_radius)
        if args_cli.success_radius is not None
        else (
            float(args_cli.return_success_radius)
            if args_cli.return_success_radius is not None
            else episode_goal_radius
        )
    )
    reference_path_xy = np.asarray([[p[0], p[1]] for p in episode["reference_path"]], dtype=np.float32)
    return_path_xy = np.asarray([[p[0], p[1]] for p in reversed(episode["reference_path"])], dtype=np.float32)
    result_suffix = f"_{args_cli.result_suffix}" if args_cli.result_suffix else ""
    result_dir = (
        f"eval_results/round_trip_{args_cli.round_trip_mode}_{args_cli.task}_"
        f"loco_{args_cli.load_run}{result_suffix}"
    )
    episode_output_id = int(episode["episode_id"]) - 1
    trajectory_relpath = f"trajectories/output_{episode_output_id}.jsonl"
    if not os.path.exists(result_dir):
        os.makedirs(result_dir)
    topdown_route_map = None
    topdown_route_map_summary = {"enabled": False}
    if args_cli.topdown_route_map:
        try:
            topdown_route_map = capture_occupancy_floor_slice(
                episode,
                resolution_m_per_px=args_cli.topdown_map_resolution,
                padding_m=args_cli.topdown_map_padding_m,
                z_min_above_floor_m=args_cli.topdown_map_z_min,
                z_max_above_floor_m=args_cli.topdown_map_z_max,
                max_size_px=args_cli.topdown_map_max_size_px,
            )
            print(
                "[INFO] Captured USD floor-slice occupancy map: "
                f"{topdown_route_map.meta['width_px']}x{topdown_route_map.meta['height_px']} px, "
                f"{topdown_route_map.meta['mesh_triangles_rasterized']} rasterized triangles"
            )
        except Exception as exc:
            topdown_route_map_summary = {
                "enabled": True,
                "error": str(exc),
            }
            print(f"[WARN] Unable to capture top-down occupancy map: {exc}")
    stream_output = ""
    vlm_vel_commands = [0.0, 0.0, 0.0]
    route_relocalizer = None
    route_relocalization_diagnostics = {}
    feature_relocalization_backends = {
        "feature_depth": "orb",
        "sift_depth": "sift",
        "loftr_depth": "loftr",
    }
    if args_cli.route_relocalization_backend in feature_relocalization_backends:
        matcher_backend = feature_relocalization_backends[args_cli.route_relocalization_backend]
        route_relocalizer = lambda descriptor, anchors: feature_depth_anchor_relocalization(
            descriptor,
            anchors,
            max_candidates=args_cli.route_relocalization_window,
            diagnostics=route_relocalization_diagnostics,
            matcher_backend=matcher_backend,
            return_candidates=True,
        )
    elif args_cli.route_relocalization_backend == "lidar_local_map":
        route_relocalizer = lambda descriptor, anchors: local_map_anchor_relocalization(
            descriptor,
            anchors,
            max_candidates=args_cli.route_relocalization_window,
            diagnostics=route_relocalization_diagnostics,
            return_candidates=True,
        )
    relocalization_interval_backends = set(feature_relocalization_backends) | {"lidar_local_map"}
    route_agent = RouteMemoryAgent(
        enabled=args_cli.route_memory,
        hint_mode=args_cli.route_hint_mode,
        anchor_spacing_m=args_cli.route_anchor_spacing_m,
        min_relocalization_confidence=args_cli.route_min_relocalization_confidence,
        relocalization_interval_updates=(
            args_cli.route_relocalization_interval_updates
            if args_cli.route_relocalization_backend in relocalization_interval_backends
            else 1
        ),
        relocalizer=route_relocalizer,
    )
    route_agent.vio_bridge_enabled = bool(getattr(args_cli, "vio_bridge", False))
    route_agent.vio_bridge_std_threshold_m = float(getattr(args_cli, "vio_bridge_std_m", 2.5))
    route_agent.vio_bridge_feature_radius_m = float(getattr(args_cli, "vio_bridge_feature_radius_m", 2.0))
    stop_gate = None
    if getattr(args_cli, "stop_gate", False):
        stop_gate = ReturnStopGate(
            r_in=float(getattr(args_cli, "stop_gate_r_in", 3.0)),
            r_out=float(getattr(args_cli, "stop_gate_r_out", 3.0)),
            confirm_steps=int(getattr(args_cli, "stop_gate_confirm_steps", 3)),
            min_confidence=float(getattr(args_cli, "stop_gate_min_confidence", 0.5)),
        )
        print(
            f"[stop_gate] enabled: r_in={stop_gate.r_in} r_out={stop_gate.r_out} "
            f"confirm_steps={stop_gate.confirm_steps} "
            f"min_confidence={stop_gate.min_confidence}",
            flush=True,
        )
    hint_action_arbiter = None
    _last_hint_action_decision = None
    if getattr(args_cli, "hint_action_arbiter", False):
        hint_action_arbiter = HintActionArbiter(HintActionArbiterConfig(
            forward_cone_deg=float(getattr(args_cli, "hint_arbiter_forward_cone_deg", 15.0)),
            forward_conflict_bearing_deg=float(
                getattr(args_cli, "hint_arbiter_forward_conflict_bearing_deg", 30.0)
            ),
            turn_step_deg=float(getattr(args_cli, "hint_arbiter_turn_step_deg", 45.0)),
            forward_distance_cm=int(getattr(args_cli, "hint_arbiter_forward_distance_cm", 75)),
            max_clear_path_distance_m=float(
                getattr(args_cli, "hint_arbiter_max_clear_path_distance_m", 1.0)
            ),
            robot_radius_m=float(getattr(args_cli, "hint_arbiter_robot_radius_m", 0.30)),
            clearance_margin_m=float(getattr(args_cli, "hint_arbiter_clearance_margin_m", 0.12)),
            allow_without_clear_path=bool(
                getattr(args_cli, "hint_arbiter_allow_without_clear_path", False)
            ),
        ))
        print(
            "[hint_arbiter] enabled: "
            f"topdown_map_available={topdown_route_map is not None} "
            f"allow_without_clear_path={hint_action_arbiter.cfg.allow_without_clear_path}",
            flush=True,
        )
    if args_cli.route_memory:
        route_agent.update_latest_anchor_metadata({
            "world_pose": [float(x) for x in get_robot_pose(env)],
            "world_pose_source": "isaac_oracle_for_relocalization_eval",
        })
    phase_events = []
    stop_events = []
    trajectory_records = []
    phase = "outbound"
    return_start_step = None
    outbound_stop_output = None
    outbound_measurements = None
    outbound_stop_distance_to_goal = None
    outbound_success = False
    return_success = False
    return_pose_before_oracle = None
    return_pose_after_oracle = None
    oracle_return_pose = None
    return_yaw_alignment = None
    return_pose_error_before_oracle = None
    return_pose_error_after_oracle = None
    last_vlm_step = None
    force_capture_next_image = False
    _gate_vlm_progress = None     # progress used at the last VLM query step
    _last_gate_decision: GateDecision = None  # gate decision from the last VLM query
    current_route_descriptor = None
    # visualizer = define_markers()
    # simulate environment
    while simulation_app.is_running():
        # run everything in inference mode
        with torch.inference_mode():
            if num_steps == target_steps:
                if phase in ("outbound", "return"):
                    query_instruction_text = current_instruction_text
                    route_hint_event = None
                    _gate_vlm_progress = None   # reset each VLM step
                    if phase == "return" and args_cli.route_memory:
                        progress_override = route_progress_override(
                            args_cli.route_hint_source,
                            env,
                            start_pos,
                            route_agent,
                        )
                        route_query_progress = (
                            progress_override
                            if progress_override is not None else route_agent.progress()
                        )
                        route_shadow_progress = (
                            route_agent.progress()
                            if progress_override is not None else None
                        )
                        _gate_vlm_progress = route_query_progress   # capture for stop gate / action arbiter
                        query_instruction_text, route_hint_event = route_agent.inject_hint(
                            current_instruction_text,
                            num_steps,
                            progress_override=route_query_progress,
                        )
                        if route_hint_event is not None:
                            route_hint_event["source"] = args_cli.route_hint_source
                            route_hint_event["shadow_progress"] = route_progress_to_record(
                                route_shadow_progress,
                                "shadow_non_oracle",
                            )
                            route_hint_event["shadow_alignment"] = route_progress_alignment_record(
                                route_query_progress,
                                route_shadow_progress,
                            )
                            phase_events.append({
                                "step": int(num_steps),
                                "phase": phase,
                                "event": "route_memory_hint",
                                **route_hint_event,
                            })
                    stream_output = sample_images_and_send_to_vlm(
                        image_observations,
                        args_cli.vlm_host,
                        args_cli.vlm_port,
                        query_instruction_text,
                    )
                    vlm_vel_commands, time_to_go, is_parseable = parse_vlm_command(stream_output)
                    _last_hint_action_decision = None
                    if hint_action_arbiter is not None and phase == "return":
                        _last_hint_action_decision = hint_action_arbiter.check(
                            progress=_gate_vlm_progress,
                            vlm_output=stream_output,
                            robot_position=get_robot_position(env),
                            robot_yaw_rad=pose_yaw(get_robot_pose(env)),
                            topdown_map=topdown_route_map,
                            local_map_descriptor=current_route_descriptor,
                        )
                        phase_events.append({
                            "step": int(num_steps),
                            "phase": phase,
                            "event": "hint_action_arbiter",
                            **_last_hint_action_decision.as_log_dict(),
                        })
                        if _last_hint_action_decision.override:
                            stream_output = _last_hint_action_decision.replacement_output
                            vlm_vel_commands, time_to_go, is_parseable = parse_vlm_command(stream_output)
                        print(
                            f"[hint_arbiter] step={num_steps} "
                            f"override={_last_hint_action_decision.override} "
                            f"reason={_last_hint_action_decision.reason} "
                            f"desired={_last_hint_action_decision.desired_kind} "
                            f"bearing={_last_hint_action_decision.desired_bearing_deg} "
                            f"clear={_last_hint_action_decision.clear_path}",
                            flush=True,
                        )
                    route_agent.update_action_history(vlm_vel_commands)
                    env_steps_to_go = int(time_to_go / (
                        env.unwrapped.cfg.sim.dt * env.unwrapped.cfg.decimation
                    ))
                    if env_steps_to_go <= 0 and "stop" not in str(stream_output).lower():
                        env_steps_to_go = 1
                    target_steps = num_steps + env_steps_to_go
                    phase_events.append({
                        "step": int(num_steps),
                        "phase": phase,
                        "event": "vlm_command",
                        "output": stream_output,
                        "parseable": bool(is_parseable),
                        "command": [float(x) for x in vlm_vel_commands],
                        "duration_seconds": float(time_to_go),
                    })
                    last_vlm_step = num_steps
                    print(
                        f"[{phase}] VLM output: {stream_output}\n"
                        f"Vel Command: {vlm_vel_commands}, Env Steps to go: {env_steps_to_go}, "
                        f"Parseable: {is_parseable}\n",
                        flush=True,
                    )

                    # --- Stop-gate arbiter (return phase only, no-op when disabled) ---
                    _vlm_stop_requested = (
                        env_steps_to_go == 0 and "stop" in str(stream_output).lower()
                    )
                    if stop_gate is not None and phase == "return":
                        _last_gate_decision = stop_gate.check(
                            progress=_gate_vlm_progress,
                            vlm_issued_stop=_vlm_stop_requested,
                        )
                        phase_events.append({
                            "step": int(num_steps),
                            "phase": phase,
                            "event": "stop_gate",
                            **_last_gate_decision.as_log_dict(),
                        })
                        if _last_gate_decision.decision == "vetoed":
                            vlm_vel_commands = list(_last_gate_decision.suggested_command)
                            route_agent.update_action_history(vlm_vel_commands)
                            env_steps_to_go = _last_gate_decision.suggested_steps
                            target_steps = num_steps + env_steps_to_go
                            _vlm_stop_requested = False
                        elif _last_gate_decision.decision == "forced":
                            _vlm_stop_requested = True
                        print(
                            f"[stop_gate] step={num_steps} "
                            f"decision={_last_gate_decision.decision} "
                            f"d={_last_gate_decision.authority_d} "
                            f"conf={_last_gate_decision.conf:.3f} "
                            f"teleport={_last_gate_decision.is_teleport_frame}",
                            flush=True,
                        )

                    if _vlm_stop_requested:
                        stop_events.append({
                            "step": int(num_steps),
                            "phase": phase,
                            "output": stream_output,
                            "position": [float(x) for x in get_robot_position(env)],
                        })
                        if phase == "outbound":
                            outbound_stop_output = stream_output
                            outbound_measurements = infos["measurements"]
                            outbound_stop_distance_to_goal = float(
                                np.linalg.norm(get_robot_position(env)[:2] - goal_pos[:2])
                            )
                            outbound_success = outbound_stop_distance_to_goal < success_radius
                            phase = "confirm"
                            phase_events.append({
                                "step": int(num_steps),
                                "phase": phase,
                                "event": "outbound_stop_to_confirm",
                                "distance_to_goal": outbound_stop_distance_to_goal,
                                "success": bool(outbound_success),
                            })
                            vlm_vel_commands = [0.0, 0.0, np.pi / 6.0]
                            target_steps = num_steps + confirm_turn_steps
                            stream_output = "[Confirm] scripted 360-degree scan"
                            image_observations = []
                        else:
                            return_stop_distance_to_start = float(
                                np.linalg.norm(get_robot_position(env)[:2] - start_pos[:2])
                            )
                            return_success = return_stop_distance_to_start < success_radius
                            phase_events.append({
                                "step": int(num_steps),
                                "phase": phase,
                                "event": "return_stop",
                                "distance_to_start": return_stop_distance_to_start,
                                "success": bool(return_success),
                            })
                            env.set_stop_called(True)

                elif phase == "confirm":
                    phase = "return"
                    return_start_step = num_steps
                    previous_anchor_count = len(route_agent.anchors)
                    route_agent.finalize_outbound(
                        descriptor=current_route_descriptor,
                        metadata={
                            "world_pose": [float(x) for x in get_robot_pose(env)],
                            "world_pose_source": "isaac_oracle_for_relocalization_eval",
                        },
                    )
                    if args_cli.route_memory and len(route_agent.anchors) > previous_anchor_count:
                        route_agent.update_latest_anchor_metadata({
                            "world_pose": [float(x) for x in get_robot_pose(env)],
                            "world_pose_source": "isaac_oracle_for_relocalization_eval",
                        })
                    return_pose_before_oracle = get_robot_pose(env)
                    oracle_return_pose = get_oracle_return_pose(env, episode)
                    return_pose_error_before_oracle = summarize_pose_error(
                        return_pose_before_oracle,
                        oracle_return_pose,
                    )
                    if args_cli.oracle_return_pose:
                        reset_navigation_memory(env, oracle_return_pose)
                    if args_cli.oracle_align_return_yaw_to_anchor_segment:
                        return_yaw_alignment = align_return_yaw_to_anchor_segment(env, route_agent)
                    return_pose_after_oracle = get_robot_pose(env)
                    return_pose_error_after_oracle = summarize_pose_error(
                        return_pose_after_oracle,
                        oracle_return_pose,
                    )
                    current_instruction_text = (
                        round_trip_instruction
                        if args_cli.round_trip_mode == "static_long_instruction"
                        else return_instruction
                    )
                    phase_events.append({
                        "step": int(num_steps),
                        "phase": phase,
                        "event": "confirm_complete_to_return",
                        "instruction": current_instruction_text,
                        "oracle_return_pose_enabled": bool(args_cli.oracle_return_pose),
                        "oracle_align_return_yaw_to_anchor_segment": bool(
                            args_cli.oracle_align_return_yaw_to_anchor_segment
                        ),
                        "return_yaw_alignment": return_yaw_alignment,
                        "pose_before_oracle": [float(x) for x in return_pose_before_oracle],
                        "pose_after_oracle": [float(x) for x in return_pose_after_oracle],
                        "pose_error_before_oracle": return_pose_error_before_oracle,
                        "pose_error_after_oracle": return_pose_error_after_oracle,
                    })
                    vlm_vel_commands = [0.0, 0.0, 0.0]
                    target_steps = num_steps + 1
                    image_observations = []
                    force_capture_next_image = True
                    stream_output = "[Return] query NaVILA with return instruction"
                    print(
                        f"[return] start step={num_steps}, oracle={bool(args_cli.oracle_return_pose)}, "
                        f"pose_error_after_oracle={return_pose_error_after_oracle}",
                        flush=True,
                    )

        obs, _, done, infos = env.step(torch.tensor(vlm_vel_commands, device = obs.device))

        if stop_gate is not None and phase == "return":
            stop_gate.notify_sim_step(get_robot_position(env))

        if args_cli.route_memory:
            action_delta = [
                float(vlm_vel_commands[0]) * control_dt,
                float(vlm_vel_commands[1]) * control_dt,
                float(vlm_vel_commands[2]) * control_dt,
            ]
            route_descriptor = route_memory_descriptor_from_infos(infos, env)
            current_route_descriptor = route_descriptor
            if phase in ("outbound", "confirm"):
                previous_anchor_count = len(route_agent.anchors)
                route_agent.update_outbound_motion(action_delta, descriptor=route_descriptor)
                if len(route_agent.anchors) > previous_anchor_count:
                    route_agent.update_latest_anchor_metadata({
                        "world_pose": [float(x) for x in get_robot_pose(env)],
                        "world_pose_source": "isaac_oracle_for_relocalization_eval",
                    })
            elif phase == "return":
                relocalization = (
                    oracle_anchor_relocalization(env, route_agent)
                    if args_cli.route_relocalization_backend == "oracle_anchor"
                    else None
                )
                route_agent.update_return_motion(
                    action_delta,
                    local_descriptor=route_descriptor,
                    relocalization=relocalization,
                )

        route_memory_progress = None
        route_memory_shadow_progress = None
        route_memory_alignment = None
        if args_cli.route_memory and phase == "return":
            progress = route_progress_override(args_cli.route_hint_source, env, start_pos, route_agent)
            shadow_progress = route_agent.progress() if progress is not None else None
            if progress is None:
                progress = route_agent.progress()
            if progress is not None:
                route_memory_progress = route_progress_to_record(progress, args_cli.route_hint_source)
                route_memory_shadow_progress = route_progress_to_record(
                    shadow_progress,
                    "shadow_non_oracle",
                )
                route_memory_alignment = route_progress_alignment_record(progress, shadow_progress)

        _traj_record = make_trajectory_record(
            num_steps,
            phase,
            env,
            vlm_vel_commands,
            stream_output,
            start_pos,
            goal_pos,
            reference_path_xy,
            return_path_xy,
            last_vlm_step,
            route_memory_progress,
        )
        if stop_gate is not None and _last_gate_decision is not None:
            _traj_record["stop_gate"] = _last_gate_decision.as_log_dict()
        if hint_action_arbiter is not None and _last_hint_action_decision is not None:
            _traj_record["hint_action_arbiter"] = _last_hint_action_decision.as_log_dict()
        if route_memory_shadow_progress is not None:
            _traj_record["route_memory_shadow"] = route_memory_shadow_progress
        if route_memory_alignment is not None:
            _traj_record["route_memory_alignment"] = route_memory_alignment
        trajectory_records.append(_traj_record)

        distance_to_start = float(np.linalg.norm(get_robot_position(env)[:2] - start_pos[:2]))
        if phase == "return" and return_start_step is not None and num_steps - return_start_step > max_return_steps:
            phase_events.append({
                "step": int(num_steps),
                "phase": phase,
                "event": "return_timeout",
                "distance_to_start": distance_to_start,
            })
            break

        if phase == "return" and return_start_step is not None and (num_steps - return_start_step) % 500 == 0:
            print(
                f"[return] step={num_steps}, elapsed_return_steps={num_steps - return_start_step}, "
                f"distance_to_start={distance_to_start:.3f}",
                flush=True,
            )

        if done or env.is_stop_called or (phase == "outbound" and num_steps > max_episode_steps):
            break

        cur_pos = env.unwrapped.scene["robot"].data.root_pos_w[0].detach().cpu().numpy()
        robot_vel = np.linalg.norm(env.unwrapped.scene["robot"].data.root_vel_w[0].detach().cpu().numpy())
        if np.linalg.norm(cur_pos - prev_pos) < 0.01 and robot_vel < 0.01:
            same_pos_count += 1
        else:
            same_pos_count = 0
        prev_pos = cur_pos

        # Break out of the loop if the robot has stayed in the same location for 500 steps
        if same_pos_count >= 1000:
            print("Robot has stayed in the same location for 1000 steps. Breaking out of the loop.")
            break

        if force_capture_next_image or num_steps % steps_per_image == 0:
            curr_frame = infos["observations"]["camera_obs"][0, :, :, :3].cpu().numpy()
            image_observations.append(Image.fromarray(curr_frame))
            curr_frame_copy = curr_frame.copy()
            add_instruction_on_img(curr_frame_copy, f"[{phase}] {current_instruction_text}")
            force_capture_next_image = False
            
        if num_steps % steps_per_viz_image == 0:
            curr_vis_frame = infos["observations"]["viz_camera_obs"][0, :, :, :3].cpu().numpy()
            add_instruction_on_img(curr_vis_frame, stream_output)
            rgb_obses.append(np.concatenate([curr_frame_copy, curr_vis_frame], axis=1))

        num_steps += 1

        # if args_cli.visualize_path:
        #     visualizer.visualize(reference_path_isaac)
    measurements = infos["measurements"]
    final_pos = get_robot_position(env)
    distance_to_start = float(np.linalg.norm(final_pos[:2] - start_pos[:2]))
    distance_to_goal = float(np.linalg.norm(final_pos[:2] - goal_pos[:2]))
    route_memory_summary = route_agent.summary()
    if topdown_route_map is not None:
        try:
            topdown_route_map_summary = save_topdown_route_map(
                result_dir,
                episode_output_id,
                topdown_route_map,
                trajectory_records,
                route_memory_summary,
                episode,
            )
            print(
                "[INFO] Saved top-down route map: "
                f"{topdown_route_map_summary['route_overlay_file']}"
            )
        except Exception as exc:
            topdown_route_map_summary = {
                "enabled": True,
                "error": str(exc),
                "meta": dict(topdown_route_map.meta),
            }
            print(f"[WARN] Unable to save top-down route map: {exc}")
    measurements["round_trip"] = {
        "mode": args_cli.round_trip_mode,
        "completed_phase": phase,
        "outbound_success": outbound_success,
        "return_success": bool(return_success),
        "round_trip_success": bool(outbound_success and return_success),
        "distance_to_start": distance_to_start,
        "distance_to_goal": distance_to_goal,
        "round_trip_instruction": round_trip_instruction,
        "outbound_instruction": outbound_instruction,
        "return_instruction": return_instruction,
        "instruction_rewriter_provider": episode_instructions["source"],
        "instruction_rewriter_model": episode_instructions["model"],
        "return_instruction_override": bool(
            args_cli.return_instruction_override.strip() or args_cli.return_instruction_file
        ),
        "return_instruction_file": args_cli.return_instruction_file or None,
        "oracle_return_pose_enabled": bool(args_cli.oracle_return_pose),
        "oracle_align_return_yaw_to_anchor_segment": bool(args_cli.oracle_align_return_yaw_to_anchor_segment),
        "return_yaw_alignment": return_yaw_alignment,
        "return_pose_before_oracle": (
            [float(x) for x in return_pose_before_oracle]
            if return_pose_before_oracle is not None else None
        ),
        "return_pose_after_oracle": (
            [float(x) for x in return_pose_after_oracle]
            if return_pose_after_oracle is not None else None
        ),
        "oracle_return_pose": (
            [float(x) for x in oracle_return_pose]
            if oracle_return_pose is not None else None
        ),
        "return_pose_error_before_oracle": return_pose_error_before_oracle,
        "return_pose_error_after_oracle": return_pose_error_after_oracle,
        "outbound_stop_output": outbound_stop_output,
        "outbound_stop_distance_to_goal": outbound_stop_distance_to_goal,
        "episode_goal_radius": episode_goal_radius,
        "success_radius": success_radius,
        "success_requires_stop": True,
        "trajectory_file": trajectory_relpath,
        "trajectory_record_count": len(trajectory_records),
        "stop_events": stop_events,
        "phase_events": phase_events,
        "route_hint_source": args_cli.route_hint_source,
        "route_relocalization_backend": args_cli.route_relocalization_backend,
        "route_relocalization_diagnostics": route_relocalization_diagnostics,
        "route_memory": route_memory_summary,
        "topdown_route_map": topdown_route_map_summary,
        "stop_gate": {
            "enabled": stop_gate is not None,
            "r_in": stop_gate.r_in if stop_gate is not None else None,
            "r_out": stop_gate.r_out if stop_gate is not None else None,
            "confirm_steps": stop_gate.confirm_steps if stop_gate is not None else None,
            "min_confidence": stop_gate.min_confidence if stop_gate is not None else None,
        },
    }

    trajectory_dir = os.path.join(result_dir, "trajectories")
    if not os.path.exists(trajectory_dir):
        os.makedirs(trajectory_dir)
    trajectory_path = os.path.join(result_dir, trajectory_relpath)
    with open(trajectory_path, "w", encoding="utf-8") as f:
        for record in trajectory_records:
            f.write(json.dumps(record) + "\n")

    measurement_dir = os.path.join(result_dir, "measurements")
    if not os.path.exists(measurement_dir):
        os.makedirs(measurement_dir)
    with open(f"{measurement_dir}/{episode_output_id}.json", "w") as f:
        json.dump(measurements, f, indent=4)


    video_dir = os.path.join(result_dir, "videos")
    if not os.path.exists(video_dir):
        os.makedirs(video_dir)

    writer = imageio.get_writer(f"{video_dir}/output_{episode_output_id}.mp4", fps=10)
    for frame in rgb_obses:
        frame = frame.astype(np.uint8)
        writer.append_data(frame)

    writer.close()

    # close the simulator
    env.close()



if __name__ == "__main__":
    # run the main function
    main()
    # close sim app
    simulation_app.close()
