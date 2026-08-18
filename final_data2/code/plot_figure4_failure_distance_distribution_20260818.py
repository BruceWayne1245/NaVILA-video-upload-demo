#!/usr/bin/env python3
"""Figure 4 (new) per investigations/数据补全/figure_spec.md: distribution of
distance_to_start over episodes with outbound_success==True and
return_success!=True, one row per condition.

Source: NaVILA-Bench/batch_logs/<tag>/summary.tsv. The "Language-only" condition
is the 50-episode pure_baseline_highsuccess100ep_chronological_first50_20260818
batch; the other four conditions were run on the full highsuccess100ep set (100
episodes) and are restricted here to the same 50 episode_ids as Language-only --
verified this reproduces every n/median/Q1/Q3/min/max in the spec table exactly
(numpy linear-interpolation percentiles)."""
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BATCH_LOGS = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs"
FINAL2 = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/final_data2"
OUT_PDF = os.path.join(FINAL2, "figures", "failure_distance_distribution.pdf")

CONDITIONS = [
    ("Language-only", "pure_baseline_highsuccess100ep_chronological_first50_20260818", False),
    ("Oracle hint", "pure_oracle_hint_highsuccess100ep_20260811", True),
    ("+ Hint-Action", "pure_oracle_hint_action_highsuccess100ep_20260812", True),
    ("+ Terminal verif.", "pure_oracle_hint_action_stopgate_highsuccess100ep_20260813", True),
    ("Online", "policy_v2_active50_replay_on_highsuccess100ep_20260816", True),
]

EXPECTED = {
    "Language-only": (39, 5.79, 3.93, 8.50, 0.00, 21.03),
    "Oracle hint": (27, 5.37, 3.85, 6.29, 1.98, 13.04),
    "+ Hint-Action": (13, 3.79, 0.84, 4.10, 0.10, 8.86),
    "+ Terminal verif.": (6, 4.96, 0.84, 6.61, 0.00, 8.82),
    "Online": (22, 5.59, 3.57, 6.89, 0.00, 17.91),
}

SUCCESS_RADIUS_M = 3.0


def truthy(v):
    return str(v).strip().lower() in ("true", "1")


def load_distances():
    base_rows = list(csv.DictReader(open(os.path.join(BATCH_LOGS, CONDITIONS[0][1], "summary.tsv")), delimiter="\t"))
    base_ids = set(r["episode_id"] for r in base_rows)

    result = {}
    for label, tag, restrict in CONDITIONS:
        rows = list(csv.DictReader(open(os.path.join(BATCH_LOGS, tag, "summary.tsv")), delimiter="\t"))
        if restrict:
            rows = [r for r in rows if r["episode_id"] in base_ids]
        fails = [r for r in rows if truthy(r.get("outbound_success")) and not truthy(r.get("return_success")) and r.get("exit_code", "0") == "0"]
        dists = np.array(sorted(float(r["distance_to_start"]) for r in fails if r.get("distance_to_start") not in (None, "")))
        result[label] = dists
    return result


def verify(distances):
    for label, (exp_n, exp_med, exp_q1, exp_q3, exp_min, exp_max) in EXPECTED.items():
        d = distances[label]
        n, med, q1, q3 = len(d), np.median(d), np.percentile(d, 25), np.percentile(d, 75)
        got = (n, round(med, 2), round(q1, 2), round(q3, 2), round(float(d.min()), 2), round(float(d.max()), 2))
        exp = (exp_n, exp_med, exp_q1, exp_q3, exp_min, exp_max)
        assert got == exp, f"{label}: got {got} != expected {exp}"
    print("distribution values verified OK")


def main():
    distances = load_distances()
    verify(distances)

    plt.rcParams.update({
        "font.size": 6,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })

    labels = [c[0] for c in CONDITIONS]
    n_rows = len(labels)
    ys = list(range(n_rows, 0, -1))  # first condition at top

    fig, ax = plt.subplots(figsize=(3.4, 2.0))

    box_data = [distances[label] for label in labels]
    bp = ax.boxplot(
        box_data, positions=ys, vert=False, widths=0.5,
        showfliers=False, patch_artist=True,
        boxprops=dict(facecolor="#E8E8E8", edgecolor="0.25", linewidth=0.6),
        medianprops=dict(color="#D55E00", linewidth=1.0),
        whiskerprops=dict(color="0.25", linewidth=0.6),
        capprops=dict(color="0.25", linewidth=0.6),
        zorder=2,
    )

    rng = np.random.default_rng(0)
    for y, label in zip(ys, labels):
        d = distances[label]
        jitter = rng.uniform(-0.16, 0.16, size=len(d))
        ax.scatter(d, np.full(len(d), y) + jitter, s=6, color="#0072B2", alpha=0.6,
                   edgecolors="none", zorder=3)
        ax.text(1.02, y, f"n={len(d)}", transform=ax.get_yaxis_transform(),
                ha="left", va="center", fontsize=6)

    ax.axvline(SUCCESS_RADIUS_M, color="0.15", linewidth=0.8, linestyle="--", zorder=1)
    ax.text(SUCCESS_RADIUS_M, n_rows + 0.95, "3.0 m success radius", ha="center", va="bottom", fontsize=6)

    ax.set_xscale("symlog", linthresh=8, linscale=1.0)
    ax.set_xlim(0, 24)
    ax.set_xticks([0, 1, 2, 3, 5, 8, 12, 20])
    ax.set_xticklabels(["0", "1", "2", "3", "5", "8", "12", "20"], fontsize=6)
    ax.set_xlabel("Distance to start at return-episode end (m)", fontsize=7)

    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=6)
    ax.set_ylim(0.3, n_rows + 1.4)
    ax.tick_params(axis="y", length=0)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.subplots_adjust(left=0.28, right=0.90, top=0.86, bottom=0.20)

    os.makedirs(os.path.dirname(OUT_PDF), exist_ok=True)
    fig.savefig(OUT_PDF, bbox_inches="tight", pad_inches=0.02)
    print("saved", OUT_PDF)
    png_path = OUT_PDF.replace(".pdf", "_preview.png")
    fig.savefig(png_path, dpi=200, bbox_inches="tight", pad_inches=0.02)
    print("saved", png_path)


if __name__ == "__main__":
    main()
