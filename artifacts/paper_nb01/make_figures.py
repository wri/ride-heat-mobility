"""
Paper figures and tables for the main results (notebook 01 run: N_AGENTS agents, seed 42,
round trips, exposure = °C·min of UTCI above 26 °C).

Reads the GeoPackage written by notebook 01 (outputs/heat_exposure_heat_<N_AGENTS>agents_seed42.gpkg)
and writes, next to this script:
  fig*.svg / fig*.png   figures (SVG with vector text; map layers embedded as 300 dpi raster)
  table*.csv            table data
  tables.json           formatted tables for build_doc.py

Population: all agents. Every agent travels in the baseline (travel probability 1),
so this is the traveller population; agents whose outdoor minutes were all at UTCI <= 26 °C
have zero exposure and are included as zeros.

Run from the repo root:  .venv/Scripts/python.exe artifacts/paper_nb01/make_figures.py
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from matplotlib.colors import LinearSegmentedColormap, LogNorm
from matplotlib.lines import Line2D
from shapely.geometry import box

from purposes import reconstruct_purposes  # same folder

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
from run_config import N_AGENTS  # noqa: E402
GPKG = ROOT / "outputs" / f"heat_exposure_heat_{N_AGENTS}agents_seed42.gpkg"
BBOX = (36.649, -1.444, 37.104, -1.163)  # west, south, east, north (config.yaml)
CRS_M = "EPSG:32737"                      # UTM 37S, metres
MIN_WARD_AGENTS = 15
RNG = np.random.default_rng(2026)

# ---- Style: journal figure conventions -------------------------------------------------
SINGLE, DOUBLE = 3.5, 7.2  # inches
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
WALK, TRANSIT = "#eb6834", "#2a78d6"  # categorical slots 2 and 1
HEAT = LinearSegmentedColormap.from_list(
    "heat_one_hue", ["#fde7d9", "#f6b48f", "#eb6834", "#c2451a", "#7d2a0c", "#3f1505"])
mpl.rcParams.update({
    "font.family": "Arial", "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.edgecolor": "#c3c2b7", "axes.linewidth": 0.6, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "xtick.major.size": 2.5, "ytick.major.size": 2.5, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "svg.fonttype": "none", "savefig.dpi": 300, "figure.dpi": 150,
})


def save(fig, name: str) -> None:
    for ext in ("svg", "png"):
        fig.savefig(HERE / f"{name}.{ext}", bbox_inches="tight", pad_inches=0.02, facecolor="white")
    plt.close(fig)


def panel_label(ax, s: str) -> None:
    ax.text(-0.02, 1.02, s, transform=ax.transAxes, fontsize=9, fontweight="bold", va="bottom", ha="right")


def boot_ci(x: np.ndarray, n: int = 2000) -> tuple[float, float]:
    if len(x) < 2:
        return np.nan, np.nan
    rng = np.random.default_rng(2026)  # own seed per call: intervals don't shift when tables are added
    means = x[rng.integers(0, len(x), (n, len(x)))].mean(axis=1)
    return tuple(np.percentile(means, [2.5, 97.5]))


def summary(x: np.ndarray) -> dict:
    lo, hi = boot_ci(x)
    return {"n": len(x), "zero": (x == 0).mean() * 100, "mean": x.mean(), "lo": lo, "hi": hi,
            "median": np.median(x), "p90": np.percentile(x, 90)}


def scalebar(ax, km: float = 5, loc=(0.06, 0.06)) -> None:
    x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
    x = x0 + loc[0] * (x1 - x0); y = y0 + loc[1] * (y1 - y0)
    ax.add_patch(mpl.patches.Rectangle((x - 0.012 * (x1 - x0), y - 0.025 * (y1 - y0)), km * 1000 + 0.024 * (x1 - x0),
                                       0.11 * (y1 - y0), facecolor="white", edgecolor="none", alpha=0.9, zorder=5))
    ax.plot([x, x + km * 1000], [y, y], color=INK, lw=1.2, solid_capstyle="butt", zorder=6)
    ax.text(x + km * 500, y + 0.015 * (y1 - y0), f"{km:g} km", ha="center", va="bottom", fontsize=7, zorder=6)


# Place labels: label -> ward names whose (clipped) area the label marks. Ward names are used
# as they are, except "CBD" (Nairobi Central) and "Kibera" (its two wards combined).
PLACES = {
    "CBD": ["Nairobi Central"], "Kibera": ["Laini Saba", "Sarangombe"], "Kangemi": ["Kangemi"],
    "Karen": ["Karen"], "Kilimani": ["Kilimani"], "Eastleigh": ["Eastleigh North", "Eastleigh South"],
    "Kasarani": ["Kasarani"], "Githurai": ["Githurai"], "Dandora": ["Dandora Area I", "Dandora Area Ii",
    "Dandora Area Iii", "Dandora Area Iv"], "Embakasi": ["Embakasi"], "Ruai": ["Ruai"],
    "Ongata Rongai": ["Ongata Rongai"], "Syokimau": ["Syokimau/Mulolongo"], "Kahawa": ["Kahawa West"],
}


# Label position relative to its dot (default: above right), for the crowded centre.
PLACE_OFFSETS = {"Kilimani": (-500, 0, "right", "center"), "CBD": (500, 0, "left", "center"),
                 "Kibera": (0, -550, "center", "top")}


def add_places(ax, wards_m, fontsize: float = 6.2) -> None:
    import matplotlib.patheffects as pe
    halo = [pe.withStroke(linewidth=1.8, foreground="white")]
    for label, names in PLACES.items():
        sel = wards_m[wards_m["ward"].isin(names)]
        if sel.empty:
            continue
        pt = sel.geometry.union_all().representative_point()
        ax.plot(pt.x, pt.y, marker="o", ms=2.2, mfc=INK, mec="white", mew=0.5, zorder=7)
        dx, dy, ha, va = PLACE_OFFSETS.get(label, (450, 350, "left", "bottom"))
        ax.text(pt.x + dx, pt.y + dy, label, fontsize=fontsize, color=INK, ha=ha, va=va,
                path_effects=halo, zorder=7)


def map_axes(ax, frame) -> None:
    b = frame.total_bounds
    ax.set_xlim(b[0], b[2]); ax.set_ylim(b[1], b[3])
    ax.set_aspect("equal"); ax.set_axis_off()


# ---- Data -------------------------------------------------------------------------------
agents = gpd.read_file(GPKG, layer="agent_homes", ignore_geometry=True)
segments = gpd.read_file(GPKG, layer="segments").to_crs(CRS_M)
stops = gpd.read_file(GPKG, layer="stops").to_crs(CRS_M)
wards = gpd.read_file(GPKG, layer="wards")
frame = gpd.GeoDataFrame(geometry=[box(*BBOX)], crs="EPSG:4326").to_crs(CRS_M)
wards_m = gpd.clip(wards.to_crs(CRS_M), frame)

agents["purpose"] = reconstruct_purposes(agents)  # not stored in the GeoPackage; see purposes.py
exp = agents["heat_degC_min"].to_numpy(float)
mode = agents["mode"].to_numpy()

# RWI quintiles over all tagged agents (as in notebook 01).
ok = agents["rwi"].notna()
q = pd.qcut(agents.loc[ok, "rwi"], 5, labels=["Q1 (poorest)", "Q2", "Q3", "Q4", "Q5 (richest)"])
agents["rwi_q"] = pd.Series(pd.NA, index=agents.index, dtype="object")
agents.loc[ok, "rwi_q"] = q.astype(str)

tables: dict[str, dict] = {}

# ---- Table 1: exposure per person, overall and by group ---------------------------------
rows = [("All agents", summary(exp))]
for m, lab in (("walk", "Walked (outbound trip)"), ("transit", "Rode transit (outbound trip)")):
    rows.append((lab, summary(exp[mode == m])))
for g, lab in (("child", "Child (0–14)"), ("youth", "Youth (15–19)"), ("adult", "Adult (20–59)"), ("elderly", "Elderly (60+)")):
    rows.append((lab, summary(exp[agents["age_group"].to_numpy() == g])))
for g, lab in (("female", "Female"), ("male", "Male")):
    rows.append((lab, summary(exp[agents["gender"].to_numpy() == g])))
t1 = pd.DataFrame([{"group": k, **v} for k, v in rows])
t1.to_csv(HERE / "table1_exposure_by_group.csv", index=False)
tables["table1"] = {
    "header": ["Group", "n", "Zero exposure (%)", "Mean per person [95% CI]", "Median per person", "90th pct. per person"],
    "rows": [[r.group, f"{r.n:,}", f"{r.zero:.1f}", f"{r['mean']:.0f} [{r.lo:.0f}–{r.hi:.0f}]",
              f"{r['median']:.0f}", f"{r.p90:.0f}"] for _, r in t1.iterrows()],
    "section_rows": {1: "Outbound mode", 3: "Age group", 7: "Gender"},
}

# ---- Table: by destination type (trip purpose) ----------------------------------------------
DEST = [("work", "Work", "Offices, shops, commercial and industrial buildings, banks; also schools, markets and health facilities as workplaces"),
        ("school", "School", "Schools, colleges, universities"),
        ("market", "Market", "Supermarkets and marketplaces"),
        ("other", "Other", "Places of worship, community centres, libraries")]
rows = []
for key, lab, desc in DEST:
    m = agents["purpose"].to_numpy() == key
    rows.append({"purpose": key, "label": lab, "destinations": desc, **summary(exp[m]),
                 "walk_share": (mode[m] == "walk").mean() * 100,
                 "mean_walk": exp[m & (mode == "walk")].mean(), "mean_transit": exp[m & (mode == "transit")].mean()})
tp = pd.DataFrame(rows)
tp.to_csv(HERE / "table_purpose_exposure_by_destination.csv", index=False)
tables["table_purpose"] = {
    "header": ["Destination type", "n", "Walked out (%)", "Zero exposure (%)", "Mean per person [95% CI]", "Median per person",
               "90th pct. per person", "Mean per person, walked", "Mean per person, transit"],
    "rows": [[r.label, f"{r.n:,}", f"{r.walk_share:.0f}", f"{r.zero:.1f}", f"{r['mean']:.0f} [{r.lo:.0f}–{r.hi:.0f}]",
              f"{r['median']:.0f}", f"{r.p90:.0f}", f"{r.mean_walk:.0f}", f"{r.mean_transit:.0f}"] for _, r in tp.iterrows()],
    "destinations": [[r.label, r.destinations] for _, r in tp.iterrows()],
}

# ---- Table 2: wealth and informality ------------------------------------------------------
rows = []
for lab in ["Q1 (poorest)", "Q2", "Q3", "Q4", "Q5 (richest)"]:
    m = (agents["rwi_q"] == lab).to_numpy()
    rows.append(("Relative Wealth Index quintile", lab, summary(exp[m]),
                 exp[m & (mode == "walk")].mean(), exp[m & (mode == "transit")].mean()))
for lab in ["low", "medium", "high"]:
    m = (agents["informality_label"] == lab).to_numpy()
    rows.append(("Morphological informality", lab.capitalize(), summary(exp[m]),
                 exp[m & (mode == "walk")].mean(), exp[m & (mode == "transit")].mean()))
t2 = pd.DataFrame([{"dimension": d, "group": g, **s, "mean_walk": w, "mean_transit": t} for d, g, s, w, t in rows])
t2.to_csv(HERE / "table2_exposure_by_wealth_informality.csv", index=False)
tables["table2"] = {
    "header": ["Home area", "n", "Mean per person [95% CI]", "Median per person", "90th pct. per person",
               "Mean per person, walked", "Mean per person, transit"],
    "rows": [[r.group, f"{r.n:,}", f"{r['mean']:.0f} [{r.lo:.0f}–{r.hi:.0f}]", f"{r['median']:.0f}",
              f"{r.p90:.0f}", f"{r.mean_walk:.0f}", f"{r.mean_transit:.0f}"] for _, r in t2.iterrows()],
    "section_rows": {0: "Relative Wealth Index quintile", 5: "Morphological informality"},
}

# ---- Table 3: segments ---------------------------------------------------------------------
seg = segments.drop(columns="geometry")
top = seg.sort_values("heat_degC_min", ascending=False).head(10)
top.to_csv(HERE / "table3_top_segments.csv", index=False)
tables["table3"] = {
    "header": ["Street", "Road class", "Length (m)", "People", "Person-min", "Total °C·min", "°C·min per person"],
    "rows": [[(r["name"] or "(unnamed)").split(";")[0], r.highway.split(";")[0], f"{r.length_m:.0f}",
              f"{r.n_persons:.0f}", f"{r.person_min:,.0f}", f"{r.heat_degC_min:,.0f}",
              f"{r.heat_degC_min_per_person:.1f}"] for _, r in top.iterrows()],
}

# ---- Table 4: stops --------------------------------------------------------------------------
st = stops.drop(columns="geometry").sort_values("heat_degC_min", ascending=False).head(10)
st.to_csv(HERE / "table4_top_stops.csv", index=False)
tables["table4"] = {
    "header": ["Stop", "People waiting", "Person-min waiting", "Total °C·min", "°C·min per person"],
    "rows": [[r.stop_name, f"{r.n_persons:.0f}", f"{r.person_min:,.0f}", f"{r.heat_degC_min:,.0f}",
              f"{r.heat_degC_min_per_person:.1f}"] for _, r in st.iterrows()],
}

# ---- Ward statistics (recomputed over all agents) -------------------------------------------
wstat = agents.groupby("ward_id").agg(
    n=("heat_degC_min", "size"), mean=("heat_degC_min", "mean"), median=("heat_degC_min", "median"),
    mean_rwi=("rwi", "mean"),
    share_inf=("informality", lambda s: (s >= 1).mean() if s.notna().any() else np.nan))
wards_m = wards_m.drop(columns=["n_agents", "n_travelled", "mean_heat_degC_min", "median_heat_degC_min",
                                "p90_heat_degC_min", "mean_rwi", "share_medium_high_informality"]
                       ).merge(wstat, left_on="ward_id", right_index=True, how="left")
reliable = wards_m[wards_m["n"] >= MIN_WARD_AGENTS].sort_values("mean", ascending=False)
wt = pd.concat([reliable.head(5), reliable.tail(5)])
wt.drop(columns="geometry").to_csv(HERE / "table5_wards.csv", index=False)
tables["table5"] = {
    "header": ["Ward", "Agents", "Mean per resident", "Median per resident", "Mean RWI", "Medium/high informality (%)"],
    "rows": [[r.ward, f"{r.n:.0f}", f"{r['mean']:.0f}", f"{r['median']:.0f}", f"{r.mean_rwi:.2f}",
              "–" if pd.isna(r.share_inf) else f"{r.share_inf * 100:.0f}"] for _, r in wt.iterrows()],
    "section_rows": {0: "Highest mean exposure", 5: "Lowest mean exposure"},
    "n_wards": int(len(reliable)), "n_wards_all": int(len(wards_m)),
}

# Key numbers for captions/text.
tables["numbers"] = {
    "n": int(len(exp)), "mean": float(exp.mean()), "median": float(np.median(exp)),
    "p90": float(np.percentile(exp, 90)), "zero_pct": float((exp == 0).mean() * 100),
    "stop_share_pct": float(stops["heat_degC_min"].sum() / (segments["heat_degC_min"].sum() + stops["heat_degC_min"].sum()) * 100),
    "n_no_informality": int(agents["informality"].isna().sum()),
    "n_segments": int((segments["heat_degC_min"] > 0).sum()), "n_stops": int((stops["heat_degC_min"] > 0).sum()),
}

# ---- Figure 1: distribution by outbound mode ---------------------------------------------
fig, ax = plt.subplots(figsize=(SINGLE, 2.3))
bins = np.arange(0, 1525, 25)
for m, col, lab in (("walk", WALK, "Walked"), ("transit", TRANSIT, "Rode transit")):
    x = exp[mode == m]
    h, _ = np.histogram(np.clip(x, 0, bins[-1] - 1e-9), bins=bins)
    ax.stairs(h / len(x) * 100, bins, color=col, lw=1.4, label=f"{lab} (n = {len(x):,})")
    ax.axvline(np.median(x), color=col, lw=0.8, ls=(0, (3, 2)))
ax.set_xlim(0, 1500)
ymax = ax.get_ylim()[1]
for m, col in (("walk", WALK), ("transit", TRANSIT)):
    med = np.median(exp[mode == m])
    ax.text(med + 12, ymax * (0.93 if m == "walk" else 0.80), f"median {med:.0f}", color=INK2, fontsize=6.5, va="top")
ax.set_xlabel("Daily exposure per person (°C·min above 26 °C UTCI)")
ax.set_ylabel("Share of agents (%) per 25 °C·min")
ax.yaxis.grid(True, color=GRID, lw=0.5); ax.set_axisbelow(True)
ax.legend(loc="upper right", handlelength=1.5)
save(fig, "fig1_exposure_distribution")

# ---- Figure 2: street segments, total and per person -----------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(DOUBLE, 3.25), gridspec_kw={"wspace": 0.04})
used = segments[segments["heat_degC_min"] > 0].sort_values("heat_degC_min")
pp = segments[(segments["n_persons"] >= 5) & (segments["heat_degC_min_per_person"] > 0)].sort_values("heat_degC_min_per_person")
for ax, data, col, norm, title, unit in (
    (axes[0], used, "heat_degC_min", LogNorm(1, 4000), "Total exposure of everyone who walked the segment", "°C·min, all people"),
    (axes[1], pp, "heat_degC_min_per_person", LogNorm(1, 200), "Exposure of one person walking the segment (≥ 5 people)", "°C·min per person"),
):
    wards_m.boundary.plot(ax=ax, color="#d6d3cd", lw=0.3, rasterized=True)
    segments.plot(ax=ax, color="#ecebe7", lw=0.25, rasterized=True)
    data.plot(ax=ax, column=col, cmap=HEAT, norm=norm, lw=0.45, rasterized=True)
    map_axes(ax, frame)
    add_places(ax, wards_m)
    sm = mpl.cm.ScalarMappable(norm=norm, cmap=HEAT)
    cb = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.045, pad=0.02, aspect=35)
    cb.set_label(unit, fontsize=7); cb.outline.set_linewidth(0.4); cb.ax.tick_params(labelsize=6.5, width=0.5)
    ax.set_title(title, fontsize=7.5, loc="left", pad=3)
panel_label(axes[0], "a"); panel_label(axes[1], "b")
scalebar(axes[0], loc=(0.72, 0.06))
save(fig, "fig2_segment_maps")

# ---- Figure 3: (a) ward map, (b) IDEAMAPS morphological informality ---------------------------
fig, (ax, axb) = plt.subplots(1, 2, figsize=(DOUBLE, 3.25), gridspec_kw={"wspace": 0.04})
low_n = wards_m[~(wards_m["n"] >= MIN_WARD_AGENTS)]
low_n.plot(ax=ax, facecolor="#f3f2ef", edgecolor="#c3c2b7", lw=0.3, hatch="////", rasterized=True)
wards_m[wards_m["n"] >= MIN_WARD_AGENTS].plot(ax=ax, column="mean", cmap=HEAT, vmin=0, vmax=700,
                                              edgecolor="white", lw=0.3, rasterized=True)
map_axes(ax, frame)
add_places(ax, wards_m, fontsize=5.8)
sm = mpl.cm.ScalarMappable(norm=mpl.colors.Normalize(0, 700), cmap=HEAT)
cb = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.05, pad=0.02, aspect=30, extend="max")
cb.set_label("Mean daily exposure per resident (°C·min)", fontsize=7); cb.outline.set_linewidth(0.4)
cb.ax.tick_params(labelsize=6.5, width=0.5)
scalebar(ax)
ax.legend(handles=[mpl.patches.Patch(facecolor="#f3f2ef", edgecolor="#c3c2b7", hatch="////", lw=0.3,
                                     label=f"< {MIN_WARD_AGENTS} agents")],
          loc="upper left", fontsize=6.5, borderaxespad=0.3, frameon=True, facecolor="white", edgecolor="none", framealpha=0.9)
ax.set_title("Mean daily exposure per resident, by home ward", fontsize=7.5, loc="left", pad=3)

# (b) IDEAMAPS morphological informality (Hafner et al. 2026, CC BY-NC 4.0), 100 m cells.
# Ordinal one-hue scale, distinct from the exposure colours so the two maps aren't read as one measure.
INFORMALITY = {0: ("Low", "#e9e7f3"), 1: ("Medium", "#a49ad1"), 2: ("High", "#3d2c84")}
idea = pd.read_csv(ROOT / yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))["paths"]["ses"]["informality"])
idea["cls"] = idea["result"].round().astype(int)
cells = gpd.GeoDataFrame(
    idea[["cls"]], crs="EPSG:4326",
    geometry=[box(*b) for b in idea[["lon_min", "lat_min", "lon_max", "lat_max"]].to_numpy()],
).to_crs(CRS_M)
cells = gpd.clip(cells, frame)
covered = cells.geometry.union_all()
gpd.GeoSeries([frame.geometry.iloc[0].difference(covered)], crs=CRS_M).plot(
    ax=axb, facecolor="#f3f2ef", edgecolor="#c3c2b7", lw=0, hatch="////", rasterized=True)
for k, (label, colour) in INFORMALITY.items():
    cells[cells["cls"] == k].plot(ax=axb, facecolor=colour, edgecolor="none", rasterized=True)
wards_m.boundary.plot(ax=axb, color="white", lw=0.3, rasterized=True)
map_axes(axb, frame)
add_places(axb, wards_m, fontsize=5.8)
cb_pad = fig.colorbar(sm, ax=axb, orientation="horizontal", fraction=0.05, pad=0.02, aspect=30)
cb_pad.ax.set_visible(False)  # same map height as panel (a)
handles = [mpl.patches.Patch(facecolor=c, edgecolor="none", label=l) for l, c in INFORMALITY.values()]
handles.append(mpl.patches.Patch(facecolor="#f3f2ef", edgecolor="#c3c2b7", hatch="////", lw=0.3, label="Not covered"))
axb.legend(handles=handles, title="Morphological informality (IDEAMAPS class of the 100 m cell)",
           title_fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=4, fontsize=7,
           frameon=False, handlelength=1.6, columnspacing=1.4)
axb.set_title("Morphological informality of 100 m cells (IDEAMAPS)", fontsize=7.5, loc="left", pad=3)
panel_label(ax, "a"); panel_label(axb, "b")
save(fig, "fig3_ward_map")

# ---- Figure 4: wealth and informality -------------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(DOUBLE, 2.4), gridspec_kw={"width_ratios": [5, 3], "wspace": 0.25})
series = (("all", INK, "All agents", 0.0, "o"), ("walk", WALK, "Walked", -0.18, "s"), ("transit", TRANSIT, "Rode transit", 0.18, "^"))
groups = (("rwi_q", ["Q1 (poorest)", "Q2", "Q3", "Q4", "Q5 (richest)"], ["Q1\npoorest", "Q2", "Q3", "Q4", "Q5\nrichest"],
           "Home Relative Wealth Index quintile"),
          ("informality_label", ["low", "medium", "high"], ["Low", "Medium", "High"], "Home morphological informality"))
for ax, (col, levels, ticklabels, xlabel) in zip(axes, groups):
    for key, color, lab, dx, marker in series:
        means, los, his = [], [], []
        for lev in levels:
            m = (agents[col] == lev).to_numpy()
            if key != "all":
                m &= mode == key
            x = exp[m]; lo, hi = boot_ci(x)
            means.append(x.mean()); los.append(lo); his.append(hi)
        xs = np.arange(len(levels)) + dx
        means, los, his = map(np.array, (means, los, his))
        ax.errorbar(xs, means, yerr=[means - los, his - means], fmt=marker, color=color, ms=4 if key == "all" else 3.4,
                    mfc=color if key == "all" else "white", mew=0.9, elinewidth=0.8, capsize=0, label=lab)
    ax.set_xticks(range(len(levels)), ticklabels)
    ax.set_xlim(-0.5, len(levels) - 0.5)
    ax.set_ylim(0, 450)
    ax.set_xlabel(xlabel)
    ax.yaxis.grid(True, color=GRID, lw=0.5); ax.set_axisbelow(True)
axes[0].set_ylabel("Mean daily exposure per person (°C·min)")
axes[0].legend(loc="lower left", ncol=3, handletextpad=0.3, columnspacing=1.0)
panel_label(axes[0], "a"); panel_label(axes[1], "b")
save(fig, "fig4_wealth_informality")

(HERE / "tables.json").write_text(json.dumps(tables, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(tables["numbers"], indent=1))
print(t1.round(1).to_string()); print(tp.drop(columns="destinations").round(1).to_string()); print(t2.round(1).to_string())
