"""Standalone VLM-server adapter for StreamVLN, wire-compatible with NaVILA's
scripts/vlm_server.py socket protocol so round_trip_eval.py can talk to it
unmodified via --vlm_port pointed at this process.

Wire protocol (copied verbatim from vlm_server.py, not altered):
  request  = 8-byte big-endian length prefix + JSON {"images": [8 base64
             jpg strings], "query": "<instruction text>"}
  response = 8-byte big-endian length prefix + JSON-encoded string

Only the model-loading and inference internals differ from NaVILA's server;
this process never imports or modifies any NaVILA file.

Known simplifications (documented, not silently swept under the rug):
  - NaVILA's client resends a freshly-resampled 8-frame window every query
    (stateless server). StreamVLN's evaluator instead keeps its own
    streaming/online memory across calls (stateful server). This adapter
    feeds only the most recent (last) of the 8 images per query into the
    evaluator's streaming memory -- correct in spirit (new observation
    arrives, gets appended) but the model only sees frames at the VLM's
    query cadence, not every intermediate env step. Good enough to validate
    end-to-end correctness; revisit if this causes a measurable behavior
    gap later.
  - No explicit reset message exists in NaVILA's wire protocol. In this
    project every episode already gets its own fresh vlm_server.py process
    (see the per-episode --vlm_port convention in existing batch drivers),
    so a fresh process here means a fresh evaluator too -- reset happens
    once at startup, matching that existing convention.
  - StreamVLN predicts a short sequence of future actions per query
    (--num_future_steps, default 4). NaVILA's protocol is one action phrase
    per query. This adapter uses only the FIRST predicted action per query,
    to match NaVILA's own one-action-per-query cadence as closely as
    possible.
"""

import argparse
import base64
import json
import os
import socket
import sys
from io import BytesIO

import numpy as np
import torch
import transformers
from PIL import Image

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_INNER_STREAMVLN_DIR = os.path.join(_PROJECT_ROOT, "streamvln")  # holds model/, utils/, etc.
for _p in (_PROJECT_ROOT, _INNER_STREAMVLN_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from streamvln.streamvln_agent import VLNEvaluator
from model.stream_video_vln import StreamVLNForCausalLM
from nav_action_translate import translate_streamvln_action, UnknownActionTokenError, STOP


def load_evaluator(args):
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        args.tokenizer_path, model_max_length=args.model_max_length, padding_side="right"
    )
    config = transformers.AutoConfig.from_pretrained(args.model_path)
    model = StreamVLNForCausalLM.from_pretrained(
        args.model_path,
        attn_implementation="flash_attention_2",
        torch_dtype=torch.bfloat16,
        config=config,
        low_cpu_mem_usage=False,
    )
    model.model.num_history = args.num_history
    model.reset(1)
    model.requires_grad_(False)
    model.to(args.device)
    model.eval()

    vln_sensor_config = {
        "rgb_height": 1.25,
        "camera_intrinsic": np.array(
            [
                [192.0, 0.0, 191.42857143, 0.0],
                [0.0, 192.0, 191.42857143, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        ),
    }
    return VLNEvaluator(vln_sensor_config, model=model, tokenizer=tokenizer, args=args)


def decode_last_image_rgb(images_b64):
    """NaVILA's client always sends exactly 8 images (padded if fewer),
    oldest-to-newest; only the most recent one is a real new observation
    for a streaming model. Decoded as RGB to match streamvln_server's own
    smoke_test.py convention (PIL .convert('RGB'))."""
    if not images_b64:
        raise ValueError("empty images list in request")
    raw = base64.b64decode(images_b64[-1])
    image = Image.open(BytesIO(raw)).convert("RGB")
    return np.asarray(image)


def build_response_phrase(evaluator, image_rgb, instruction, step_id):
    # evaluator.step()'s first arg is the env index (0..num_envs-1), matched
    # against model.reset(1)'s internal per-env state lists (see
    # stream_video_vln.py's reset()/curr_t) -- NOT an incrementing step
    # counter. We only ever run one environment, so this is always 0.
    # (step_id is still used for our own logging below.)
    env_id = 0
    action_seq, generate_time, llm_output = evaluator.step(
        env_id, image_rgb, instruction, run_model=True
    )
    print(f"[streamvln_server] step {step_id} generate_time={generate_time:.2f}s "
          f"raw={llm_output!r} action_seq={action_seq}")
    if not action_seq:
        print("[streamvln_server] WARNING: empty action_seq, defaulting to stop")
        return STOP
    try:
        return translate_streamvln_action(action_seq[0])
    except UnknownActionTokenError as exc:
        print(f"[streamvln_server] WARNING: {exc}; defaulting to stop instead of "
              f"risking NaVILA's silent forward-fallback on unrecognized text")
        return STOP


def start_server(evaluator, host, port):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(1)
    print(f"[streamvln_server] listening on {host}:{port}")

    step_id = 0
    while True:
        conn, addr = server_socket.accept()
        try:
            size_data = conn.recv(8)
            if not size_data:
                continue
            size = int.from_bytes(size_data, "big")
            if size <= 0:
                continue
            data = b""
            while len(data) < size:
                packet = conn.recv(4096)
                if not packet:
                    break
                data += packet
            if not data:
                continue
            try:
                request = json.loads(data.decode())
            except json.JSONDecodeError as exc:
                print(f"[streamvln_server] malformed request from {addr}: {exc}")
                continue

            image_rgb = decode_last_image_rgb(request["images"])
            step_id += 1
            response = build_response_phrase(evaluator, image_rgb, request["query"], step_id)

            response_bytes = json.dumps(response).encode()
            conn.sendall(len(response_bytes).to_bytes(8, "big"))
            conn.sendall(response_bytes)
        except Exception as exc:  # keep the server alive across one bad request
            import traceback
            print(f"[streamvln_server] error handling request from {addr}: {exc}")
            traceback.print_exc()
        finally:
            conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument(
        "--model_path",
        default="checkpoints/StreamVLN_Video_qwen_1_5_r2r_rxr_envdrop_scalevln_v1_3",
    )
    parser.add_argument("--tokenizer_path", default="Qwen/Qwen2-7B-Instruct")
    parser.add_argument("--num_future_steps", type=int, default=4)
    parser.add_argument("--num_frames", type=int, default=32)
    parser.add_argument("--num_history", type=int, default=8)
    parser.add_argument("--model_max_length", type=int, default=4096)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()

    evaluator = load_evaluator(args)
    print("[streamvln_server] model loaded, ready")
    start_server(evaluator, args.host, args.port)
