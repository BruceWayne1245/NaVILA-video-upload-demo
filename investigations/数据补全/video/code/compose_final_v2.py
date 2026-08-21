"""Phase 4 v2 composition, per the user's 2026-08-21 revision request:

1. Drop Seg 1 (ep1006 baseline alone) and Seg 2 (ep1256 oracle-hint alone) --
   a single failing episode with nothing to compare against reads as
   pointless on its own. The video now opens on Seg 3.
2. Fix the canvas fill: the old pad-to-1920x1080 (scale=decrease + pad) left
   huge black bars top/bottom on every side-by-side comparison segment,
   because pairing two 1024-wide (ego+third-person) panels made a 2048-wide
   frame far too wide/short for a 16:9 canvas. Two changes fix this:
   (a) render_segments_v2.py now crops pair segments to third-person-only
       per side (512 wide instead of 1024), so a pair frame is 1024 wide
       again -- same aspect as a single-clip segment;
   (b) this script switches from scale=decrease+pad (letterbox/pillarbox,
       lots of empty canvas) to scale=increase+crop (fills 1920x1080
       completely, cropping only the excess -- and only ever from the TOP of
       the frame via the explicit crop y-offset below, so the text panel at
       the bottom is never clipped).
3. Key-moment pauses: seg3/seg4-main/seg5-part1/closing now hold a 1.5s
   freeze with a growing highlight oval at each detected left/right
   divergence (an arbitration override firing, or a terminal state --
   STOP proposed -> vetoed vs -> executed -- newly appearing), built into
   the _raw/*_v2.mp4 pieces by render_segments_v2.py. This script's speed
   factors for those four pieces are UNCHANGED from compose_final.py's
   original NATIVE/TARGET values on purpose: the factor is a pure playback
   multiplier, decoupled from the actual (now larger, with pause frames)
   raw file it's applied to -- see render_segments_v2.py's PAUSE_FRAMES
   derivation for why reusing the original factor makes each pause land at
   ~1.5 real seconds regardless of the segment's speed-up.

Single-clip pieces (seg4 insert ep1378, seg5 part2 ep428, seg5 part3 ep1439)
are untouched, reused from the original _raw/ render.

Run with system python3 (only shells out to ffmpeg, no cv2 needed).
"""
import json
import os
import subprocess

REPO = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/数据补全/video"
RAW = os.path.join(REPO, "_raw")
SEG = os.path.join(REPO, "segments_v2")
TMP = os.path.join(REPO, "_raw", "_scaled_v2")
os.makedirs(SEG, exist_ok=True)
os.makedirs(TMP, exist_ok=True)

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
OUT_FPS = 25
CANVAS = "1920x1080"

# Native content-frame counts (pre-pause) and target content seconds --
# UNCHANGED from compose_final.py for the four pair pieces, see docstring.
NATIVE = {
    "seg3_ep1256_pair_v2.mp4": 962,
    "seg4_ep33_pair_v2.mp4": 584,
    "seg4_ep1378_insert.mp4": 1332,
    "seg5_part1_ep1006_pair_v2.mp4": 1432,
    "seg5_part2_ep428.mp4": 692,
    "seg5_part3_ep1439.mp4": 492,
    "closing_ep1154_pair_v2.mp4": 1312,
}

TARGET = {
    "seg3_ep1256_pair_v2.mp4": 50.0,
    "seg4_ep33_pair_v2.mp4": 35.0,
    "seg4_ep1378_insert.mp4": 25.0,
    "seg5_part1_ep1006_pair_v2.mp4": 30.0,
    "seg5_part2_ep428.mp4": 15.0,
    "seg5_part3_ep1439.mp4": 15.0,
    "closing_ep1154_pair_v2.mp4": 20.0,
}


def run(cmd):
    subprocess.run(cmd, check=True)


def speed_factor(name):
    native_s = NATIVE[name] / 10.0
    return native_s / TARGET[name]


def scale_and_speed(raw_name):
    factor = speed_factor(raw_name)
    src = os.path.join(RAW, raw_name)
    dst = os.path.join(TMP, raw_name)
    speed_text = f"{factor:.1f}x speed"
    vf = (
        f"setpts=PTS/{factor:.5f},"
        # fill 1920x1080 completely (no black bars): scale up until BOTH
        # dimensions cover the canvas, then crop the excess only off the
        # top of the frame (crop y-offset = in_h-1080) so the bottom text
        # panel is never touched.
        f"scale=1920:1080:force_original_aspect_ratio=increase,"
        f"crop=1920:1080:0:in_h-1080,"
        f"drawtext=fontfile={FONT}:text='{speed_text}':fontcolor=yellow:fontsize=28:"
        f"x=w-tw-16:y=16:box=1:boxcolor=black@0.5:boxborderw=6,"
        f"fps={OUT_FPS},format=yuv420p"
    )
    run([
        "ffmpeg", "-y", "-v", "error", "-i", src,
        "-vf", vf, "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-an", dst,
    ])
    return factor, dst


def title_card(text_lines, out_path, duration=3.0):
    drawtext_filters = []
    n = len(text_lines)
    for i, line in enumerate(text_lines):
        y_off = f"(h/2)+{(i - (n - 1) / 2) * 60:.0f}"
        escaped = (
            line.replace("%", " percent").replace("\\", "\\\\")
            .replace(":", "\\:").replace("'", "\\'")
        )
        size = 54 if i == 0 else 32
        color = "white" if i == 0 else "0xCCCCCC"
        drawtext_filters.append(
            f"drawtext=fontfile={FONT}:text='{escaped}':fontcolor={color}:fontsize={size}:"
            f"x=(w-text_w)/2:y={y_off}"
        )
    vf = f"color=c=black:s={CANVAS}:d={duration}:r={OUT_FPS}," + ",".join(drawtext_filters) + ",format=yuv420p"
    run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-an", out_path,
    ])


def concat(parts, out_path):
    listfile = out_path + ".list.txt"
    with open(listfile, "w") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listfile,
        "-c", "copy", out_path,
    ])
    os.remove(listfile)


def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def main():
    factors = {}

    # --- Seg 3 (was Seg 1/2 in the original cut; video now opens here) ---
    f3, s3 = scale_and_speed("seg3_ep1256_pair_v2.mp4")
    factors["seg3"] = f3
    title_card(["Segment 1", "Constraining the action -- ep1256, hint vs hint-action",
                "ground-truth pose, both sides", f"{f3:.1f}x speed"], os.path.join(TMP, "title_seg3.mp4"))
    concat([os.path.join(TMP, "title_seg3.mp4"), s3], os.path.join(SEG, "seg3.mp4"))

    # --- Seg 4 (main pair + insert) ---
    f4a, s4a = scale_and_speed("seg4_ep33_pair_v2.mp4")
    f4b, s4b = scale_and_speed("seg4_ep1378_insert.mp4")
    factors["seg4_main"] = f4a
    factors["seg4_insert"] = f4b
    title_card(["Segment 2", "Premature termination presents as trajectory failure",
                "ep33: hint-action vs hint-action-stopgate (ground-truth pose)",
                f"{f4a:.1f}x speed"], os.path.join(TMP, "title_seg4.mp4"), duration=4.0)
    title_card(["Insert: ep1378", "No STOP is ever proposed -- step budget runs out",
                "0.205 m from home, still judged a failure",
                f"{f4b:.1f}x speed"], os.path.join(TMP, "title_seg4_insert.mp4"), duration=3.5)
    concat([
        os.path.join(TMP, "title_seg4.mp4"), s4a,
        os.path.join(TMP, "title_seg4_insert.mp4"), s4b,
    ], os.path.join(SEG, "seg4.mp4"))

    # --- Seg 5 (three parts) ---
    f5a, s5a = scale_and_speed("seg5_part1_ep1006_pair_v2.mp4")
    f5b, s5b = scale_and_speed("seg5_part2_ep428.mp4")
    f5c, s5c = scale_and_speed("seg5_part3_ep1439.mp4")
    factors["seg5_part1"] = f5a
    factors["seg5_part2"] = f5b
    factors["seg5_part3"] = f5c
    title_card(["Segment 3", "The online system and its cost",
                "ep1006: baseline vs online (proposed)",
                f"{f5a:.1f}x speed"], os.path.join(TMP, "title_seg5a.mp4"))
    title_card(["ep428, online", "Bearing-reliability gate withholds the hint",
                "on 99.5 percent of return steps -- return fails",
                f"{f5b:.1f}x speed"], os.path.join(TMP, "title_seg5b.mp4"), duration=3.5)
    title_card(["ep1439, online (contrast)", "Gate withholds on 0 percent of return steps",
                "return succeeds",
                f"{f5c:.1f}x speed"], os.path.join(TMP, "title_seg5c.mp4"), duration=3.5)
    concat([
        os.path.join(TMP, "title_seg5a.mp4"), s5a,
        os.path.join(TMP, "title_seg5b.mp4"), s5b,
        os.path.join(TMP, "title_seg5c.mp4"), s5c,
    ], os.path.join(SEG, "seg5.mp4"))

    # --- Closing ---
    fc, sc = scale_and_speed("closing_ep1154_pair_v2.mp4")
    factors["closing"] = fc
    title_card(["Closing: regression", "ep1154 -- baseline succeeds, proposed system fails",
                "4 of 49 episodes regressed this way", f"{fc:.1f}x speed"],
               os.path.join(TMP, "title_closing.mp4"), duration=4.0)
    results_card = os.path.join(TMP, "results_card.mp4")
    title_card([
        "Results", "language-only 22.0%  ->  Oracle ladder 37.2 / 71.1 / 86.0%  ->  online 55.1%",
        "Oracle rows use ground-truth pose",
    ], results_card, duration=5.0)
    concat([
        os.path.join(TMP, "title_closing.mp4"), sc, results_card,
    ], os.path.join(SEG, "closing.mp4"))

    # --- Final assembled cut ---
    concat([
        os.path.join(SEG, "seg3.mp4"), os.path.join(SEG, "seg4.mp4"),
        os.path.join(SEG, "seg5.mp4"), os.path.join(SEG, "closing.mp4"),
    ], os.path.join(REPO, "final_v2.mp4"))

    durations = {name: ffprobe_duration(os.path.join(SEG, f"{name}.mp4"))
                 for name in ["seg3", "seg4", "seg5", "closing"]}
    final_duration = ffprobe_duration(os.path.join(REPO, "final_v2.mp4"))

    print("SPEED_FACTORS", json.dumps(factors, indent=2))
    print("SEGMENT_DURATIONS_S", json.dumps(durations, indent=2))
    print("FINAL_DURATION_S", final_duration)


if __name__ == "__main__":
    main()
