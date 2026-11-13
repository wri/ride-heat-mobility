"""Histogram of outbound departure times in the notebook 01 main run (seed 42), by trip purpose.

The GeoPackage doesn't store departure times, so they are replayed exactly as
model.simulation.run() draws them: one demographic segment at a time in sorted
(age, gender, SES) order, purposes from the "purposes" stream and departure ticks from the
"departures" stream (see purposes.py for the same replay of purposes). Only agents who
travelled are shown. Writes fig_departure_times.{svg,png} and departure_times_15min.csv.

Run from the repository root:  python artifacts/paper_nb01/departure_histogram.py
"""
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

from nairobi_heat_abm.model.agent import DemographicParams, TravelBehaviorParams  # noqa: E402
from nairobi_heat_abm.model.simulation import (  # noqa: E402
    PURPOSE_KEYS, _RNG_STREAMS, _draw_departure_ticks, _draw_purposes, _effective_behavior,
)
from purposes import AGE_CODES, GENDER_CODES  # noqa: E402
from run_config import N_AGENTS  # noqa: E402

SEED = 42
cfg = yaml.safe_load(open(ROOT / "config.yaml"))["simulation"]
START, END, DT = cfg["start_hour"], cfg["end_hour"], cfg["timestep_seconds"]

agents = gpd.read_file(ROOT / "outputs" / f"heat_exposure_heat_{N_AGENTS}agents_seed{SEED}.gpkg",
                       layer="agent_homes", ignore_geometry=True)
assert (agents["agent_id"].to_numpy() == np.arange(len(agents))).all()

behavior, demographics = TravelBehaviorParams(), DemographicParams()
streams = np.random.SeedSequence(SEED).spawn(len(_RNG_STREAMS))
rng_p = np.random.default_rng(streams[_RNG_STREAMS.index("purposes")])
rng_d = np.random.default_rng(streams[_RNG_STREAMS.index("departures")])
age = agents["age_group"].map(AGE_CODES).to_numpy()
gender = agents["gender"].map(GENDER_CODES).to_numpy()
ses = np.zeros(len(agents), dtype=int)
purposes = np.empty(len(agents), dtype=np.uint8)
ticks = np.empty(len(agents), dtype=np.int32)
for a, g, s in sorted(set(zip(age.tolist(), gender.tolist(), ses.tolist()))):
    idx = np.where((age == a) & (gender == g) & (ses == s))[0]
    eff = _effective_behavior(behavior, demographics, a, g, s)
    purposes[idx] = _draw_purposes(eff, len(idx), rng_p)
    ticks[idx] = _draw_departure_ticks(eff, purposes[idx], START, END, DT, rng_d)

trav = agents["travelled"].to_numpy(bool)
hour = START + ticks[trav] * DT / 3600.0
purpose = np.array(PURPOSE_KEYS)[purposes[trav]]

# ---- 15-minute bins, stacked by purpose ---------------------------------------------------
edges = np.arange(START, END + 1e-9, 0.25)
LABELS = {"work": "Work", "school": "School", "market": "Market", "other": "Other"}
COLORS = {"work": "#2a78d6", "school": "#eb6834", "market": "#1baf7a", "other": "#eda100"}  # categorical slots 1-4
counts = {p: np.histogram(hour[purpose == p], bins=edges)[0] for p in PURPOSE_KEYS}
n = len(hour)
tab = pd.DataFrame({"bin_start_h": edges[:-1], **{p: counts[p] for p in PURPOSE_KEYS}})
tab["total"] = tab[list(PURPOSE_KEYS)].sum(axis=1)
tab.to_csv(HERE / "departure_times_15min.csv", index=False)

mpl.rcParams.update({"font.family": "Arial", "font.size": 8, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": "#c3c2b7", "axes.linewidth": 0.6,
                     "xtick.color": "#52514e", "ytick.color": "#52514e", "legend.frameon": False})
fig, ax = plt.subplots(figsize=(7.2, 3.2))
bottom = np.zeros(len(edges) - 1)
w = 0.25
for p in PURPOSE_KEYS:
    share = counts[p] / n * 100
    ax.bar(edges[:-1] + w / 2, share, width=w * 0.9, bottom=bottom, color=COLORS[p], label=LABELS[p],
           edgecolor="white", linewidth=0.6)
    bottom += share
ax.set_xlim(START, END)
ax.set_xticks(range(START, END + 1, 2), [f"{h:02d}:00" for h in range(START, END + 1, 2)])
ax.set_ylabel("Share of travellers leaving home (% per 15 min)")
ax.grid(axis="y", color="#e1e0d9", linewidth=0.5); ax.set_axisbelow(True)
ax.set_xlabel("Outbound departure time")
ax.spines["left"].set_visible(False)
ax.tick_params(axis="y", length=0)
ax.legend(ncol=4, loc="upper right", handlelength=1, handleheight=1, columnspacing=1.2)
band = lambda lo, hi: ((hour >= lo) & (hour < hi)).mean() * 100
for ext in ("svg", "png"):
    fig.savefig(HERE / f"fig_departure_times.{ext}", bbox_inches="tight", dpi=200, facecolor="white")
print(f"n={n}; 06-09 {band(6,9):.1f}%  07-08 {band(7,8):.1f}%  09-15 {band(9,15):.1f}%  15-20 {band(15,20):.1f}%")
print(pd.Series(purpose).value_counts(normalize=True).round(3).to_dict())
for p in PURPOSE_KEYS:
    hp = hour[purpose == p]
    print(f"  {p:7s} median {int(np.median(hp))}:{int(np.median(hp) % 1 * 60):02d}  06-09 {((hp>=6)&(hp<9)).mean()*100:.0f}%  15-20 {((hp>=15)&(hp<20)).mean()*100:.0f}%")
