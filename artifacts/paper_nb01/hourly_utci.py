"""
UTCI by hour on the streets agents walked (main run: N_AGENTS agents, seed 42): the mean and the
10th-90th / 25th-75th percentile spread across walked street segments at each hour, weighted by
the person-minutes walked on each segment. UTCI sampled at segment midpoints from the hourly 10 m
rasters (14 March 2025, 08:00-18:00), as the model samples it (heat.sample_temperature).

Also prints how the variation in UTCI on walked streets splits between time of day (between-hour)
and place (within-hour), for the whole day and for the afternoon.

Writes fig_hourly_utci.{svg,png} and table_hourly_utci.csv.
Run from the repo root:  .venv/Scripts/python.exe artifacts/paper_nb01/hourly_utci.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_rio = ROOT / ".venv" / "Lib" / "site-packages" / "rasterio"
if (_rio / "proj_data").exists():
    os.environ["PROJ_DATA"] = str(_rio / "proj_data"); os.environ.pop("PROJ_LIB", None)
    os.environ["GDAL_DATA"] = str(_rio / "gdal_data")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))

import geopandas as gpd  # noqa: E402
import matplotlib as mpl  # noqa: E402
mpl.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from nairobi_heat_abm.data.heat import load_heat_surface, sample_temperature  # noqa: E402
from run_config import N_AGENTS  # noqa: E402

INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
HEAT = "#eb6834"
mpl.rcParams.update({
    "font.family": "Arial", "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.edgecolor": "#c3c2b7", "axes.linewidth": 0.6, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "xtick.major.size": 2.5, "ytick.major.size": 2.5, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "svg.fonttype": "none", "savefig.dpi": 300, "figure.dpi": 150,
})

cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
b = cfg["bbox"]
surf = load_heat_surface(ROOT / cfg["paths"]["heat_dir"], bbox=(b["south"], b["west"], b["north"], b["east"]))
seg = gpd.read_file(ROOT / "outputs" / f"heat_exposure_heat_{N_AGENTS}agents_seed42.gpkg", layer="segments")
seg = seg[seg["person_min"] > 0]
mid = seg.geometry.interpolate(0.5, normalized=True)  # lon/lat; fine for a midpoint at street scale
lon, lat = mid.x.to_numpy(), mid.y.to_numpy()
w = seg["person_min"].to_numpy(float); w /= w.sum()


def wquant(x: np.ndarray, q: float) -> float:
    o = np.argsort(x); c = np.cumsum(w[o]) - w[o] / 2
    return float(np.interp(q, c, x[o]))


hours = list(surf.hours)
M = np.array([sample_temperature(surf, lon, lat, h).astype(float) for h in hours])
rows = []
for h, t in zip(hours, M):
    m = float((w * t).sum())
    rows.append({"hour": h, "mean": m, "sd": float(np.sqrt((w * (t - m) ** 2).sum())),
                 **{f"p{int(q * 100)}": wquant(t, q) for q in (0.1, 0.25, 0.5, 0.75, 0.9)}})
tab = pd.DataFrame(rows)
tab.round(2).to_csv(HERE / "table_hourly_utci.csv", index=False)


def split(sel: list[int]) -> tuple[float, float]:
    hm = tab["mean"].to_numpy()[sel]
    between = float(((hm - hm.mean()) ** 2).mean())
    within = float(np.mean([(w * (M[i] - tab["mean"][i]) ** 2).sum() for i in sel]))
    return between, within


print(f"{len(seg):,} walked segments")
print(tab.round(1).to_string(index=False))
for name, lo, hi in [("08-18", 8, 18), ("13-17", 13, 17)]:
    bt, wi = split([i for i, h in enumerate(hours) if lo <= h <= hi])
    print(f"{name}: time of day {bt / (bt + wi):.0%} of variance, place {wi / (bt + wi):.0%}")

# ---- figure -------------------------------------------------------------------------------
x = tab["hour"].to_numpy()
fig, ax = plt.subplots(figsize=(3.5, 2.5))
ax.yaxis.grid(True, color=GRID, linewidth=0.5); ax.set_axisbelow(True)
ax.set_xlim(7.6, 18.4)
# UTCI assessment scale boundaries, labelled in the right margin
for lvl, lab in ((26, "26 moderate"), (32, "32 strong"), (38, "38 very strong")):
    ax.axhline(lvl, color=MUTED, lw=0.6, ls=(0, (3, 2)), zorder=1)
    ax.text(18.55, lvl, lab, fontsize=6, color=INK2, va="center", ha="left", clip_on=False)
ax.text(18.55, 40.2, "Heat stress\nfrom (°C)", fontsize=6, color=INK2, va="bottom", ha="left", clip_on=False)
band90 = ax.fill_between(x, tab["p10"], tab["p90"], color=HEAT, alpha=0.18, lw=0, zorder=2)
band50 = ax.fill_between(x, tab["p25"], tab["p75"], color=HEAT, alpha=0.30, lw=0, zorder=3)
(line,) = ax.plot(x, tab["mean"], color=HEAT, lw=2, zorder=4, solid_capstyle="round", marker="o", ms=3.2,
                  mfc=HEAT, mec="white", mew=0.6)
ax.legend([line, band50, band90], ["Mean", "25th–75th percentile", "10th–90th percentile"],
          loc="lower right", fontsize=6.5, handlelength=1.6, borderaxespad=0.2); ax.set_xticks(range(8, 19, 2), [f"{h:02d}:00" for h in range(8, 19, 2)])
ax.set_ylim(15, 41)
ax.set_xlabel("Hour of day"); ax.set_ylabel("UTCI on walked streets (°C)")
for ext in ("svg", "png"):
    fig.savefig(HERE / f"fig_hourly_utci.{ext}", bbox_inches="tight", pad_inches=0.02, facecolor="white")
