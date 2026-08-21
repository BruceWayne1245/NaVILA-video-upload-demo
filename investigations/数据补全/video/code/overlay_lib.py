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


def _fit_text(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def draw_overlay(frame, row, rows, idx, config_label, speed_label):
    """frame: HxWx3 BGR uint8 (H=512, W=1024 or 512). Returns a taller frame
    with a text panel appended at the bottom (H+PANEL_H). Text size/position
    scale with the panel width so this also works for the narrower
    third-person-only panels used in side-by-side pair mode (w=512)."""
    h, w = frame.shape[:2]
    narrow = w < 900
    fs = 0.36 if narrow else 0.5
    fs_bold = 0.4 if narrow else 0.55
    max_chars = 34 if narrow else 70
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
    _put(panel, _fit_text(hint if hint else "(no route hint — language-only)", max_chars),
         (10, 24), fs, hint_color)
    _put(panel, _fit_text(vlm_action, max_chars), (10, 48), fs, (255, 255, 255))

    # flash arbitration red for ~4 frames (~0.4s @ 10fps source) around an override
    override_recent = False
    for j in range(max(0, idx - 3), idx + 1):
        if j < len(rows) and "OVERRIDDEN" in (rows[j].get("arbitration", "") or ""):
            override_recent = True
            break
    if arbitration:
        color = (0, 0, 255) if override_recent else (120, 220, 120)
        _put(panel, _fit_text(arbitration, max_chars), (10, 72), fs, color)

    if terminal_state:
        color = (0, 0, 255) if "VETO" in terminal_state or "EXECUTED" in terminal_state else (0, 200, 255)
        _put(panel, _fit_text(terminal_state, max_chars), (10, 96), fs_bold, color, thickness=2)

    if distance not in ("", None):
        try:
            d = float(distance)
            dcolor = (120, 220, 120) if d <= 3.0 else (0, 165, 255)
            dx = w - int(w * 0.195)
            cx = w - int(w * 0.03)
            r = max(9, int(14 * w / 1024))
            _put(panel, f"d = {d:.2f} m", (dx, 24), fs_bold, dcolor, thickness=2)
            cv2.circle(panel, (cx, 55), r, dcolor, 2)
            if d <= 3.0:
                cv2.circle(panel, (cx, 55), max(3, r // 3), dcolor, -1)
        except ValueError:
            pass

    out = np.zeros((h + PANEL_H, w, 3), dtype=np.uint8)
    out[:h] = frame
    out[h:] = panel

    _put(out, config_label, (8, 20), fs, (255, 255, 0), thickness=1)
    _put(out, speed_label, (w - int(w * 0.156), 20), fs, (255, 255, 0), thickness=1)
    return out


def draw_attention_circle(out, w, h, row_y, progress):
    """Draws a growing yellow oval hugging the panel row at row_y (panel-
    local y, i.e. add h to get full-frame y) to flag a divergence moment
    without covering the text it circles. progress in [0, 1] animates the
    oval growing in from the center, matching the freeze-frame hold."""
    cx = int(w * 0.5)
    cy = h + row_y - 6
    max_a = int(w * 0.47)
    a = max(20, int(max_a * min(1.0, progress * 1.3)))
    b = int(0.15 * w * (max(20, min(a, max_a)) / max_a)) if max_a else 16
    b = max(14, min(b, 20))
    thickness = 3 if w >= 900 else 2
    cv2.ellipse(out, (cx, cy), (a, b), 0, 0, 360, (0, 255, 255), thickness, cv2.LINE_AA)
    return out


CAPTION_H = 46  # px, extra band below the data panel, used only when pausing


def event_caption(kind, row):
    """Short, data-driven one-liner explaining a divergence event -- derived
    from the same logged fields the panel already shows, not hand-authored
    per segment, so it stays accurate if the underlying run changes."""
    if kind == "terminal":
        term = row.get("terminal_state") or ""
        d = row.get("distance_to_start")
        try:
            dd, ok = f"{float(d):.1f}m", float(d) <= 3.0
        except (TypeError, ValueError):
            dd, ok = "?", None
        if "VETO" in term:
            return "Stop-gate vetoes the STOP -- the robot keeps moving"
        if "EXECUTED" in term:
            tag = " -- success" if ok else (" -- still short" if ok is False else "")
            return f"Episode ends here, {dd} from home{tag}"
        return term or "Episode ends here"
    arb = row.get("arbitration") or ""
    vlm = (row.get("vlm_action") or "").replace("VLM: ", "").strip()
    direction = arb.split("(")[-1].rstrip(")") if "(" in arb else ""
    if direction and vlm:
        return f"VLM wanted '{vlm}' -- arbiter executes '{direction}' instead"
    return "The arbiter overrides the VLM here"


def draw_caption_band(w, caption_h, text):
    band = np.zeros((caption_h, w, 3), dtype=np.uint8)
    band[:] = (40, 40, 40)
    if text:
        fs = 0.42 if w < 900 else 0.6
        budget = w - 16
        safe = _ascii_safe(text)
        (tw, th), _ = cv2.getTextSize(safe, FONT, fs, 1)
        if tw > budget:
            # shrink char-by-char (measuring actual rendered width, not a
            # guessed char count -- Hershey glyph widths vary enough that a
            # fixed chars-per-panel-width budget overflows narrow panels)
            lo, hi = 0, len(safe)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                cand = safe[:mid].rstrip() + "..."
                cw, _ = cv2.getTextSize(cand, FONT, fs, 1)[0]
                if cw <= budget:
                    lo = mid
                else:
                    hi = mid - 1
            safe = safe[:lo].rstrip() + "..."
            (tw, th), _ = cv2.getTextSize(safe, FONT, fs, 1)
        x = max(6, (w - tw) // 2)
        _put(band, safe, (x, caption_h // 2 + th // 2), fs, (255, 255, 255), thickness=1)
    return band


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
                              out_path, crop_third_person=True,
                              pause_raw_frames=0, max_events=3):
    """Sync by `step`: walk the LONGER clip's own frame timeline; for each of
    its frames, look up the nearest-step frame on the other side. Once the
    shorter side's clip ends, hold its last frame.

    crop_third_person: source frames are ego(left half)+third-person(right
    half) concatenated, 1024 wide; two of those side by side make a 2048-wide
    frame that pads to mostly-black bars once fit into a 1920x1080 canvas.
    Cropping each side down to just its third-person half (512 wide) before
    pairing keeps the combined frame at 1024 wide, matching a single-clip
    segment's aspect ratio and filling the output canvas properly.

    pause_raw_frames: if >0, freezes both sides for this many raw (10fps)
    frames at each detected divergence moment (see detect_pair_events),
    drawing a growing highlight ring over the row of overlay text that
    diverged. The caller picks pause_raw_frames so that, once this piece's
    fixed ffmpeg speed-up factor is applied later, the freeze lasts the
    intended real-time seconds."""
    rows_l = load_csv(csv_path_l)
    rows_r = load_csv(csv_path_r)

    cap_l = cv2.VideoCapture(video_path_l)
    cap_r = cv2.VideoCapture(video_path_r)
    fps = cap_l.get(cv2.CAP_PROP_FPS) or 10.0
    w_full = int(cap_l.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap_l.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = w_full // 2 if crop_third_person else w_full

    def crop(f):
        return f[:, w_full // 2:] if crop_third_person else f

    frames_l = []
    while True:
        ok, f = cap_l.read()
        if not ok:
            break
        frames_l.append(crop(f))
    frames_r = []
    while True:
        ok, f = cap_r.read()
        if not ok:
            break
        frames_r.append(crop(f))
    cap_l.release()
    cap_r.release()

    n_l, n_r = len(frames_l), len(frames_r)
    longer_is_l = n_l >= n_r
    n_steps = max(n_l, n_r)

    # Resolve idx_l/idx_r for every i up front, then detect divergence edges
    # directly on the RESOLVED per-frame sequence (not on raw CSV steps): the
    # two CSVs sit on different, only-approximately-aligned step grids, so
    # mapping an event step from one side onto the other via nearest_row_idx
    # can land one row short of where its own terminal_state/arbitration
    # text actually turns on. Detecting on what each frame will actually show
    # avoids that off-by-one class of bug entirely.
    idx_pairs = []
    for i in range(n_steps):
        if longer_is_l:
            il = min(i, n_l - 1)
            target_step = int(rows_l[min(i, len(rows_l) - 1)]["step"])
            ir = nearest_row_idx(rows_r, target_step) if rows_r else 0
            ir = min(ir, n_r - 1)
        else:
            ir = min(i, n_r - 1)
            target_step = int(rows_r[min(i, len(rows_r) - 1)]["step"])
            il = nearest_row_idx(rows_l, target_step) if rows_l else 0
            il = min(il, n_l - 1)
        idx_pairs.append((min(il, len(rows_l) - 1), min(ir, len(rows_r) - 1)))

    events_by_i = {}
    if pause_raw_frames > 0:
        min_gap = 15
        prev_arb_l = prev_arb_r = False
        prev_term_l = prev_term_r = ""
        last_event_i = -10**9
        pending = []
        for i, (il, ir) in enumerate(idx_pairs):
            arb_l = "OVERRIDDEN" in (rows_l[il].get("arbitration") or "")
            arb_r = "OVERRIDDEN" in (rows_r[ir].get("arbitration") or "")
            term_l = rows_l[il].get("terminal_state") or ""
            term_r = rows_r[ir].get("terminal_state") or ""
            kind = None
            if term_l != prev_term_l and term_l:
                kind = "terminal"
            elif term_r != prev_term_r and term_r:
                kind = "terminal"
            elif (arb_l and not prev_arb_l) or (arb_r and not prev_arb_r):
                kind = "override"
            if kind and i - last_event_i >= min_gap:
                pending.append((i, kind))
                last_event_i = i
            prev_arb_l, prev_arb_r = arb_l, arb_r
            prev_term_l, prev_term_r = term_l or prev_term_l, term_r or prev_term_r
        # prefer terminal events, then spread remaining override slots evenly
        terms = [e for e in pending if e[1] == "terminal"]
        overs = [e for e in pending if e[1] == "override"]
        keep = terms[:]
        slots = max_events - len(keep)
        if slots > 0 and overs:
            gap = max(1, len(overs) // slots)
            keep += overs[::gap][:slots]
        for i, kind in keep:
            events_by_i[i] = kind

    caption_h = CAPTION_H if pause_raw_frames > 0 else 0
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps,
                              (2 * w, h + PANEL_H + caption_h))
    blank_band = draw_caption_band(w, caption_h, "") if caption_h else None

    for i in range(n_steps):
        idx_l, idx_r = idx_pairs[i]
        row_l, row_r = rows_l[idx_l], rows_r[idx_r]
        out_l = draw_overlay(frames_l[idx_l], row_l, rows_l, idx_l, label_l, "")
        out_r = draw_overlay(frames_r[idx_r], row_r, rows_r, idx_r, label_r, "")
        if caption_h:
            out_l = np.concatenate([out_l, blank_band], axis=0)
            out_r = np.concatenate([out_r, blank_band], axis=0)
        combined = np.concatenate([out_l, out_r], axis=1)
        writer.write(combined)

        if i in events_by_i:
            kind = events_by_i[i]
            row_y = 96 if kind == "terminal" else 72
            arb_l = "OVERRIDDEN" in (row_l.get("arbitration") or "")
            arb_r = "OVERRIDDEN" in (row_r.get("arbitration") or "")
            term_l = bool(row_l.get("terminal_state"))
            term_r = bool(row_r.get("terminal_state"))
            circle_l = arb_l if kind == "override" else term_l
            circle_r = arb_r if kind == "override" else term_r
            caption_l = draw_caption_band(w, caption_h, event_caption(kind, row_l)) if circle_l else blank_band
            caption_r = draw_caption_band(w, caption_h, event_caption(kind, row_r)) if circle_r else blank_band
            for k in range(pause_raw_frames):
                progress = (k + 1) / max(1, pause_raw_frames)
                frame_l = np.concatenate([out_l[:h + PANEL_H], caption_l], axis=0)
                frame_r = np.concatenate([out_r[:h + PANEL_H], caption_r], axis=0)
                if circle_l:
                    draw_attention_circle(frame_l, w, h, row_y, progress)
                if circle_r:
                    draw_attention_circle(frame_r, w, h, row_y, progress)
                writer.write(np.concatenate([frame_l, frame_r], axis=1))

    writer.release()
    return n_steps
