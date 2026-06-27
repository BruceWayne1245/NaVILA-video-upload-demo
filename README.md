# NaVILA + Isaac Sim VLN-CE Deployment on RTX 4090

Reproduction of [NaVILA](https://navila-bot.github.io/) (RSS 2025) Isaac Sim benchmark on a local workstation with RTX 4090.

**Status: End-to-end evaluation working ✅ — Episode 0: success=1.0, SPL=0.907**

**Latest update (2026-06-27) — LoFTR matcher integrated:** geometry pipeline verified correct via 18-test suite; LoFTR (`kornia==0.6.12`, `pretrained="outdoor"`) installed in both conda environments and wired as the `loftr_depth` backend. Offline synthetic tests show LoFTR produces 5–9× more inlier matches than ORB under rotation, scale change, and perspective warp. The `--route_relocalization_backend=loftr_depth` flag is ready; ep994 evaluation with the VLM server running is the next step.

**Anchor relocalization pipeline (2026-06-27):** route memory was extended to a map-free relocalization interface. Each outbound anchor stores RGB, depth, camera intrinsics, and route-distance metadata. The Return stage can accept a metric relative pose to any saved anchor and convert it into a prompt hint such as "route anchor A0 is 0.61 m away, 112 deg to your left; estimated remaining route via anchor is 0.61 m." An Isaac oracle-anchor backend verified the full hint pipeline on episode `994`: outbound success true, return success true, round-trip success true, final distance to start `0.619 m`.

**Classical backend failure analysis (2026-06-27):** ORB+depth on ep994 produced 12 estimates from 76 attempts (6–11 3D inliers each), all too noisy to help. GT covisibility diagnostics showed the bottleneck is matching quality, not missing shared view. SIFT+depth produced more candidates but every estimate was rejected by the consistency gate (37/37 rejected; minimum error 8.06 m). Geometry code was independently verified correct — a formal oracle-consistency proof and 18-test suite confirm the backproject→RANSAC→camera-to-body chain is exact. The 8 m+ SIFT errors are caused entirely by bad feature correspondences, not by a geometry bug.

---

## Hardware & System

| Component | Detail |
|---|---|
| GPU | NVIDIA GeForce RTX 4090 (24 GB VRAM, sm_89) |
| CPU | Intel Core i9-14900K (24 cores / 48 threads) |
| RAM | 125 GB |
| OS | Ubuntu 22.04.5 LTS |
| Driver | 570.124.06 |
| CUDA | 12.8 (system) |
| Storage | Root: 1.8 TB NVMe; Data: `/mnt/SSD4T` (3.6 TB, used for all project files) |

**Note on storage:** The root partition was at 100% capacity. All project files, conda environments, model checkpoints, and datasets are placed on `/mnt/SSD4T`.

---

## Directory Layout

```
/mnt/SSD4T/teambruce/
├── projects/
│   └── navila-isaac/
│       ├── NaVILA/               # AnjieCheng/NaVILA (commit 76b98f2)
│       ├── NaVILA-Bench/         # yang-zj1026/VLN-CE-Isaac (commit e9d2db1)
│       ├── IsaacLab/             # yang-zj1026/IsaacLab (commit 4d558ec)
│       └── checkpoints/
│           └── navila-llama3-8b-8f/  # HuggingFace: a8cheng/navila-llama3-8b-8f (16 GB)
├── conda_envs/
│   ├── vlnce-isaac/              # Isaac Sim + IsaacLab environment
│   └── navila-vlm/               # NaVILA VLM server environment
└── conda_pkgs/                   # Conda package cache (redirected from root)
```

---

## Conda Environment Setup

### Configure conda to use SSD4T

```bash
# ~/.condarc
pkgs_dirs:
  - /mnt/SSD4T/teambruce/conda_pkgs
  - /home/teambruce/miniconda3/pkgs
envs_dirs:
  - /mnt/SSD4T/teambruce/conda_envs
  - /home/teambruce/miniconda3/envs
```

### Environment 1: `vlnce-isaac` (Isaac Sim + IsaacLab)

```bash
conda create --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac python=3.10 -y

# Install Isaac Sim 4.1.0.0
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  pip install \
    isaacsim-rl==4.1.0.0 isaacsim-replicator==4.1.0.0 \
    isaacsim-extscache-physics==4.1.0.0 isaacsim-extscache-kit-sdk==4.1.0.0 \
    isaacsim-extscache-kit==4.1.0.0 isaacsim-app==4.1.0.0 \
    --extra-index-url https://pypi.nvidia.com

# Run IsaacLab installer (this downgrades torch to 2.2.2+cu121 — fine on RTX 4090 sm_89)
TERM=xterm conda run --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -i none

# Install rsl_rl and warp
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p -m pip install \
  -e /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/rsl_rl

conda run --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  pip install warp-lang==1.13.0
```

Key versions after install:
- `torch 2.2.2+cu121` (IsaacLab pins this; works on sm_89)
- `isaacsim-app 4.1.0.0`
- `omni-isaac-lab 0.20.8` (yang-zj1026 fork)
- `rsl-rl 2.0.2`
- `warp-lang 1.13.0`

### Environment 2: `navila-vlm` (NaVILA VLM Server)

```bash
conda create --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm python=3.10 -y

# PyTorch (original NaVILA pin — works natively on RTX 4090)
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  pip install torch==2.3.0+cu121 torchvision==0.18.0+cu121 \
  --index-url https://download.pytorch.org/whl/cu121

# FlashAttention 2.5.8 — prebuilt wheel available for sm_89 (Ada Lovelace)
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  pip install https://github.com/Dao-AILab/flash-attention/releases/download/v2.5.8/flash_attn-2.5.8+cu122torch2.3cxx11abiFALSE-cp310-cp310-linux_x86_64.whl

# NaVILA/VILA package
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  pip install -e /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA

# Upgrade bitsandbytes (0.41.0 has API incompatibility with transformers patch)
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  pip install "bitsandbytes>=0.43.0"

# Apply NaVILA transformers patch
SITE=/mnt/SSD4T/teambruce/conda_envs/navila-vlm/lib/python3.10/site-packages/transformers
REPLACE=/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA/llava/train/transformers_replace
cp ${REPLACE}/modeling_utils.py        ${SITE}/modeling_utils.py
cp ${REPLACE}/models/llama/modeling_llama.py   ${SITE}/models/llama/modeling_llama.py
cp ${REPLACE}/models/llama/tokenization_llama.py ${SITE}/models/llama/tokenization_llama.py
cp ${REPLACE}/models/mistral/modeling_mistral.py ${SITE}/models/mistral/modeling_mistral.py
cp ${REPLACE}/models/mixtral/modeling_mixtral.py ${SITE}/models/mixtral/modeling_mixtral.py
```

Key versions:
- `torch 2.3.0+cu121`
- `flash-attn 2.5.8`
- `transformers 4.37.2`
- `bitsandbytes 0.49.2`

---

## Repository Setup

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac

git clone https://github.com/yang-zj1026/VLN-CE-Isaac.git NaVILA-Bench
git clone https://github.com/yang-zj1026/IsaacLab.git IsaacLab
git clone https://github.com/AnjieCheng/NaVILA.git NaVILA

# IsaacLab extension symlinks
ln -sf $(pwd)/NaVILA-Bench/isaaclab_exts/omni.isaac.vlnce \
       IsaacLab/source/extensions/omni.isaac.vlnce
ln -sf $(pwd)/NaVILA-Bench/isaaclab_exts/omni.isaac.matterport \
       IsaacLab/source/extensions/omni.isaac.matterport
```

---

## Data & Assets

### NaVILA Checkpoint

```bash
mkdir -p /mnt/SSD4T/teambruce/projects/navila-isaac/checkpoints
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  huggingface-cli download a8cheng/navila-llama3-8b-8f \
  --local-dir /mnt/SSD4T/teambruce/projects/navila-isaac/checkpoints/navila-llama3-8b-8f
```

Size: ~16 GB (4 safetensors shards).

### VLN-CE-Isaac Assets (Matterport USD + Annotations)

```bash
conda run --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  huggingface-cli download Zhaojing/VLN-CE-Isaac \
  --repo-type dataset \
  --local-dir /mnt/SSD4T/teambruce/projects/navila-isaac/vlnce_assets

ASSETS=/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/isaaclab_exts/omni.isaac.vlnce/assets
mkdir -p ${ASSETS}
cp vlnce_assets/vln_ce_isaac_v1.json.gz ${ASSETS}/
unzip -q vlnce_assets/matterport_usd.zip -d ${ASSETS}/
# Result: 91 Matterport scene directories
```

Low-level policy checkpoints for Go2 and H1 are bundled in the `NaVILA-Bench/logs/` directory (included in the git repo).

---

## Patches Required

The following patches were necessary to run on this setup. All are due to version mismatches between NaVILA's pinned dependencies and current library releases — none are RTX 4090 / Ada Lovelace specific.

### 1. `NaVILA/llava/train/sequence_parallel/globals.py`
**Issue:** Hard import of `deepspeed` fails when DeepSpeed is not installed (evaluation-only setup).
```python
# Before
import deepspeed.comm as dist

# After
import torch
try:
    import deepspeed.comm as dist
except ImportError:
    import torch.distributed as dist
```

### 2. `NaVILA/llava/model/builder.py`
**Issue:** `load_8bit=True` skips setting `torch_dtype`, but `prepare_config_for_eval()` always pops it → `KeyError`.
```python
# After (line 44-46)
if load_8bit:
    kwargs["load_in_8bit"] = True
    kwargs["torch_dtype"] = torch.float16  # ← added
```

### 3. `transformers/modeling_utils.py` (in conda env site-packages AND NaVILA repo)
**Issue:** NaVILA's transformers patch calls `set_module_quantized_tensor_to_device(..., fp16_statistics=...)`, but the current transformers renamed this parameter to `quantized_stats`.
```python
# Before
set_module_quantized_tensor_to_device(model, param_name, param_device, value=param, fp16_statistics=fp16_statistics)

# After
set_module_quantized_tensor_to_device(model, param_name, param_device, value=param, quantized_stats=fp16_statistics)
```
Apply to both:
- `conda_envs/navila-vlm/lib/python3.10/site-packages/transformers/modeling_utils.py`
- `NaVILA/llava/train/transformers_replace/modeling_utils.py`

### 4. `NaVILA-Bench/scripts/vlm_server.py`
**Issue (a):** `args.model_path` references the global `args` instead of `self.args` → `NameError`.  
**Issue (b):** Calling `self.model.to(device)` after loading with `device_map` causes meta tensor error.  
**Fix:** Use `self.args.model_path`, pass explicit `device_map={"": device}`, remove redundant `.to()`.  
**Added:** `--load_8bit` flag, `--max_new_tokens` flag, `pad_token_id` in generate call.

### 5. `NaVILA-Bench/scripts/navila_eval.py`
**Issue:** PIL JPEG encoding (`pil_image.save(..., format="JPEG")`) crashes inside Isaac Sim due to bundled PIL version conflict with conda env's Pillow.  
**Fix:** Replace with OpenCV encoding:
```python
import cv2
np_bgr = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
_, buf = cv2.imencode(".jpg", np_bgr)
encoded_images.append(base64.b64encode(buf.tobytes()).decode())
```

### 6. `vlnce-isaac` conda env `PIL/_util.py`
**Issue:** Isaac's bundled `PIL/ImageFont.py` calls `PIL._util.is_directory()`, which doesn't exist in Pillow 11.x+.  
**Fix:** Add the function:
```python
def is_directory(f):
    return isinstance(f, (bytes, str, os.PathLike)) and os.path.isdir(f)
```

### 7. Isaac bundled `botocore/httpchecksum.py`
**Path:** `.../isaacsim/extscache/omni.kit.pip_archive/pip_prebundle/botocore/httpchecksum.py`  
**Issue:** The conda env's `s3transfer` imports `DEFAULT_CHECKSUM_ALGORITHM` from botocore, but Isaac's bundled botocore is too old to have it. This caused `omni.replicator.core` to fail loading, breaking camera sensor initialization.  
**Fix:** Add the constant to Isaac's bundled botocore:
```python
DEFAULT_CHECKSUM_ALGORITHM = "crc32"
```

---

## Running the Evaluation

Requires two terminals.

### Terminal 1 — VLM Server

```bash
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/navila-vlm \
  python /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/vlm_server.py \
  --model_path /mnt/SSD4T/teambruce/projects/navila-isaac/checkpoints/navila-llama3-8b-8f \
  --port 54321 \
  --load_8bit
```

Wait until the port is listening:
```bash
ss -tlnp | grep 54321
```

### Terminal 2 — Isaac Evaluation

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && \
OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/navila_eval.py \
  --task=go2_matterport_vision \
  --num_envs=1 \
  --history_length=9 \
  --load_run=2024-09-25_23-22-02 \
  --headless \
  --enable_cameras \
  --episode_idx=0
```

Results saved to: `eval_results/go2_matterport_vision_loco_2024-09-25_23-22-02/`

### VRAM Usage (RTX 4090, 24 GB)

| Component | VRAM |
|---|---|
| VLM server (8-bit) | ~10 GB |
| Isaac Sim + camera rendering | ~8 GB |
| **Total** | **~18 GB / 24 GB** |

---

## Results

### Episode 0 — `go2_matterport_vision`

```json
{
    "path_length": 8.977,
    "distance_to_goal": 0.787,
    "success": 1.0,
    "spl": 0.907,
    "oracle_navigation_error": 0.203,
    "oracle_success": 1.0
}
```

**success = 1.0, SPL = 0.907** — the Go2 robot successfully navigated to the goal following NaVILA's language-conditioned commands.

---

## Project Progress Log

### 2026-06-05 — Language-Only Round-Trip Baseline

After confirming the baseline NaVILA + Isaac Sim VLN-CE deployment on six episodes, the next project stage is to construct a single-episode long-horizon task with an Outbound -> Confirm -> Return structure.

Implemented a language-only round-trip baseline evaluator:

```text
code/round_trip_eval.py
```

The working copy in the Isaac project is:

```text
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/round_trip_eval.py
```

This baseline intentionally does not use route memory, anchors, template inversion, geometric hints, or fallback control. It only tests whether NaVILA can execute a continuous long-horizon round-trip task from language.

Supported modes:

- `static_long_instruction`: NaVILA always receives one complete outbound-confirm-return instruction from the first step onward.
- `phase_prompt`: the evaluator provides phase-specific language prompts for Outbound and Return, but still provides no route-memory or geometric information.

Current behavior:

- Converts the original single-trip VLN-CE instruction into a round-trip instruction.
- Interprets the first NaVILA `stop` during Outbound as a phase transition rather than ending the episode.
- Runs a scripted Confirm phase as a 360-degree scan.
- Continues into a Return phase inside the same simulator episode.
- Evaluates return success by distance to the original starting point.
- Saves stop events, phase events, generated instructions, outbound success, return distance-to-start, return success, and round-trip success into the measurement JSON.
- Writes results under `eval_results/round_trip_<mode>_<task>_loco_<run>/` so modes and baseline results are not overwritten.

Run command for Baseline A, the strict long-instruction version:

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && \
OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision \
  --num_envs=1 \
  --history_length=9 \
  --load_run=2024-09-25_23-22-02 \
  --headless \
  --enable_cameras \
  --round_trip_mode=static_long_instruction \
  --episode_idx=0
```

Run command for Baseline B, the phase-prompt language-only version:

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && \
OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision \
  --num_envs=1 \
  --history_length=9 \
  --load_run=2024-09-25_23-22-02 \
  --headless \
  --enable_cameras \
  --round_trip_mode=phase_prompt \
  --episode_idx=0
```

The next technical steps are:

- Run both baseline modes with GPU access and compare behavior.
- Decide whether `static_long_instruction` is too strict for NaVILA's original single-trip training distribution.
- Use the stronger language-only baseline as the comparison target for the later external-memory agent.
- Only after this baseline is measured, add route-template memory, geometric hints, and fallback control as the proposed method.

### 2026-06-05 — First `phase_prompt` Round-Trip Test

Ran `phase_prompt` on `go2_matterport_vision`, episode 0.

Artifacts:

```text
results/round_trip_phase_prompt_episode0/
├── output_0.mp4
├── measurement_raw_before_outbound_success_fix.json
└── summary.md
```

Observed behavior:

- Outbound reached the original target region and NaVILA emitted `stop`.
- The evaluator transitioned from Outbound to scripted Confirm, then into Return inside the same simulator episode.
- Return did not reach the original starting point.

Key numbers:

```text
outbound stop step: 1200
outbound stop distance to goal: 0.493 m
outbound goal radius: 3.0 m
outbound success: true by distance threshold
return success: false
round-trip success: false
final distance to start: 8.523 m
final distance to outbound goal: 2.974 m
```

Important evaluator fix:

The raw JSON from this first run records `round_trip.outbound_success=false`, but this is a logging bug: the evaluator inferred outbound success from the final post-return measurement. The code has been fixed so that outbound success is computed at the first outbound `stop` using the outbound goal radius.

### 2026-06-05 — Second `phase_prompt` Run After Evaluator Fix

Ran `phase_prompt` again on `go2_matterport_vision`, episode 0, after fixing outbound-success logging.

Artifacts:

```text
results/round_trip_phase_prompt_episode0_run2/
├── output_0.mp4
├── measurement.json
└── summary.md
```

Key numbers:

```text
outbound stop step: 1425
outbound stop distance to goal: 0.780 m
outbound goal radius: 3.0 m
outbound success: true
return stop step: 4801
return stop distance to start: 6.055 m
final distance to start: 6.062 m
return success: false
round-trip success: false
top-level path length: 29.794 m
```

Interpretation:

The phase-prompt baseline can complete the outbound portion and transition through Confirm into Return, but it still fails the return-to-start objective. In this run, NaVILA stopped during Return while still about 6 m from the original start. This supports keeping `phase_prompt` as a language-only baseline before adding the external route-memory agent.

### 2026-06-06 — Return-Failure Diagnosis

Reviewed both `phase_prompt` runs using the saved command events, measurements, and videos.

Findings:

- All Return-phase NaVILA outputs were parseable navigation commands; neither run failed because of an invalid-language-output fallback.
- The robot did not remain physically stuck for a prolonged period.
- Run 1 stayed mainly around the living-room area and timed out without returning.
- Run 2 entered a corridor, later selected an incorrect direction, returned toward the living-room area, and emitted `stop` while still about `6.06 m` from the start.
- The second run therefore shows both route-selection/re-localization failure and incorrect task-completion judgment.

The existing logs do not contain a full per-step pose trajectory, so they cannot yet distinguish gradual geometric drift from a discrete wrong turn at a junction. A later baseline instrumentation update should record pose, heading, distance to the reversed reference path, along-path progress, commanded motion, and executed motion.

### 2026-06-06 — Explicit Reverse-Instruction Generator

Added an offline instruction-rewriting module to the working NaVILA-Bench project:

```text
scripts/instruction_rewriter.py
tests/test_instruction_rewriter.py
```

The module:

- accepts an episode's original outbound instruction;
- asks a local or OpenAI-compatible LLM for an independently executable Return instruction;
- requires JSON output;
- reverses landmark/route order and directional actions through prompt constraints;
- rejects unchanged, empty, refusal, and obvious stop-first outputs;
- caches the generated instruction so benchmark runs are deterministic;
- supports `cache_only` evaluation, keeping the instruction-generation LLM outside the navigation loop.

The initial `llama3.2` generation was rejected during manual review because it reversed landmark order incorrectly and introduced ambiguous room transitions. The prompt was strengthened and versioned as `round-trip-rewriter-v2`. A second generation using local `qwen2.5vl:7b` produced:

```text
Outbound:
Exit the bedroom and turn left. Walk straight passing the gray couch
and stop near the rug.

Return:
From the rug, walk back past the gray couch. Turn right, enter the bedroom,
and stop at the original starting location.
```

Five unit tests currently cover generation, caching, cache-only loading, unchanged-output rejection, and rejection of an outbound `stop` repeated as the first Return action.

Important limitation:

The current generator validates format and several obvious logical errors, but it does **not** mathematically prove that an LLM-generated reverse instruction is geometrically correct. Sparse source instructions may omit junctions, landmark-side relations, or the exact visual identity of the starting location. Generated instructions must therefore remain versioned and manually reviewed before benchmark use.

Planned correction work:

- parse the outbound instruction into structured route steps;
- mechanically reverse step order and invert directional relations;
- validate landmark order with a second pass;
- use the episode reference path and heading to check turn geometry;
- record an explicit human-review status in the cache and measurement JSON.

### 2026-06-06 — Explicit Reverse-Instruction Baseline Test

Checked system resources before the run:

```text
GPU: RTX 4090, approximately 23.6 GB VRAM free before loading models
System memory: approximately 117 GB available
SSD4T: approximately 2.7 TB available
```

Ran Episode 0 in `phase_prompt` mode using the reviewed `qwen2.5vl:7b` reverse instruction from the deterministic cache. The result directory used the suffix `explicit_reverse_v2` so the previous runs were not overwritten.

Key results:

```text
outbound stop step: 1200
outbound stop distance to goal: 0.529 m
outbound success: true
return stop step: 4976
return stop distance to start: 11.279 m
final distance to start: 11.281 m
return success: false
round-trip success: false
```

Observed behavior:

- The explicit instruction changed the Return behavior: the robot left the living-room region and entered a long corridor.
- It entered the wrong part of the environment, continued issuing valid movement commands, and finally emitted `stop` far from the original start.
- This run demonstrates that replacing the abstract “retrace the route” prompt with a manually reviewed, explicit reverse instruction is not sufficient by itself.
- The result is consistent with failures in visual re-localization, junction selection, route-progress estimation, and stop judgment.

This remains a language-only baseline. It still uses no route memory, anchor matching, geometric hints, template inversion, or fallback controller.

Operational note:

After Isaac Sim shut down, `nvidia-smi` temporarily lost communication with NVML even though the NVIDIA kernel modules remained loaded and no NVIDIA Xid entry was found in the checked kernel-log window. GPU/driver health should be confirmed before another simulation run.

### 2026-06-06 — Strict Long-Instruction Baseline

After GPU/NVML communication recovered, ran Episode 0 in `static_long_instruction` mode using the same cached `qwen2.5vl:7b` outbound + explicit Return instruction.

Key results:

```text
outbound success: false
return started: false
closest outbound distance to goal: 0.143 m
final distance to outbound goal: 3.004 m
final distance to start: 8.410 m
path length: 13.854 m
stop events: 0
outbound timeout: approximately 50 seconds
```

Observed behavior:

- The robot correctly left the bedroom and entered the living-room area.
- It passed through the target region and came within `0.143 m` of the outbound goal.
- NaVILA did not emit `stop`, so the evaluator never transitioned to Confirm or Return.
- It continued navigating and moved away from the outbound target until timeout.

Interpretation:

This is a subtask-boundary or phase-transition failure. Under the full combined instruction, NaVILA failed to recognize that the outbound subtask had finished. This run does not measure reverse-route ability because Return never started.

Result directory:

```text
eval_results/round_trip_static_long_instruction_go2_matterport_vision_loco_2024-09-25_23-22-02_strict_explicit_reverse_v2/
```

### 2026-06-06 — Controlled Phase-Prompt Return Diagnosis

Added reusable diagnostic controls to `round_trip_eval.py`:

```text
--return_instruction_file=<path>
--return_instruction_override=<text>
--oracle_return_pose
```

The evaluator now records the natural Return pose, optional expert-corrected pose, selected Return instruction, and phase-transition events. `--oracle_return_pose` places the robot at the expert outbound endpoint and faces it toward the previous expert waypoint when Return begins.

Three Episode 0 conditions were compared:

| Return condition | Outbound | Return | Final distance to start |
|---|---:|---:|---:|
| Generated reverse instruction + natural pose | Success | Failure | `11.281 m` |
| Human Oracle instruction + natural pose | Success | Success | `1.995 m` |
| Human Oracle instruction + expert pose | Success | Success | `1.992 m` |

The human Oracle Return instruction was:

```text
From the rug, turn around. Retrace the route past the gray couch and continue straight back
toward the bedroom doorway. Turn right through the doorway into the bedroom and stop at the
original starting position inside the bedroom. Do not stop before reaching the bedroom.
```

Additional observations:

- The natural-pose Oracle run began Return approximately `1.01 m` from the expert endpoint and still succeeded.
- Both Oracle-instruction runs entered the configured `2.0 m` Return success radius.
- The expert-pose run reproduced the original successful outbound stop distance of `0.529 m` before pose correction.
- An initial expert-pose implementation exposed an inference-tensor refresh bug; the invalid run was discarded, the history-buffer reset was fixed, and the corrected `oracle_instruction_pose_v2` run completed normally.

Revised conclusion (updated 2026-06-06):

The Oracle instruction successes are methodologically invalid as evidence for NaVILA's round-trip capability. The Oracle instruction adds spatial detail that is absent from the original outbound instruction ("turn around", "Do not stop before reaching the bedroom", explicit doorway language), making it a strictly easier task. A scientifically valid baseline requires a reverse instruction at the same level of specificity as the original. See the 2026-06-06 Instruction Rewriter v3 entry below.

Relevant result directories:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_explicit_reverse_v2/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_oracle_instruction_v1/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_oracle_instruction_pose_v2/
```

### 2026-06-06 — Instruction Rewriter Upgraded to v3 (Parse → Mechanical Invert → Render)

The one-step LLM generation pipeline (`round-trip-rewriter-v2`) was replaced with a three-step pipeline that separates logic from language:

1. **Parse** — LLM converts the outbound instruction into a structured step sequence (JSON).
2. **Mechanical invert** — deterministic Python code reverses step order and applies fixed rules: `left ↔ right`, `exit_room ↔ enter_room`, landmark order guaranteed by code.
3. **Render** — LLM converts the inverted step sequence back to natural language at the same level of specificity as the original.

The motivation is to eliminate instruction logic errors (wrong landmark order, un-inverted turn directions) as a confounding variable, while keeping the generated instruction at the same granularity as the original outbound instruction. Adding detail beyond the original (e.g. "turn around", explicit stop constraints) would reduce task difficulty and invalidate the comparison.

The v2 pipeline depended on the LLM to get both the spatial inversion logic and the language rendering correct in a single step. The v3 pipeline guarantees structural correctness by code and uses the LLM only for parsing and rendering.

Files changed:

```text
scripts/instruction_rewriter.py   (PROMPT_VERSION → round-trip-rewriter-v3)
tests/test_instruction_rewriter.py (10 tests, all passing)
```

Episode 0 v3 generated return instruction (qwen2.5vl:7b):

```text
From the rug, move straight to the gray couch, turn right, and enter the bedroom. Stop at the bedroom.
```

### 2026-06-06 — Training Coverage Diagnosis: Reverse-Direction Episode Test

**Research question:** Is the return-phase failure caused by (H1) insufficient training coverage of the reverse route direction, or (H2) a structural limitation specific to the round-trip context?

**Method:** Search the VLN-CE-Isaac dataset for episodes in the same scene (`zsNo4HB9uLZ`) whose outbound path traverses the same waypoints as episode 0's return path, in the reverse direction.

**Finding:** Episodes 1198, 1199, and 1200 share the identical waypoint sequence with episode 0's return path (5/5 waypoints within 2 m), traveling from the corridor near the rug toward the bedroom. Their array indices in the dataset are 705, 706, and 707.

| | Episode 0 outbound | Episodes 1198–1200 outbound |
|---|---|---|
| Start | Bedroom `(15.07, 4.48)` | Corridor `(12.86, 0.07)` |
| Goal | Rug area `(13.05, -1.87)` | Bedroom `(15.07, 4.48)` |
| Direction | Bedroom → Rug | Corridor → Bedroom (= episode 0 return direction) |
| Waypoint overlap | — | 5 / 5 |

**Result:** Episode 705 (`episode_id=1198`, instruction: "Walk straight into the hallway. Turn right and go into the room. Wait near the door on the left.") evaluated with standard `navila_eval.py`:

```json
{
    "path_length": 7.630,
    "distance_to_goal": 1.080,
    "success": 1.0,
    "spl": 0.807,
    "oracle_navigation_error": 0.159,
    "oracle_success": 1.0
}
```

**Conclusion:** NaVILA achieves `success = 1.0` on the reverse-direction path as a standard outbound episode. This directly rules out H1: the training distribution covers this path direction, and the model has the capability to navigate it. The return failure in the round-trip evaluation is therefore a structural problem specific to the round-trip context — not a training coverage gap. This is the key result justifying the need for an external route-memory mechanism rather than simply adding more training data.

Result file:

```text
eval_results/go2_matterport_vision_loco_2024-09-25_23-22-02/measurements/1197.json
```

### 2026-06-16 - Return-Failure Ablations: Pose Drift vs Instruction Quality

Ran a focused set of Episode 0 round-trip ablations to separate three possible causes of Return failure:

1. accumulated outbound pose drift at the start of Return;
2. quality and training-distribution fit of the generated reverse instruction;
3. the round-trip context itself, including phase transition, visual history, and stop judgment.

All runs used the same language-only `phase_prompt` round-trip evaluator and no route memory, anchor matching, geometric hints, or fallback controller unless explicitly noted. The standard v3 reverse instruction was:

```text
From the rug, move straight to the gray couch, turn right, and enter the bedroom. Stop at the bedroom. This is the return phase. Stop only when you have reached the original starting location.
```

The retrieved reverse-direction dataset instruction from Episode 705 / `episode_id=1198` was:

```text
Walk straight into the hallway. Turn right and go into the room. Wait near the door on the left.
```

#### Round-trip: v3 reverse instruction vs oracle Return pose

| Condition | Outbound | Return | Final distance to start | Return-start pose error |
|---|---:|---:|---:|---:|
| v3 reverse instruction + natural Return pose | true | false | `11.213 m` | XY `0.300 m`, yaw `-46.4 deg` |
| v3 reverse instruction + oracle Return pose | true | false | `10.029 m` | after reset: XY `0.000 m`, yaw `0.0 deg` |

Key observation: oracle Return pose reset worked exactly, but did not recover success. This means accumulated outbound pose drift is not by itself a sufficient explanation for Return failure.

#### Same reverse path as a normal single-trip episode

Used Episode 705 (`episode_id=1198`) in the same scene (`zsNo4HB9uLZ`). This episode follows the reverse direction of Episode 0's Return path as a normal VLN task.

| Single-trip condition on Episode 705 | Success | SPL | Distance to goal |
|---|---:|---:|---:|
| Original Episode 705 instruction | `1.0` | `0.892` | `0.317 m` |
| Episode 0 v3 reverse instruction used as override | `0.0` | `0.000` | `17.740 m` |

Key observation: NaVILA succeeds on this reverse-direction route with the dataset's natural instruction, but fails badly when the v3 reverse instruction is used as the user instruction. This shows reverse-instruction wording and training-distribution fit are a major confound.

#### Round-trip using Episode 705's natural instruction as Return instruction

| Condition | Outbound | Return | Final distance to start | Termination |
|---|---:|---:|---:|---|
| Episode 705 instruction + natural Return pose | true | false | `3.532 m` | Return stop at `3.532 m` |
| Episode 705 instruction + oracle Return pose | true | false | `11.351 m` | Return stop at `11.351 m` |

Replacing the v3 reverse instruction with Episode 705's natural instruction improved the natural-pose Return substantially (`11.21 m` -> `3.53 m` from start), but still did not enter the configured `2.0 m` success radius. Adding oracle Return pose to the Episode 705 instruction did not help in this run.

Current interpretation:

- v3 reverse-instruction quality is insufficient and materially worsens Return behavior.
- Pose drift exists, especially heading error at Return start, but correcting the Return pose alone does not restore success.
- Round-trip context remains a separate failure factor: phase transition, accumulated visual history, current-view mismatch, and premature stop judgment can still break Return even with a dataset instruction that succeeds as a clean single-trip episode.

Result directories:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_drift_natural_ep0_v3/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_drift_oracle_pose_ep0_v3/
eval_results/go2_matterport_vision_loco_2024-09-25_23-22-02_ep1198_original_instruction/
eval_results/go2_matterport_vision_loco_2024-09-25_23-22-02_ep1198_episode0_v3_return_instruction/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_drift_natural_ep0_ep705_return_instruction/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_drift_oracle_pose_ep0_ep705_return_instruction/
```

### 2026-06-16 - Instruction Rewriter v4: Dataset Reverse-Path Retrieval

Upgraded the reverse-instruction generator from v3 to v4.

Previous v3 behavior:

- parsed the outbound instruction;
- mechanically inverted the parsed route;
- rendered a reverse instruction with an LLM;
- for Episode 0 produced the weak instruction beginning with `From the rug...`.

Problem identified by ablations:

- the v3 instruction failed even as a clean single-trip override on Episode 705;
- the dataset's natural reverse-direction instruction succeeded on that same route;
- therefore the reverse instruction must be treated as a real experimental variable, not as a solved preprocessing step.

New v4 behavior:

1. Given the current dataset path and episode index, search the same scene for episodes whose reference path overlaps the current episode's Return path in reverse order.
2. Rank candidates by matched waypoints, path-length agreement, coverage, mean waypoint distance, and dataset index.
3. If a strong reverse-path neighbor exists, use that episode's original VLN instruction as the Return instruction.
4. If no neighbor exists, fall back to the parse -> mechanical invert -> render pipeline.

For Episode 0, v4 retrieves:

```text
episode_index=705; episode_id=1198; matched_waypoints=5; mean_distance_m=0.000
```

and uses:

```text
Walk straight into the hallway. Turn right and go into the room. Wait near the door on the left.
```

The cache was updated with a `round-trip-rewriter-v4` entry, so `--instruction_rewriter_provider=cache_only` now resolves Episode 0 to the dataset reverse-path instruction when dataset context is available.

Implementation notes:

```text
scripts/instruction_rewriter.py    # v4 retrieval + fallback generator
scripts/round_trip_eval.py         # passes dataset path and episode index into InstructionRewriter
tests/test_instruction_rewriter.py # 11 tests passing, including reverse-path retrieval ranking
```

### 2026-06-16 - Per-Step Trajectory Logging and Stronger Oracle Reset

Added per-step trajectory logging to the round-trip evaluator so every completed run can be diagnosed from a JSONL trajectory file rather than only from final measurements.

Each round-trip measurement now records:

```text
round_trip.trajectory_file
round_trip.trajectory_record_count
```

Each trajectory record includes:

- step index and current phase;
- robot position, quaternion, yaw, root velocity, and planar speed;
- active high-level command and latest VLM output;
- distance to the original start and outbound goal;
- nearest point on the outbound reference path and reversed return path.

Also strengthened `--oracle_return_pose`. It now resets more than just the robot pose:

- writes the expert return-start pose and zero root velocity;
- clears low-level proprioceptive history;
- rebuilds low-level observations as normal writable tensors;
- clears stop/same-position state;
- clears the VLM image history;
- forces the first Return VLM query to use a fresh post-reset camera frame.

Two implementation bugs were exposed and fixed while validating this:

1. The local IsaacLab `SimulationContext` does not expose `write_data_to_sim()`, so the call is now version-gated.
2. Rebuilding low-level observations inside `torch.inference_mode()` created inference tensors that the VLN wrapper could not update in place. The refresh path now temporarily disables inference mode and clones detached tensors.

#### v4 rerun with trajectory logging

Both runs used Episode 0, `phase_prompt`, `cache_only`, and the v4 dataset reverse-path instruction retrieved from Episode 705:

```text
Walk straight into the hallway. Turn right and go into the room. Wait near the door on the left.
```

| Condition | Outbound | Return | Round trip | Final distance to start | Trajectory records |
|---|---:|---:|---:|---:|---:|
| v4 baseline, natural Return pose | true | true | true | `1.995 m` | `2963` |
| v4 baseline + stronger oracle reset | true | false | false | `13.295 m` | `3152` |

Baseline details:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_traj_baseline_ep0/
measurements/0.json
trajectories/output_0.jsonl
```

- `instruction_rewriter_provider`: `dataset_reverse_path_neighbor`
- `instruction_rewriter_model`: `episode_index=705;episode_id=1198;matched_waypoints=5;mean_distance_m=0.000`
- outbound stop distance to goal: `0.195 m`
- Return-start pose error before oracle correction: XY `0.456 m`, yaw `-72.6 deg`
- final distance to start: `1.995 m`, inside the configured `2.0 m` success radius

Oracle-reset details:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_traj_oracle_reset_ep0/
measurements/0.json
trajectories/output_0.jsonl
```

- oracle reset itself was exact: post-reset XY error `0.000 m`, z error `0.000 m`, yaw error `0.0 deg`
- Return began near the reversed reference path: trajectory sample at Return start had nearest-return-path distance `0.063 m`
- Return initially moved closer to start (`6.673 m` -> `5.691 m`), then drifted away (`9.096 m`, `12.101 m`) and finally stopped at `13.295 m`

Current interpretation:

- The v4 instruction fix is material: the natural-pose v4 baseline succeeded where earlier v3 variants failed.
- The stronger oracle reset now cleanly isolates robot pose, low-level history, VLM visual history, and stop/memory state at Return transition.
- Because oracle reset was exact but the Return trajectory still diverged after the reset, this failure is not explained by accumulated outbound pose drift alone. The per-step log points to post-reset Return-phase visual decision/control drift or stop judgment as the next target.

### 2026-06-16 - v4 Baseline Stability and Random-Episode Generalization

After the first v4 Episode 0 baseline succeeded just inside the configured `2.0 m` return-success radius, repeated the same language-only baseline to check whether that success was a one-off stochastic result.

All runs used Episode 0, `phase_prompt`, `cache_only`, and the v4 dataset reverse-path instruction retrieved from Episode 705.

| Run set | Runs | Round-trip success | Final distance to start |
|---|---:|---:|---|
| Original v4 baseline + 5 repeats | 6 | 6 / 6 | `1.995 m` to `2.000 m` |

Repeat-run observations:

- The Episode 0 v4 baseline success is reproducible across six total runs.
- The margin is extremely narrow: the final distance is consistently just inside the `2.0 m` success threshold.
- Several runs are bitwise-identical or nearly identical, while two repeats used a slightly different outbound stop pose and still ended inside the threshold.

Representative result directories:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_traj_baseline_ep0/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_repeat_baseline_ep0_r1/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_repeat_baseline_ep0_r2/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_repeat_baseline_ep0_r3/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_repeat_baseline_ep0_r4/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_repeat_baseline_ep0_r5/
```

Then stopped testing Episode 0 and sampled three different episodes from `vln_ce_isaac_v1.json.gz`, restricted to cases where v4 could retrieve a reverse-path neighbor from the dataset.

| episode_idx | episode_id | scene | Reverse-neighbor source | Outbound | Return | Round trip | Final distance to start |
|---:|---:|---|---|---:|---:|---:|---:|
| 189 | 286 | `2azQ1b91cZZ` | episode_idx `696`, 4 matched waypoints, mean distance `0.000 m` | true | false | false | `7.217 m` |
| 278 | 444 | `EU6Fwq7SyZv` | episode_idx `888`, 4 matched waypoints, mean distance `0.261 m` | false | false | false | `1.173 m` |
| 799 | 1361 | `zsNo4HB9uLZ` | episode_idx `393`, 5 matched waypoints, mean distance `0.000 m` | false | false | false | `5.932 m` |

Per-episode notes:

- Episode 189 completed Outbound and entered Return, but never got close to the start. During Return its best distance to start was about `6.19 m`, and it stopped at about `7.21 m`.
- Episode 278 failed before Return. It remained in the Outbound phase and eventually hit the same-location/stuck guard, with final distance to outbound goal `9.954 m`.
- Episode 799 also failed before Return. It continued issuing movement/turn commands but did not produce a successful outbound stop, ending `2.104 m` from the outbound goal.

Random-episode result directories:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep189/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep278/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep799/
```

Current interpretation:

- Episode 0 is a favorable narrow-margin case rather than a generally representative round-trip success.
- On random episodes, many failures happen before Return because Outbound itself does not reliably terminate successfully.
- For return-specific diagnosis, future tests should either pre-screen for episodes with stable Outbound success or use an oracle Return-start setup to isolate the Return leg from Outbound failure.

### 2026-06-17 — v4 Baseline: 5 New Random Episodes Across 5 Scenes

Ran 5 new episodes sampled from the v4-eligible pool (episodes that have at least one reverse-path neighbor in the same scene). Selected one best candidate per scene, prioritising highest matched-waypoint count and lowest mean path distance. All runs used `phase_prompt` mode and `cache_only` instruction provider (v4 dataset reverse-path retrieval).

System state before run: GPU 24018 MB VRAM free, RAM 120 GB available, SSD4T 2.7 TB available.

| ep_idx | ep_id | scene | Reverse-neighbor source | Outbound | Return | Round trip | Final distance to start |
|---:|---:|---|---|---:|---:|---:|---:|
| 366 | 601 | `X7HyMhZNoso` | ep_idx=1038, ep_id=1759, 7 matched, mean 0.000 m | true | false | false | `7.441 m` (timeout) |
| 105 | 151 | `QUCTc6BB5sX` | ep_idx=993, ep_id=1699, 7 matched, mean 0.000 m | true | true | **true** | `1.997 m` |
| 3 | 7 | `x8F5xyUWy9e` | ep_idx=354, ep_id=583, 5 matched, mean 0.000 m | false* | true | false | `1.997 m` |
| 132 | 193 | `2azQ1b91cZZ` | ep_idx=756, ep_id=1288, 7 matched, mean 0.258 m | false | — | false | — |
| 612 | 1069 | `zsNo4HB9uLZ` | ep_idx=678, ep_id=1165, 7 matched, mean 0.000 m | false | — | false | — |

*ep3 outbound stopped at 3.919 m, marginally outside the 3.0 m goal radius.

Per-episode notes:

- **Episode 366 (X7HyMhZNoso):** Outbound completed successfully (stopped at 2.456 m from goal). During Return, the robot became stuck in alternating left/right 45-degree turns from approximately step 3750 onward, timed out at step 7051 with distance to start 7.441 m. Classic Return visual-decision failure with no forward progress.

- **Episode 105 (QUCTc6BB5sX):** Full round-trip success. Outbound stopped cleanly at 1.186 m from goal. Return distance improved continuously from 11.875 m → 9.822 m → 6.861 m → 3.019 m across 500-step checkpoints. Final distance to start: 1.997 m (inside 2.0 m radius).

- **Episode 3 (x8F5xyUWy9e):** Anomalous result. Outbound formally failed (stopped at 3.919 m, just outside the 3.0 m goal radius) but Return still succeeded (final distance 1.997 m). The robot reached the outbound target area closely enough to execute a successful Return despite the formal outbound failure. This round-trip is counted as a failure (outbound unconfirmed), but it suggests Return capability in this episode is robust even from a slightly incorrect outbound endpoint.

- **Episode 132 (2azQ1b91cZZ):** Outbound never emitted a stop; the episode timed out in the outbound phase at 5.421 m from original start. Return never started.

- **Episode 612 (zsNo4HB9uLZ):** Same failure mode as ep132 — outbound timeout without stop, Return never started. Final position was 2.962 m from the original start (still in outbound phase).

Updated cumulative results across all random episodes tested with v4 (excluding the 6 Episode 0 stability runs):

| ep_idx | scene | Outbound | Return | Round trip | Final dist to start |
|---:|---|---:|---:|---:|---:|
| 189 | `2azQ1b91cZZ` | true | false | false | `7.217 m` |
| 278 | `EU6Fwq7SyZv` | false | — | false | — |
| 799 | `zsNo4HB9uLZ` | false | — | false | — |
| 366 | `X7HyMhZNoso` | true | false | false | `7.441 m` |
| 105 | `QUCTc6BB5sX` | true | true | **true** | `1.997 m` |
| 3 | `x8F5xyUWy9e` | false* | true | false | `1.997 m` |
| 132 | `2azQ1b91cZZ` | false | — | false | — |
| 612 | `zsNo4HB9uLZ` | false | — | false | — |

Round-trip success rate on random episodes: **1 / 8 (12.5%)**, versus 6 / 6 for the Episode 0 stability set. Both confirmed successes (ep0 and ep105) ended just inside the 2.0 m threshold (1.995–1.997 m), suggesting they are near-threshold cases rather than comfortable successes. Outbound failure is the dominant blocker: 5 of 8 random episodes failed before Return started.

Result directories:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep366/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep105/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep3/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep132/
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_v4_random_baseline_ep612/
```


### 2026-06-18 — v4 Baseline: 30 Additional Reverse-Path Episodes

Ran two new automatic serial batches with `phase_prompt` mode and `cache_only` v4 dataset reverse-path retrieval. The batch runner started the next episode automatically after each run completed; no manual intervention was required after launch. All 30 runs exited with code `0`.

Batch scripts and local summaries:

```text
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/run_v4_batch_10_20260618.sh
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/run_v4_batch_20_20260618.sh
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/v4_batch_10_20260618/summary.tsv
/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/v4_batch_20_20260618/summary.tsv
```

Aggregate results across the 30 new runs:

- Outbound success: **14 / 30**
- Return success: **5 / 30**
- Full round-trip success: **3 / 30**
- Outbound-success per-step trajectory logs uploaded: **14 JSONL files** under `results/per_step_logs/v4_batch_20260618_outbound_success/`

| Batch | Runs | Outbound | Return | Round trip |
|---|---:|---:|---:|---:|
| Batch A: 10 episodes | 10 | 3 | 2 | 0 |
| Batch B: 20 episodes | 20 | 11 | 3 | 3 |
| **Combined** | **30** | **14** | **5** | **3** |

Per-episode results:

| Batch | ep_idx | ep_id | scene | Reverse-neighbor source | Outbound | Return | Round trip | Final distance to start | Outbound stop distance to goal | Trajectory records | Uploaded trajectory log |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| Batch A: 10 episodes | 106 | 152 | `QUCTc6BB5sX` | ep_idx=993, ep_id=1699, 7 matched, mean 0.000 m | false | true | false | `0.000 m` | `9.581 m` | 4512 | — |
| Batch A: 10 episodes | 367 | 602 | `X7HyMhZNoso` | ep_idx=1038, ep_id=1759, 7 matched, mean 0.000 m | true | false | false | `5.793 m` | `1.033 m` | 3302 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_10_20260618_ep367_episode602_X7HyMhZNoso.jsonl` |
| Batch A: 10 episodes | 613 | 1070 | `zsNo4HB9uLZ` | ep_idx=678, ep_id=1165, 7 matched, mean 0.000 m | false | true | false | `1.996 m` | `16.438 m` | 1714 | — |
| Batch A: 10 episodes | 133 | 194 | `2azQ1b91cZZ` | ep_idx=756, ep_id=1288, 7 matched, mean 0.258 m | false | false | false | `6.199 m` | — | 2502 | — |
| Batch A: 10 episodes | 198 | 307 | `TbHJrupSAjP` | ep_idx=537, ep_id=928, 7 matched, mean 1.519 m | false | false | false | `0.550 m` | — | 2502 | — |
| Batch A: 10 episodes | 186 | 280 | `EU6Fwq7SyZv` | ep_idx=447, ep_id=754, 6 matched, mean 0.433 m | false | false | false | `3.561 m` | — | 2502 | — |
| Batch A: 10 episodes | 4 | 8 | `x8F5xyUWy9e` | ep_idx=354, ep_id=583, 5 matched, mean 0.000 m | true | false | false | `10.151 m` | `1.630 m` | 2552 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_10_20260618_ep4_episode8_x8F5xyUWy9e.jsonl` |
| Batch A: 10 episodes | 336 | 547 | `Z6MFQCViBuw` | ep_idx=651, ep_id=1132, 4 matched, mean 0.000 m | false | false | false | `12.322 m` | — | 2502 | — |
| Batch A: 10 episodes | 408 | 682 | `oLBMNvg9in8` | ep_idx=522, ep_id=907, 4 matched, mean 0.761 m | true | false | false | `6.884 m` | `0.686 m` | 5827 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_10_20260618_ep408_episode682_oLBMNvg9in8.jsonl` |
| Batch A: 10 episodes | 107 | 153 | `QUCTc6BB5sX` | ep_idx=993, ep_id=1699, 7 matched, mean 0.000 m | false | false | false | `12.227 m` | — | 2502 | — |
| Batch B: 20 episodes | 368 | 603 | `X7HyMhZNoso` | ep_idx=1038, ep_id=1759, 7 matched, mean 0.000 m | true | false | false | `6.826 m` | `0.451 m` | 7027 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep368_episode603_X7HyMhZNoso.jsonl` |
| Batch B: 20 episodes | 614 | 1071 | `zsNo4HB9uLZ` | ep_idx=678, ep_id=1165, 7 matched, mean 0.000 m | false | false | false | `0.761 m` | — | 2502 | — |
| Batch B: 20 episodes | 993 | 1699 | `QUCTc6BB5sX` | ep_idx=105, ep_id=151, 7 matched, mean 0.000 m | true | true | true | `1.994 m` | `0.522 m` | 4411 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep993_episode1699_QUCTc6BB5sX.jsonl` |
| Batch B: 20 episodes | 134 | 195 | `2azQ1b91cZZ` | ep_idx=756, ep_id=1288, 7 matched, mean 0.258 m | true | false | false | `6.223 m` | `0.252 m` | 3252 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep134_episode195_2azQ1b91cZZ.jsonl` |
| Batch B: 20 episodes | 199 | 308 | `TbHJrupSAjP` | ep_idx=537, ep_id=928, 7 matched, mean 1.519 m | false | false | false | `0.589 m` | — | 2502 | — |
| Batch B: 20 episodes | 187 | 281 | `EU6Fwq7SyZv` | ep_idx=447, ep_id=754, 6 matched, mean 0.433 m | true | false | false | `11.813 m` | `0.216 m` | 7727 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep187_episode281_EU6Fwq7SyZv.jsonl` |
| Batch B: 20 episodes | 5 | 9 | `x8F5xyUWy9e` | ep_idx=354, ep_id=583, 5 matched, mean 0.000 m | true | false | false | `8.598 m` | `0.255 m` | 3882 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep5_episode9_x8F5xyUWy9e.jsonl` |
| Batch B: 20 episodes | 337 | 548 | `Z6MFQCViBuw` | ep_idx=651, ep_id=1132, 4 matched, mean 0.000 m | false | false | false | `4.622 m` | `4.818 m` | 3702 | — |
| Batch B: 20 episodes | 409 | 683 | `oLBMNvg9in8` | ep_idx=522, ep_id=907, 4 matched, mean 0.761 m | false | false | false | `2.125 m` | — | 1666 | — |
| Batch B: 20 episodes | 678 | 1165 | `zsNo4HB9uLZ` | ep_idx=612, ep_id=1069, 7 matched, mean 0.000 m | true | false | false | `3.782 m` | `0.208 m` | 3777 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep678_episode1165_zsNo4HB9uLZ.jsonl` |
| Batch B: 20 episodes | 679 | 1166 | `zsNo4HB9uLZ` | ep_idx=612, ep_id=1069, 7 matched, mean 0.000 m | true | true | true | `1.995 m` | `0.227 m` | 4021 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep679_episode1166_zsNo4HB9uLZ.jsonl` |
| Batch B: 20 episodes | 680 | 1167 | `zsNo4HB9uLZ` | ep_idx=612, ep_id=1069, 7 matched, mean 0.000 m | true | false | false | `3.710 m` | `0.380 m` | 3877 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep680_episode1167_zsNo4HB9uLZ.jsonl` |
| Batch B: 20 episodes | 994 | 1700 | `QUCTc6BB5sX` | ep_idx=105, ep_id=151, 7 matched, mean 0.000 m | true | false | false | `4.522 m` | `0.729 m` | 3927 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep994_episode1700_QUCTc6BB5sX.jsonl` |
| Batch B: 20 episodes | 995 | 1701 | `QUCTc6BB5sX` | ep_idx=105, ep_id=151, 7 matched, mean 0.000 m | false | false | false | `11.760 m` | — | 2502 | — |
| Batch B: 20 episodes | 1038 | 1759 | `X7HyMhZNoso` | ep_idx=366, ep_id=601, 7 matched, mean 0.000 m | true | true | true | `1.998 m` | `1.004 m` | 3881 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep1038_episode1759_X7HyMhZNoso.jsonl` |
| Batch B: 20 episodes | 1039 | 1760 | `X7HyMhZNoso` | ep_idx=366, ep_id=601, 7 matched, mean 0.000 m | false | false | false | `3.748 m` | — | 2502 | — |
| Batch B: 20 episodes | 1040 | 1761 | `X7HyMhZNoso` | ep_idx=366, ep_id=601, 7 matched, mean 0.000 m | true | false | false | `2.415 m` | `0.993 m` | 4152 | `results/per_step_logs/v4_batch_20260618_outbound_success/v4_batch_20_20260618_ep1040_episode1761_X7HyMhZNoso.jsonl` |
| Batch B: 20 episodes | 465 | 793 | `QUCTc6BB5sX` | ep_idx=600, ep_id=1042, 7 matched, mean 0.216 m | false | false | false | `0.000 m` | — | 952 | — |
| Batch B: 20 episodes | 466 | 794 | `QUCTc6BB5sX` | ep_idx=600, ep_id=1042, 7 matched, mean 0.216 m | false | false | false | `3.630 m` | `5.201 m` | 6603 | — |
| Batch B: 20 episodes | 467 | 795 | `QUCTc6BB5sX` | ep_idx=600, ep_id=1042, 7 matched, mean 0.216 m | false | false | false | `4.176 m` | — | 2502 | — |

The three confirmed round-trip successes were:

| ep_idx | scene | Final distance to start |
|---:|---|---:|
| 993 | `QUCTc6BB5sX` | `1.994 m` |
| 679 | `zsNo4HB9uLZ` | `1.995 m` |
| 1038 | `X7HyMhZNoso` | `1.998 m` |

Interpretation: the larger 30-episode sample keeps the same pattern seen in the earlier random v4 runs. v4 reverse-path retrieval can produce full round-trip success, but successes remain narrow-margin cases ending just inside the 2.0 m return-success radius. Outbound failure is still common, and among episodes that do enter Return, visual decision and stop-judgment errors remain the main failure modes.


### 2026-06-26 — Relative-Odometry Route-Memory Batch Test

Updated the round-trip evaluator so outbound and return success both use the official `3.0 m` goal radius. Return success now requires a VLM-issued `stop` inside the start radius; entering the radius alone does not terminate the episode or count as success.

Implemented the first external route-memory agent:

- Records outbound anchors using relative odometry deltas rather than storing Isaac/global coordinates.
- Builds a reversed route template for Return.
- Injects compact route-progress hints into the Return prompt, including the remaining route-template distance to the start.
- Adds a conservative fallback controller for low-progress or oscillatory Return behavior.

Batch selection:

- Source: previous 30-episode phase-prompt baseline.
- Criterion: baseline outbound success was true and baseline return success was false.
- Tested episodes: `4, 5, 134, 187, 367, 368, 408, 678, 680, 994`.
- Excluded episode `1040` because it was a borderline case under the current `3.0 m` radius.

Artifacts:

```text
results/route_memory_batch_10_20260626/
├── summary.tsv
├── summary.json
├── measurements/
└── trajectories/
```

Key aggregate result:

| Method | Outbound Success | Return Success | Round-Trip Success | Final Distance Improved |
|---|---:|---:|---:|---:|
| Baseline | 10/10 | 0/10 | 0/10 | - |
| Route memory, relative odometry | 8/10 | 3/10 | 3/10 | 7/10 |

Per-episode comparison:

| Episode | Baseline Return | Baseline Distance to Start (m) | Route-Memory Outbound | Route-Memory Return | Route-Memory Distance to Start (m) | Return Stop Count | Fallback Count |
|---:|:---:|---:|:---:|:---:|---:|---:|---:|
| 4 | False | 10.151 | True | False | 0.000 | 0 | 2 |
| 5 | False | 8.598 | True | False | 8.859 | 0 | 16 |
| 134 | False | 6.223 | False | False | 2.605 | 0 | 0 |
| 187 | False | 11.813 | True | False | 8.820 | 0 | 18 |
| 367 | False | 5.793 | True | True | 1.765 | 1 | 2 |
| 368 | False | 6.826 | True | False | 7.137 | 0 | 12 |
| 408 | False | 6.884 | False | False | 2.125 | 0 | 0 |
| 678 | False | 3.782 | True | True | 2.691 | 1 | 1 |
| 680 | False | 3.710 | True | True | 1.925 | 1 | 1 |
| 994 | False | 4.522 | True | False | 4.742 | 1 | 1 |

Interpretation:

- The route-memory framework produced a clear return improvement on this hard subset: round-trip success rose from `0/10` to `3/10`.
- Seven of ten episodes ended closer to the start than the baseline.
- Episode `4` reached `0.000 m` from the start but did not emit a Return-phase VLM `stop`, so it is correctly counted as return failure under the stop-required rule.
- Episodes `134` and `408` regressed on outbound success, so the current framework is promising but not stable enough to claim a general improvement.

---

### 2026-06-27 — Anchor Relocalization Interface and Feature-Depth Backend

Motivation:

The previous route-memory design still depended on the robot entering a local anchor acquisition radius before an anchor could help. This fails in cases like episode `994`, where local geometry descriptors are available but the robot never reaches the first target anchor, so `lock_anchor=0` and anchor correction never activates.

The route-memory agent was redesigned so anchors can be used as map-free relocalization references. Instead of asking "am I standing on this anchor?", the Return stage can now ask "where is this saved outbound anchor relative to my current frame?" A successful relocalizer returns a metric relative pose:

```text
AnchorRelocalization(
  anchor_index=<saved outbound anchor>,
  anchor_dx_m=<anchor forward distance in robot frame>,
  anchor_dy_m=<anchor left/right distance in robot frame>,
  anchor_dtheta_rad=<relative heading>,
  confidence=<backend confidence>,
  backend=<backend name>
)
```

The agent then converts that into route-progress hints:

```text
[System Hint: route anchor A0 is 0.61 m away, 112 deg to your left;
estimated remaining route via anchor is 0.61 m;
start vector dx=-0.23 m, dy=0.56 m.]
```

Implemented code changes:

- `scripts/route_memory_agent.py`
  - Added `RouteAnchor`, `AnchorRelocalization`, and anchor-relative fields on `RelativeStartProgress`.
  - Keeps the old action-integrated relative-start estimate as a fallback.
  - Stores sparse outbound anchors with route-distance metadata.
  - Accepts external relocalization outputs and prioritizes anchor-relative progress when confidence is high enough.
  - Summarizes descriptors by shape/range in measurements instead of dumping large arrays.
- `scripts/round_trip_eval.py`
  - Added `--route_relocalization_backend={none,oracle_anchor,feature_depth}`.
  - Added `--route_relocalization_window` and `--route_relocalization_interval_updates`.
  - Extracts route-memory descriptors from `camera_obs`, `depth_obs`, and `route_memory_obs`.
  - Saves RGB, metric depth, camera intrinsics, height map, and height scan into anchor descriptors.
  - Records anchor relocalization fields in every per-step JSONL trajectory.
- `scripts/vlm_server.py`
  - Fixed a robustness issue where an empty socket connection or malformed JSON request could crash the server.
- `tests/test_route_memory_agent.py`
  - Added tests for anchor saving, anchor-route remaining distance, low-confidence relocalization rejection, and relocalization-driven hint generation.

Validation commands:

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench

env PYTHONPATH=scripts python -m unittest tests/test_route_memory_agent.py

env PYTHONPYCACHEPREFIX=/tmp/navila_pycache \
  python -m py_compile \
  scripts/vlm_server.py \
  scripts/route_memory_agent.py \
  scripts/round_trip_eval.py
```

Both checks passed.

#### Oracle-anchor closed-loop test

The first test used Isaac pose only to simulate a perfect anchor relocalizer. It does not count as a proposed method result; its purpose is to verify the complete plumbing:

```text
current frame -> anchor relative pose -> anchor route hint -> VLM Return prompt -> stop decision
```

Run configuration:

```bash
TERM=xterm OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision \
  --num_envs=1 \
  --history_length=9 \
  --load_run=2024-09-25_23-22-02 \
  --headless \
  --enable_cameras \
  --round_trip_mode=phase_prompt \
  --instruction_rewriter_provider=cache_only \
  --episode_idx=994 \
  --route_memory \
  --route_hint_mode=compact \
  --route_relocalization_backend=oracle_anchor \
  --result_suffix=oracle_anchor_reloc_ep994_20260627
```

Artifacts:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_oracle_anchor_reloc_ep994_20260627/
├── measurements/1699.json
├── trajectories/output_1699.jsonl
└── videos/output_1699.mp4
```

Result:

| Episode | Backend | Outbound | Return | Round trip | Final distance to start | Anchors | Relocalization events | Hint events |
|---:|---|:---:|:---:|:---:|---:|---:|---:|---:|
| 994 | `oracle_anchor` | True | True | True | `0.619 m` | 17 | 2052 | 36 |

Interpretation:

- The anchor-relative hint pipeline is correct.
- The VLM can use a metric anchor/start hint to stop near the start when the relative pose source is accurate.
- This supports the hypothesis that previous failures are primarily caused by unreliable relative pose estimation, not by the prompt-hint idea itself.

#### First real feature-depth backend

A first non-oracle backend was added:

```text
RGB + depth + ORB feature matching + 3D-3D RANSAC/Kabsch
```

The backend:

- extracts ORB features from the current RGB frame and saved anchor RGB frames;
- matches features with ratio test and cross-check fallback;
- uses aligned depth to back-project matched pixels into metric 3D;
- estimates a rigid 3D transform with RANSAC and Kabsch;
- converts the resulting anchor translation into robot-frame `dx/dy` for `AnchorRelocalization`.

Strict run:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_feature_depth_reloc_ep994_20260627/
```

Result:

- Relocalization events: `0`
- Return success: false
- Final distance to start: `4.363 m`

Relaxed run:

```text
eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_feature_depth_relaxed_ep994_20260627/
```

Result:

| Episode | Backend | Outbound | Return | Round trip | Final distance to start | Anchors | Relocalization events |
|---:|---|:---:|:---:|:---:|---:|---:|---:|
| 994 | `feature_depth_orb_3d3d` | True | False | False | `4.424 m` | 17 | 12 |

Diagnostics from the relaxed run:

```json
{
  "attempts": 76,
  "candidate_anchors": 608,
  "ransac_failed": 591,
  "no_pose_selected": 64,
  "low_confidence_pose": 4,
  "successful_estimates": 12
}
```

Representative successful estimates were low confidence:

```text
anchor_index=10, dx=1.10 m, dy=-0.09 m, confidence=0.347, inliers=11
anchor_index=8,  dx=1.59 m, dy=-0.65 m, confidence=0.215, inliers=8
anchor_index=15, dx=-1.43 m, dy=-0.91 m, confidence=0.158, inliers=7
```

Interpretation:

- The real backend is wired correctly: it can produce `AnchorRelocalization` events and drive anchor-relative hints without crashing the evaluator.
- ORB+depth is too weak for this setting. Most candidate anchor matches fail RANSAC, and successful estimates usually have only `6-11` 3D inliers.
- Anchor choice is unstable under this backend, so the Return prompt can receive noisy hints and does not improve over the baseline.
- The next backend should be a stronger cross-view matcher or learned map-free relative-pose model: SuperPoint/LightGlue, LoFTR, or MicKey-style metric relative pose.

Current conclusion:

The research direction remains valid. The oracle-anchor result proves that "remote anchor relative pose -> Return hint" is useful when pose is reliable. The first real classical backend proves the integration path works but also shows that handcrafted ORB+depth matching is not enough for the viewpoint change and low-overlap conditions in these VLN-CE trajectories.

### 2026-06-27 — Geometry Verification, SIFT Diagnostics, and LoFTR Integration

#### Geometry pipeline extraction and verification

All geometry and feature-matching functions were extracted from `round_trip_eval.py` into a standalone module:

```text
scripts/relocalization.py
```

This makes offline testing possible without Isaac Sim. Key exported functions:
`backproject_points`, `rigid_transform_3d`, `ransac_rigid_transform`, `camera_point_to_body`, `loftr_match_points`, `feature_depth_anchor_relocalization`, plus all descriptor accessors.

An 18-test verification suite was added:

```text
tests/test_geometry_pipeline.py
```

Test groups:
- **TestRigidTransform3D** (5 tests): pure translation, pure rotation, general R+t, reflection check (det=+1), too-few-points→None
- **TestRansacRigidTransform** (4 tests): no outliers exact recovery, 50% outliers, too-few-points, inlier mask shape
- **TestCameraPointToBody** (6 tests): fallback axis mapping, extrinsic identity+offset, oracle consistency proof, 20 random pose oracle consistency
- **TestFullPipelineSynthetic** (3 tests): pure translation scene, yaw-rotated cameras, 10+ random configs vs oracle

All 18 tests pass. Key result: the oracle consistency test proves mathematically that given perfect RANSAC output (i.e., `t = Rc_w.T @ (Pa_w - Pc_w)`), `camera_point_to_body` recovers the same body-frame anchor position as the oracle formula `Rb_w.T @ (Pa_w - Pb_w)`.

**Conclusion:** The 8 m+ consistency errors from SIFT are caused entirely by bad feature matches, not by a bug in the geometry transformation code.

Run command:

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench
PYTHONPATH=scripts python -m unittest tests/test_geometry_pipeline.py -v
```

#### SIFT backend test on ep994

The `sift_depth` backend with full extrinsic conversion and consistency gate was tested on episode `994`:

| Backend | Return | Final dist | Notes |
|---|:---:|---:|---|
| `oracle_anchor` | True | 0.619 m | Proves hint pipeline correct |
| `feature_depth` (ORB) | False | 4.424 m | 12/76 estimates; 6–11 inliers |
| `sift_depth` | False | — | 37/37 rejected by consistency gate; min error 8.06 m |

SIFT produced more raw candidates than ORB but every estimate was too far from the action-integrated odometry estimate to be trusted. The system correctly fell back to odometry-only hints rather than injecting wrong anchor directions.

#### LoFTR integration

`kornia==0.6.12` was installed in both `navila-vlm` and `vlnce-isaac` conda environments. The LoFTR `outdoor` pretrained model (44.2 MB, 108 MB VRAM on CUDA) is cached at `~/.cache/torch/hub/checkpoints/loftr_outdoor.ckpt`.

A second test suite was added:

```text
tests/test_loftr_matching.py
```

Offline LoFTR vs ORB comparison on synthetic image pairs (9 tests, all pass):

| Condition | ORB matches | LoFTR inliers | Ratio |
|---|---:|---:|---:|
| Small translation (20 px) | 494 | 2455 | 5.0× |
| 15° rotation | 387 | 2598 | 6.7× |
| 25° rotation | 381 | 1718 | 4.5× |
| 0.75× scale | 324 | 1900 | 5.9× |
| Perspective warp (≈30° tilt) | 229 | 2164 | 9.4× |

LoFTR is wired as the `loftr_depth` backend in `round_trip_eval.py`:

```bash
--route_relocalization_backend=loftr_depth
```

The selection path is: `loftr_depth` → `matcher_backend="loftr"` → `feature_depth_anchor_relocalization(..., matcher_backend="loftr")` → `loftr_match_points()` in `relocalization.py` → `kornia.feature.LoFTR(pretrained="outdoor")`.

Run command for ep994 evaluation with LoFTR (requires VLM server to be running on port 54321):

```bash
cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench && OMNI_KIT_ACCEPT_EULA=YES \
/home/teambruce/miniconda3/bin/conda run \
  --prefix /mnt/SSD4T/teambruce/conda_envs/vlnce-isaac \
  /mnt/SSD4T/teambruce/projects/navila-isaac/IsaacLab/isaaclab.sh -p \
  scripts/round_trip_eval.py \
  --task=go2_matterport_vision --num_envs=1 --history_length=9 \
  --load_run=2024-09-25_23-22-02 --headless --enable_cameras \
  --round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only \
  --episode_idx=994 \
  --route_memory --route_hint_mode=compact \
  --route_relocalization_backend=loftr_depth \
  --result_suffix=loftr_depth_ep994_<date>
```

**Next step:** run ep994 with the VLM server active to get the first real LoFTR relocalization result.


---

## Key Differences vs RTX 5090 (Blackwell) Setup

This deployment is significantly simpler than running on a Blackwell GPU:

| Item | RTX 5090 (Blackwell sm_120) | RTX 4090 (Ada Lovelace sm_89) |
|---|---|---|
| PyTorch | Needed cu128 (torch 2.11+) | Original cu121 (torch 2.3.0) works |
| FlashAttention | No prebuilt wheel; source build failed | Prebuilt wheel available |
| Isaac torch | Needed upgrade to cu128 | IsaacLab-pinned 2.2.2+cu121 works |
| RAM/VRAM | 32 GB VRAM (5090) | 24 GB (tight but sufficient with 8-bit) |

The only patches needed here are genuine code bugs or minor version mismatches unrelated to GPU architecture.

---

## References

- [NaVILA Paper (RSS 2025)](https://arxiv.org/abs/2412.04453)
- [NaVILA GitHub](https://github.com/AnjieCheng/NaVILA)
- [NaVILA-Bench GitHub](https://github.com/yang-zj1026/VLN-CE-Isaac)
- [IsaacLab fork](https://github.com/yang-zj1026/IsaacLab)
- [NaVILA checkpoint (HuggingFace)](https://huggingface.co/a8cheng/navila-llama3-8b-8f)
- [VLN-CE-Isaac dataset (HuggingFace)](https://huggingface.co/datasets/Zhaojing/VLN-CE-Isaac)

