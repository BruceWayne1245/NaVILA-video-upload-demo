"""Standalone VLM-server adapter for Uni-NaVid, wire-compatible with
NaVILA's scripts/vlm_server.py socket protocol so round_trip_eval.py can
talk to it unmodified via --vlm_port pointed at this process.

Wire protocol (copied verbatim from vlm_server.py, not altered):
  request  = 8-byte big-endian length prefix + JSON {"images": [8 base64
             jpg strings], "query": "<instruction text>"}
  response = 8-byte big-endian length prefix + JSON-encoded string

Only the model-loading and inference internals differ from NaVILA's server;
this process never imports or modifies any NaVILA file.

Known simplifications (same reasoning as streamvln_server.py, see that
file's docstring for the full explanation):
  - Only the most recent (last) of the 8 images per query is fed to the
    agent's own internal frame history (self.rgb_list), not every
    intermediate env step.
  - No explicit reset in the wire protocol; this project already gives
    every episode its own fresh vlm_server.py process, so reset happens
    once at startup here too.
  - Uni-NaVid predicts a short action sequence per query; this adapter uses
    only the FIRST predicted action, to match NaVILA's one-action-per-query
    cadence.
"""

import argparse
import base64
import json
import socket
from io import BytesIO

import cv2
import numpy as np
from PIL import Image

from uninavid.mm_utils import get_model_name_from_path
from uninavid.model.builder import load_pretrained_model
from uninavid.constants import IMAGE_TOKEN_INDEX, DEFAULT_IMAGE_TOKEN, DEFAULT_IM_START_TOKEN, DEFAULT_IM_END_TOKEN
from uninavid.conversation import conv_templates, SeparatorStyle
from uninavid.mm_utils import tokenizer_image_token, KeywordsStoppingCriteria
import torch

from nav_action_translate import translate_uninavid_action, UnknownActionTokenError, STOP


class UniNaVidAgent:
    """Copied from offline_eval_uninavid.py::UniNaVid_Agent (unchanged
    inference logic), just relocated into this server file."""

    def __init__(self, model_path):
        print("Initialize UniNaVid")
        self.conv_mode = "vicuna_v1"
        self.model_name = get_model_name_from_path(model_path)
        self.tokenizer, self.model, self.image_processor, self.context_len = load_pretrained_model(
            model_path, None, get_model_name_from_path(model_path)
        )
        assert self.image_processor is not None
        print("Initialization Complete")

        self.promt_template = (
            "Imagine you are a robot programmed for navigation tasks. You have been given a video "
            "of historical observations and an image of the current observation <image>. Your "
            "assigned task is: '{}'. Analyze this series of images to determine your next four "
            "actions. The predicted action should be one of the following: forward, left, right, or stop."
        )
        self.rgb_list = []
        self.count_id = 0
        self.reset()

    def process_images(self, rgb_list):
        batch_image = np.asarray(rgb_list)
        self.model.get_model().new_frames = len(rgb_list)
        video = self.image_processor.preprocess(batch_image, return_tensors="pt")["pixel_values"].half().cuda()
        return [video]

    def predict_inference(self, prompt):
        qs = prompt
        VIDEO_START_SPECIAL_TOKEN = "<video_special>"
        VIDEO_END_SPECIAL_TOKEN = "</video_special>"
        IMAGE_START_TOKEN = "<image_special>"
        IMAGE_END_TOKEN = "</image_special>"
        NAVIGATION_SPECIAL_TOKEN = "[Navigation]"
        IAMGE_SEPARATOR = "<image_sep>"
        image_start_special_token = self.tokenizer(IMAGE_START_TOKEN, return_tensors="pt").input_ids[0][1:].cuda()
        image_end_special_token = self.tokenizer(IMAGE_END_TOKEN, return_tensors="pt").input_ids[0][1:].cuda()
        video_start_special_token = self.tokenizer(VIDEO_START_SPECIAL_TOKEN, return_tensors="pt").input_ids[0][1:].cuda()
        video_end_special_token = self.tokenizer(VIDEO_END_SPECIAL_TOKEN, return_tensors="pt").input_ids[0][1:].cuda()
        navigation_special_token = self.tokenizer(NAVIGATION_SPECIAL_TOKEN, return_tensors="pt").input_ids[0][1:].cuda()
        image_seperator = self.tokenizer(IAMGE_SEPARATOR, return_tensors="pt").input_ids[0][1:].cuda()

        if self.model.config.mm_use_im_start_end:
            qs = DEFAULT_IM_START_TOKEN + DEFAULT_IMAGE_TOKEN + DEFAULT_IM_END_TOKEN + "\n" + qs.replace("<image>", "")
        else:
            qs = DEFAULT_IMAGE_TOKEN + "\n" + qs.replace("<image>", "")

        conv = conv_templates[self.conv_mode].copy()
        conv.append_message(conv.roles[0], qs)
        conv.append_message(conv.roles[1], None)
        prompt = conv.get_prompt()

        token_prompt = tokenizer_image_token(prompt, self.tokenizer, IMAGE_TOKEN_INDEX, return_tensors="pt").cuda()
        indices_to_replace = torch.where(token_prompt == -200)[0]
        new_list = []
        while indices_to_replace.numel() > 0:
            idx = indices_to_replace[0]
            new_list.append(token_prompt[:idx])
            new_list.append(video_start_special_token)
            new_list.append(image_seperator)
            new_list.append(token_prompt[idx : idx + 1])
            new_list.append(video_end_special_token)
            new_list.append(image_start_special_token)
            new_list.append(image_end_special_token)
            new_list.append(navigation_special_token)
            token_prompt = token_prompt[idx + 1 :]
            indices_to_replace = torch.where(token_prompt == -200)[0]
        if token_prompt.numel() > 0:
            new_list.append(token_prompt)
        input_ids = torch.cat(new_list, dim=0).unsqueeze(0)

        stop_str = conv.sep if conv.sep_style != SeparatorStyle.TWO else conv.sep2
        keywords = [stop_str]
        stopping_criteria = KeywordsStoppingCriteria(keywords, self.tokenizer, input_ids)

        imgs = self.process_images(self.rgb_list)
        self.rgb_list = []

        with torch.inference_mode():
            self.model.update_prompt([[prompt]])
            output_ids = self.model.generate(
                input_ids,
                images=imgs,
                do_sample=True,
                temperature=0.5,
                max_new_tokens=1024,
                use_cache=True,
                stopping_criteria=[stopping_criteria],
            )

        input_token_len = input_ids.shape[1]
        outputs = self.tokenizer.batch_decode(output_ids[:, input_token_len:], skip_special_tokens=True)[0]
        outputs = outputs.strip()
        if outputs.endswith(stop_str):
            outputs = outputs[: -len(stop_str)]
        return outputs.strip()

    def reset(self):
        self.rgb_list = []
        self.count_id += 1
        self.model.config.run_type = "eval"
        self.model.get_model().initialize_online_inference_nav_feat_cache()
        self.model.get_model().new_frames = 0

    def act(self, instruction, rgb_bgr):
        self.rgb_list.append(rgb_bgr)
        navigation_qs = self.promt_template.format(instruction)
        navigation = self.predict_inference(navigation_qs)
        return navigation.split(" ")


def decode_last_image_bgr(images_b64):
    """Uni-NaVid's own offline_eval_uninavid.py feeds cv2.imread()'d (BGR)
    arrays straight into the agent, so this decodes to BGR to match that
    convention exactly (not RGB -- see streamvln_server.py for the RGB
    case, deliberately different per-model)."""
    if not images_b64:
        raise ValueError("empty images list in request")
    raw = base64.b64decode(images_b64[-1])
    np_buf = np.frombuffer(raw, dtype=np.uint8)
    bgr = cv2.imdecode(np_buf, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("failed to decode image")
    return bgr


def build_response_phrase(agent, image_bgr, instruction):
    action_list = agent.act(instruction, image_bgr)
    print(f"[uninavid_server] raw action_list={action_list}")
    if not action_list or not action_list[0]:
        print("[uninavid_server] WARNING: empty action_list, defaulting to stop")
        return STOP
    try:
        return translate_uninavid_action(action_list[0])
    except UnknownActionTokenError as exc:
        print(f"[uninavid_server] WARNING: {exc}; defaulting to stop instead of "
              f"risking NaVILA's silent forward-fallback on unrecognized text")
        return STOP


def start_server(agent, host, port):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(1)
    print(f"[uninavid_server] listening on {host}:{port}")

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
                print(f"[uninavid_server] malformed request from {addr}: {exc}")
                continue

            image_bgr = decode_last_image_bgr(request["images"])
            response = build_response_phrase(agent, image_bgr, request["query"])

            response_bytes = json.dumps(response).encode()
            conn.sendall(len(response_bytes).to_bytes(8, "big"))
            conn.sendall(response_bytes)
        except Exception as exc:
            print(f"[uninavid_server] error handling request from {addr}: {exc}")
        finally:
            conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model_path", default="model_zoo/uninavid-7b-full-224-video-fps-1-grid-2")
    args = parser.parse_args()

    agent = UniNaVidAgent(args.model_path)
    print("[uninavid_server] model loaded, ready")
    start_server(agent, args.host, args.port)
