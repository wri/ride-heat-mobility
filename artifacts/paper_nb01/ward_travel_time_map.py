"""
Map of mean total travel time per person (door-to-door minutes, trip out + trip home), by home
ward, for the main run (N_AGENTS agents, seed 42). Same frame, place labels and scale bar as
fig_ward_exposure_map. Every agent is counted: a trip still under way at the end of the simulated
day (20:00) counts up to 20:00, and a trip home due to leave after 20:00 counts 0, so the means
are lower bounds where trips were cut off (share per ward in table_ward_travel_time.csv).

Needs outputs/agent_times_<N_AGENTS>agents_seed42.csv from rerun_trip_times.py.
Writes fig_ward_travel_time_map.{svg,png} and table_ward_travel_time.csv.
Run from the repo root:  .venv/Scripts/python.exe artifacts/paper_nb01/ward_travel_time_map.py
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

import geopandas as gpd  # noqa: E402
import matplotlib as mpl  # noqa: E402
mpl.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from shapely.geometry import box  # noqa: E402

sys.path.insert(0, str(HERE))
from run_config import N_AGENTS  # noqa: E402

BBOX = (36.649, -1.444, 37.104, -1.163)  # west, south, east, north (config.yaml)
CRS_M = "EPSG:32737"
MIN_WARD_AGENTS = 15
FS = 1.25
INK = "#0b0b0b"
# One-hue blue scale (the transit hue), distinct from the exposure oranges: a different measure.
TIME = LinearSegmentedColormap.from_list(
    "time_one_hue", ["#e3eefb", "#a9c9f0", "#5d9be3", "#2a78d6", "#1a54a0", "#0e2f5e"])
mpl.rcParams.update({"font.family": "Arial", "font.size": 9, "legend.frameon": False,
                     "svg.fonttype": "none", "savefig.dpi": 300, "figure.dpi": 150})

GPKG = ROOT / "outputs" / f"heat_exposure_heat_{N_AGENTS}agents_seed42.gpkg"
homes = gpd.read_file(GPKG, layer="agent_homes", ignore_geometry=True)[["agent_id", "ward"]]
times = pd.read_csv(ROOT / "outputs" / f"agent_times_{N_AGENTS}agents_seed42.csv")
a = homes.merge(times, on="agent_id", validate="one_to_one")
# Travel time within the simulated day: a trip still under way at END_HOUR counts up to END_HOUR,
# and a trip home due to leave after END_HOUR counts 0. A lower bound for agents who hadn't
# finished, so every agent is kept.
END_HOUR = 20.0
out_open = a["trip_out_min"].isna()
a["out_min"] = a["trip_out_min"].where(~out_open, (END_HOUR - a["depart_out_hour"]) * 60)
home_open = a["trip_home_min"].isna() & (a["return_departure_hour"] < END_HOUR)
home_never = a["trip_home_min"].isna() & ~home_open
a["home_min"] = a["trip_home_min"].fillna(0.0)
a.loc[home_open, "home_min"] = (END_HOUR - a.loc[home_open, "return_departure_hour"]) * 60
a["total_min"] = a["out_min"] + a["home_min"]
assert a["total_min"].notna().all()
print(f"trip out unfinished at {END_HOUR:.0f}:00: {out_open.sum():,}; trip home under way: {home_open.sum():,}; "
      f"trip home not started: {(home_never & ~out_open).sum():,}; complete: {(~out_open & ~a['trip_home_min'].isna()).sum():,}")
print(f"travel time, all agents: mean {a['total_min'].mean():.1f} min, median {a['total_min'].median():.1f}")

trunc = out_open | a["trip_home_min"].isna()
by_ward = (a.assign(truncated=trunc).groupby("ward")
           .agg(n=("total_min", "size"), mean=("total_min", "mean"), median=("total_min", "median"),
                pct_truncated=("truncated", lambda s: s.mean() * 100))
           .reset_index())
by_ward.sort_values("mean", ascending=False).to_csv(HERE / "table_ward_travel_time.csv", index=False)

frame = gpd.GeoDataFrame(geometry=[box(*BBOX)], crs="EPSG:4326").to_crs(CRS_M)
wards = gpd.read_file(GPKG, layer="wards")[["ward", "geometry"]].merge(by_ward, on="ward", how="left")
wards_m = gpd.clip(wards.to_crs(CRS_M), frame)
ok = wards_m["n"] >= MIN_WARD_AGENTS
shown = wards_m.loc[ok, "mean"]
vmax = float(np.ceil(shown.quantile(0.97) / 10) * 10)
print(f"wards shown: {ok.sum()}; ward means {shown.min():.0f}-{shown.max():.0f} min; colour scale 0-{vmax:.0f}")

# ---- map furniture (as make_figures.py / context_maps.py) ----------------------------------
PLACES = {
    "CBD": ["Nairobi Central"], "Kibera": ["Laini Saba", "Sarangombe"], "Kangemi": ["Kangemi"],
    "Karen": ["Karen"], "Kilimani": ["Kilimani"], "Eastleigh": ["Eastleigh North", "Eastleigh South"],
    "Kasarani": ["Kasarani"], "Githurai": ["Githurai"], "Dandora": ["Dandora Area I", "Dandora Area Ii",
    "Dandora Area Iii", "Dandora Area Iv"], "Embakasi": ["Embakasi"], "Ruai": ["Ruai"],
    "Ongata Rongai": ["Ongata Rongai"], "Syokimau": ["Syokimau/Mulolongo"], "Kahawa": ["Kahawa West"],
}
PLACE_OFFSETS = {"Kilimani": (-500, 0, "right", "center"), "CBD": (500, 0, "left", "center"),
                 "Kibera": (0, -550, "center", "top")}


def add_places(ax, fontsize: float = 5.8 * FS) -> None:
    halo = [pe.withStroke(linewidth=1.8, foreground="white")]
    for label, names in PLACES.items():
        sel = wards_m[wards_m["ward"].isin(names)]
        if sel.empty:
            continue
        pt = sel.geometry.union_all().representative_point()
        ax.plot(pt.x, pt.y, marker="o", ms=2.2, mfc=INK, mec="white", mew=0.5, zorder=7)
        dx, dy, ha, va = PLACE_OFFSETS.get(label, (450, 350, "left", "bottom"))
        ax.text(pt.x + dx, pt.y + dy, label, fontsize=fontsize, color=INK, ha=ha, va=va, path_effects=halo, zorder=7)


def scalebar(ax, km: float = 5, loc=(0.06, 0.06)) -> None:
    x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
    x = x0 + loc[0] * (x1 - x0); y = y0 + loc[1] * (y1 - y0)
    ax.add_patch(mpl.patches.Rectangle((x - 0.012 * (x1 - x0), y - 0.025 * (y1 - y0)), km * 1000 + 0.024 * (x1 - x0),
                                       0.11 * (y1 - y0), facecolor="white", edgecolor="none", alpha=0.9, zorder=5))
    ax.plot([x, x + km * 1000], [y, y], color=INK, lw=1.2, solid_capstyle="butt", zorder=6)
    ax.text(x + km * 500, y + 0.015 * (y1 - y0), f"{km:g} km", ha="center", va="bottom", fontsize=7 * FS, zorder=6)


fig, ax = plt.subplots(figsize=(6.5, 4.7))
wards_m[~ok].plot(ax=ax, facecolor="#f3f2ef", edgecolor="#c3c2b7", lw=0.3, hatch="////", rasterized=True)
wards_m[ok].plot(ax=ax, column="mean", cmap=TIME, vmin=0, vmax=vmax, edgecolor="white", lw=0.3, rasterized=True)
b = frame.total_bounds
ax.set_xlim(b[0], b[2]); ax.set_ylim(b[1], b[3]); ax.set_aspect("equal"); ax.set_axis_off()
add_places(ax)
sm = mpl.cm.ScalarMappable(norm=mpl.colors.Normalize(0, vmax), cmap=TIME)
cb = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.05, pad=0.02, aspect=30,
                  extend="max" if shown.max() > vmax else "neither")
cb.set_label("Mean daily travel time per person, out and home (min)", fontsize=7 * FS)
cb.outline.set_linewidth(0.4); cb.ax.tick_params(labelsize=6.5 * FS, width=0.5)
scalebar(ax)
ax.legend(handles=[mpl.patches.Patch(facecolor="#f3f2ef", edgecolor="#c3c2b7", hatch="////", lw=0.3,
                                     label=f"< {MIN_WARD_AGENTS} agents")],
          loc="upper left", fontsize=6.5 * FS, borderaxespad=0.3, frameon=True, facecolor="white",
          edgecolor="none", framealpha=0.9)
for ext in ("svg", "png"):
    fig.savefig(HERE / f"fig_ward_travel_time_map.{ext}", bbox_inches="tight", pad_inches=0.02, facecolor="white")
print(by_ward[by_ward["n"] >= MIN_WARD_AGENTS].sort_values("mean").iloc[[0, 1, 2, -3, -2, -1]].to_string(index=False))
