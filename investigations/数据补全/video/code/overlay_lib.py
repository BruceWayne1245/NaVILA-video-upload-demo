"""Shared overlay-drawing + clip-reading helpers for Phase 4 rendering.

Source clips are 1024x512 @ 10fps: egocentric camera (left half) concatenated
with a third-person chase camera (right half), instruction text already
burned in by the original capture. This module adds a second overlay layer
(hint / VLM action / arbitration / terminal state / distance / config label)
sourced from the Phase 3 CSVs, as a text panel at the bottom of the frame.
"""
import csv
import os

import cv2
import numpy as np

FONT = cv2.FONT_HERSHEY_SIMPLEX
PANEL_H = 110  # px, text panel height added at the bottom of each 512-tall half


def load_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


_ASCII_SUB = {
    "→": "->",   # →
    "·": "-",    # ·
    "°": "deg",  # °
    "‘": "'", "’": "'", "“": '"', "”": '"',
}


def _ascii_safe(text):
    # cv2.putText's Hershey fonts render unknown glyphs as garbage ("??"); the
    # CSVs carry a few unicode symbols (arrow, middle-dot, degree) that need
    # ASCII stand-ins before drawing.
    for u, a in _ASCII_SUB.items():
        text = text.replace(u, a)
    return text.encode("ascii", "ignore").decode("ascii")


def _put(img, text, org, scale, color, thickness=1, shadow=True):
    text = _ascii_safe(text)
    if shadow:
        cv2.putText(img, text, (org[0] + 1, org[1] + 1), FONT, scale, (0, 0, 0), thickness + 1, cv2.LINE_AA)
    cv2.putText(img, text, org, FONT, scale, color, thickness, cv2.LINE_AA)


def draw_overlay(frame, row, rows, idx, config_label, speed_label):
    """frame: HxWx3 BGR uint8 (H=512, W=1024). Returns a taller frame with a
    text panel appended at the bottom (H+PANEL_H)."""
    h, w = frame.shape[:2]
    panel = np.zeros((PANEL_H, w, 3), dtype=np.uint8)
    panel[:] = (18, 18, 18)

    hint = row.get("hint", "") or ""
    vlm_action = row.get("vlm_action", "") or ""
    arbitration = row.get("arbitration", "") or ""
    terminal_state = ""
    # sticky terminal_state: once it appears, keep showing it through the
    # rest of the clip (it signals the episode's ending near the tail anyway)
    for j in range(idx, -1, -1):
        ts = rows[j].get("terminal_state", "")
        if ts:
            terminal_state = ts
            break
    distance = row.get("distance_to_start", "")

    hint_color = (140, 140, 255) if hint.startswith("—") or "withheld" in hint else (255, 255, 255)
    _put(panel, hint if hint else "(no route hint — language-only)", (10, 24), 0.5, hint_color)
    _put(panel, vlm_action, (10, 48), 0.5, (255, 255, 255))

    # flash arbitration red for ~4 frames (~0.4s @ 10fps source) around an override
    override_recent = False
    for j in range(max(0, idx - 3), idx + 1):
        if j < len(rows) and "OVERRIDDEN" in (rows[j].get("arbitration", "") or ""):
            override_recent = True
            break
    if arbitration:
        color = (0, 0, 255) if override_recent else (120, 220, 120)
        _put(panel, arbitration, (10, 72), 0.5, color)

    if terminal_state:
        color = (0, 0, 255) if "VETO" in terminal_state or "EXECUTED" in terminal_state else (0, 200, 255)
        _put(panel, terminal_state, (10, 96), 0.55, color, thickness=2)

    if distance not in ("", None):
        try:
            d = float(distance)
            dcolor = (120, 220, 120) if d <= 3.0 else (0, 165, 255)
            _put(panel, f"d = {d:.2f} m", (w - 200, 24), 0.55, dcolor, thickness=2)
            cv2.circle(panel, (w - 30, 55), 14, dcolor, 2)
            if d <= 3.0:
                cv2.circle(panel, (w - 30, 55), 4, dcolor, -1)
        except ValueError:
            pass

    out = np.zeros((h + PANEL_H, w, 3), dtype=np.uint8)
    out[:h] = frame
    out[h:] = panel

    _put(out, config_label, (8, 20), 0.5, (255, 255, 0), thickness=1)
    _put(out, speed_label, (w - 160, 20), 0.5, (255, 255, 0), thickness=1)
    return out


def nearest_row_idx(rows, target_step):
    # rows are step-monotonic; linear scan is fine at this scale (<1500 rows)
    best_i, best_d = 0, abs(int(rows[0]["step"]) - target_step)
    for i, r in enumerate(rows):
        d = abs(int(r["step"]) - target_step)
        if d < best_d:
            best_i, best_d = i, d
    return best_i


def render_single(video_path, csv_path, out_path, config_label, native_frames=None):
    rows = load_csv(csv_path)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h + PANEL_H))
    idx = 0
    n = len(rows)
    speed_label = ""  # filled in by caller via config_label if desired
    while True:
        ok, frame = cap.read()
        if not ok or idx >= n:
            break
        row = rows[idx]
        out = draw_overlay(frame, row, rows, idx, config_label, "")
        writer.write(out)
        idx += 1
    cap.release()
    writer.release()
    return idx


def render_pair_side_by_side(video_path_l, csv_path_l, label_l,
                              video_path_r, csv_path_r, label_r,
                              out_path):
    """Sync by `step`: walk the LONGER clip's own frame timeline; for each of
    its frames, look up the nearest-step frame on the other side. Once the
    shorter side's clip ends, hold its last frame."""
    rows_l = load_csv(csv_path_l)
    rows_r = load_csv(csv_path_r)

    cap_l = cv2.VideoCapture(video_path_l)
    cap_r = cv2.VideoCapture(video_path_r)
    fps = cap_l.get(cv2.CAP_PROP_FPS) or 10.0
    w = int(cap_l.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap_l.get(cv2.CAP_PROP_FRAME_HEIGHT))

    frames_l = []
    while True:
        ok, f = cap_l.read()
        if not ok:
            break
        frames_l.append(f)
    frames_r = []
    while True:
        ok, f = cap_r.read()
        if not ok:
            break
        frames_r.append(f)
    cap_l.release()
    cap_r.release()

    n_l, n_r = len(frames_l), len(frames_r)
    longer_is_l = n_l >= n_r
    n_steps = max(n_l, n_r)

    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (2 * w, h + PANEL_H))

    for i in range(n_steps):
        if longer_is_l:
            idx_l = min(i, n_l - 1)
            target_step = int(rows_l[min(i, len(rows_l) - 1)]["step"])
            idx_r = nearest_row_idx(rows_r, target_step) if rows_r else 0
            idx_r = min(idx_r, n_r - 1)
        else:
            idx_r = min(i, n_r - 1)
            target_step = int(rows_r[min(i, len(rows_r) - 1)]["step"])
            idx_l = nearest_row_idx(rows_l, target_step) if rows_l else 0
            idx_l = min(idx_l, n_l - 1)

        row_l = rows_l[min(idx_l, len(rows_l) - 1)]
        row_r = rows_r[min(idx_r, len(rows_r) - 1)]
        out_l = draw_overlay(frames_l[idx_l], row_l, rows_l, min(idx_l, len(rows_l) - 1), label_l, "")
        out_r = draw_overlay(frames_r[idx_r], row_r, rows_r, min(idx_r, len(rows_r) - 1), label_r, "")
        combined = np.concatenate([out_l, out_r], axis=1)
        writer.write(combined)

    writer.release()
    return n_steps
