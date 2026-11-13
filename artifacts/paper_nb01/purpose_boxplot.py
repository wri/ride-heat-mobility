"""
Box plot of daily heat exposure per person by destination type (trip purpose), main run
(N_AGENTS agents, seed 42). Purposes are reconstructed from the seed (purposes.py).

Boxes: quartiles; line: median; diamond: mean; whiskers: 1.5 IQR (Tukey); dots: agents beyond
the whiskers. Values >= YMAX are drawn as off-scale and counted above the axis (as in Figure 1).

Run from the repo root:  .venv/Scripts/python.exe artifacts/paper_nb01/purpose_boxplot.py
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

from purposes import reconstruct_purposes  # same folder
from run_config import N_AGENTS  # same folder

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GPKG = ROOT / "outputs" / f"heat_exposure_heat_{N_AGENTS}agents_seed42.gpkg"
YMAX = 1500

# Style as make_figures.py
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BOX = "#eb6834"  # heat hue used for exposure throughout the paper
mpl.rcParams.update({
    "font.family": "Arial", "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.edgecolor": "#c3c2b7", "axes.linewidth": 0.6, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "xtick.major.size": 2.5, "ytick.major.size": 2.5, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "svg.fonttype": "none", "savefig.dpi": 300, "figure.dpi": 150,
})

agents = gpd.read_file(GPKG, layer="agent_homes", ignore_geometry=True)
agents["purpose"] = reconstruct_purposes(agents)
exp = agents["heat_degC_min"].to_numpy(float)
purpose = agents["purpose"].to_numpy()

LABELS = {"work": "Work", "school": "School", "market": "Market", "other": "Other"}
keys = sorted(LABELS, key=lambda k: -np.median(exp[purpose == k]))  # highest median first
data = [exp[purpose == k] for k in keys]

fig, ax = plt.subplots(figsize=(3.5, 2.6))
ax.yaxis.grid(True, color=GRID, linewidth=0.5)
ax.set_axisbelow(True)
bp = ax.boxplot(
    [np.minimum(d, YMAX) for d in data], widths=0.5, patch_artist=True, showmeans=True,
    medianprops=dict(color=INK, linewidth=1.2),
    boxprops=dict(facecolor=BOX + "55", edgecolor=BOX, linewidth=0.8),
    whiskerprops=dict(color=BOX, linewidth=0.8), capprops=dict(color=BOX, linewidth=0.8),
    flierprops=dict(marker="o", markersize=1.6, markerfacecolor=MUTED, markeredgecolor="none", alpha=0.35),
    meanprops=dict(marker="D", markersize=4, markerfacecolor="white", markeredgecolor=INK, markeredgewidth=0.7),
)
ax.set_ylim(0, YMAX * 1.04)
ax.set_xticks(range(1, len(keys) + 1),
              [f"{LABELS[k]}\nn = {len(d):,}" for k, d in zip(keys, data)])
ax.set_ylabel("Daily exposure per person (°C·min)")
ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
for i, d in enumerate(data, start=1):
    over = int((d >= YMAX).sum())
    if over:
        ax.text(i, YMAX * 1.05, f"{over} ≥ {YMAX:,}", ha="center", va="bottom", fontsize=6.5, color=INK2)
    ax.text(i + 0.3, np.median(d), f"{np.median(d):.0f}", ha="left", va="center", fontsize=6.5, color=INK2)

for ext in ("svg", "png"):
    fig.savefig(HERE / f"fig_purpose_boxplot.{ext}", bbox_inches="tight", pad_inches=0.02, facecolor="white")

for k, d in zip(keys, data):
    q1, med, q3 = np.percentile(d, [25, 50, 75])
    print(f"{k:7s} n={len(d):6,d} mean={d.mean():5.0f} median={med:4.0f} IQR={q1:.0f}-{q3:.0f} "
          f">= {YMAX}: {(d >= YMAX).sum()} max={d.max():.0f}")
