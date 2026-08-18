#!/usr/bin/env python3
"""Figure 3 (new) per investigations/数据补全/figure_spec.md: arrival rate (AR) vs
success rate (SR), both conditional on outbound success, across the Oracle ladder
plus the online system. Values are taken directly from the spec's table (no
"verify before plotting" note is attached to this figure, unlike Fig 2 / Fig 4)."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

FINAL2 = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/final_data2"
OUT_PDF = os.path.join(FINAL2, "figures", "arrival_vs_success.pdf")

CONDITIONS = [
    ("Language-\nonly", 24.0, 22.0),
    ("+ Oracle\nhint", 39.5, 37.2),
    ("+ Hint-\nAction", 82.2, 71.1),
    ("+ Terminal\nverif.", 90.7, 86.0),
    ("Online", 59.2, 55.1),
]
# Annotate only the three larger termination deficits (11.1, 4.7, 4.1); the
# first two (2.0, 2.3) are too small to annotate cleanly -- left to the table.
ANNOTATE_DELTA = {2, 3, 4}

AR_COLOR = "#0072B2"
SR_COLOR = "#D55E00"

plt.rcParams.update({
    "font.size": 6,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

fig, ax = plt.subplots(figsize=(3.4, 2.0))

bar_w = 0.32
ladder_x = [0, 1, 2, 3]
online_x = [5]  # gap at x=4 separates the online bar from the ladder
xs = ladder_x + online_x

# lighter face behind the online group to set it apart from the Oracle ladder
ax.axvspan(4.5, 5.5, color="0.92", zorder=0)
ax.axvline(4.5, color="0.6", linewidth=0.6, linestyle=":", zorder=1)

for x, (_, ar, sr) in zip(xs, CONDITIONS):
    ax.bar(x - bar_w / 2, ar, width=bar_w, color=AR_COLOR, zorder=2)
    ax.bar(x + bar_w / 2, sr, width=bar_w, color=SR_COLOR, hatch="///", edgecolor="white", linewidth=0.4, zorder=2)

for i, (x, (_, ar, sr)) in enumerate(zip(xs, CONDITIONS)):
    if i not in ANNOTATE_DELTA:
        continue
    delta = ar - sr
    y_line = max(ar, sr) + 3.0
    ax.plot([x - bar_w / 2, x - bar_w / 2], [ar + 0.8, y_line], color="0.3", linewidth=0.5, zorder=3)
    ax.plot([x + bar_w / 2, x + bar_w / 2], [sr + 0.8, y_line], color="0.3", linewidth=0.5, zorder=3)
    ax.plot([x - bar_w / 2, x + bar_w / 2], [y_line, y_line], color="0.3", linewidth=0.5, zorder=3)
    ax.text(x, y_line + 1.0, f"Δ{delta:.1f}", ha="center", va="bottom", fontsize=6.5)

ax.set_ylim(0, 100)
ax.set_ylabel("Return success / arrival (%)", fontsize=7)
ax.set_xticks(xs)
ax.set_xticklabels([c[0] for c in CONDITIONS], fontsize=6)
ax.tick_params(axis="y", labelsize=6)
ax.tick_params(axis="x", length=0)

ax.text(1.5, -32, "Oracle ladder", ha="center", va="top", fontsize=6.5, transform=ax.transData, clip_on=False)
ax.text(5, -32, "Online", ha="center", va="top", fontsize=6.5, transform=ax.transData, clip_on=False)

ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

legend_handles = [
    mpatches.Patch(facecolor=AR_COLOR, label="Arrival rate (AR)"),
    mpatches.Patch(facecolor=SR_COLOR, hatch="///", edgecolor="white", label="Success rate (SR)"),
]
ax.legend(handles=legend_handles, loc="upper left", fontsize=6, frameon=False, handlelength=1.4, handletextpad=0.5)

fig.subplots_adjust(left=0.14, right=0.98, top=0.98, bottom=0.30)

os.makedirs(os.path.dirname(OUT_PDF), exist_ok=True)
fig.savefig(OUT_PDF, bbox_inches="tight", pad_inches=0.02)
print("saved", OUT_PDF)
png_path = OUT_PDF.replace(".pdf", "_preview.png")
fig.savefig(png_path, dpi=200, bbox_inches="tight", pad_inches=0.02)
print("saved", png_path)
