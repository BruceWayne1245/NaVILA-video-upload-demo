# NaVILA + Isaac Sim VLN-CE Deployment on RTX 4090

Reproduction of [NaVILA](https://navila-bot.github.io/) (RSS 2025) Isaac Sim benchmark on a local workstation with RTX 4090.

**Status: End-to-end evaluation working ✅ — Episode 0: success=1.0, SPL=0.907**

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
