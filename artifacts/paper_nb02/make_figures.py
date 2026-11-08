"""
Paper figures and tables for the behavioural sensitivity analysis (notebook 02: Morris
elementary effects, round trips, exposure = °C·min of UTCI above 26 °C).

Reads the batch written by `python -m nairobi_heat_abm.rdm.run_sensitivity`
(config.yaml -> sensitivity.output_dir) and writes, next to this script:
  fig*.svg / fig*.png   figures (numbered after the main-results figures, 5-8)
  table*.csv            table data
  tables.json           formatted tables, read by ../paper_nb01/build_doc.py

Run from the repo root:  .venv/Scripts/python.exe artifacts/paper_nb02/make_figures.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
import yaml  # noqa: E402

# Same batch as notebook 02: config.yaml -> sensitivity.output_dir
OUT = ROOT / yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))["sensitivity"]["output_dir"]

# ---- Style: same conventions as paper_nb01 --------------------------------------------
SINGLE, DOUBLE = 3.5, 7.2
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BAR = "#eb6834"
HEAT = LinearSegmentedColormap.from_list(
    "heat_one_hue", ["#fdf3ec", "#fde7d9", "#f6b48f", "#eb6834", "#c2451a", "#7d2a0c"])
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


def panel_label(ax, s: str, x: float = -0.02) -> None:
    ax.text(x, 1.02, s, transform=ax.transAxes, fontsize=9, fontweight="bold", va="bottom", ha="right")


# Short labels for figures (the factor table carries the full ones).
SHORT = {
    "destination_distance_decay": "Destination distance decay",
    "walk_time_weight": "Walking-time weight (route choice)",
    "walk_share_shift_pp": "Walk-share shift",
    "walk_speed_mean_mps": "Walking speed, mean",
    "walk_speed_std_mps": "Walking speed, SD",
    "transit_mean_wait_min": "Mean boarding wait",
    "transit_wait_tolerance_min": "Wait tolerance",
    "peak1_hour": "Morning peak, hour",
    "peak1_weight": "Morning peak, share",
    "peak2_hour": "Evening outbound peak, hour",
    "peak2_weight": "Evening outbound peak, share",
    "departure_tilt_strength": "Purpose-specific departure timing",
    "work_share": "Work share of purposes",
    "work_end_hour_mean": "Work end time",
    "school_end_hour_mean": "School end time",
    "market_dwell_median_min": "Market dwell time",
    "other_dwell_median_min": "Other-purpose dwell time",
}
UNITS = {
    "destination_distance_decay": "", "walk_time_weight": "×", "walk_share_shift_pp": " pp",
    "walk_speed_mean_mps": " m/s", "walk_speed_std_mps": " m/s", "transit_mean_wait_min": " min",
    "transit_wait_tolerance_min": " min", "peak1_hour": " h", "peak1_weight": "", "peak2_hour": " h",
    "peak2_weight": "", "departure_tilt_strength": "×", "work_share": "", "work_end_hour_mean": " h",
    "school_end_hour_mean": " h", "market_dwell_median_min": " min", "other_dwell_median_min": " min",
}

factors = pd.read_csv(OUT / "factors.csv")
runs = pd.read_csv(OUT / "runs.csv")
design = pd.read_csv(OUT / "design.csv")
idx = pd.read_csv(OUT / "morris_indices.csv")
base = pd.read_csv(OUT / "baseline_summary.csv").set_index("outcome")
settings = json.loads((OUT / "run_config.json").read_text())
assert len(runs) == len(design), f"batch incomplete: {len(runs)}/{len(design)} runs"


def direction(r) -> str:
    if abs(r["mu"]) >= 0.8 * r["mu_star"]:
        return "↑" if r["mu"] > 0 else "↓"
    return "↕"


def get(outcome: str) -> pd.DataFrame:
    return idx[idx["outcome"] == outcome].set_index("factor")


me = get("mean_exposure").sort_values("rank")
ORDER = list(me.index)  # factors ranked by mean exposure, used in every figure


def mu_star_bars(ax, outcome: str, xlabel: str, order=ORDER, labels=True, noise=None) -> None:
    d = get(outcome).loc[order[::-1]]
    y = np.arange(len(d))
    ax.barh(y, d["mu_star"], color=BAR, height=0.62, zorder=2)
    ax.errorbar(d["mu_star"], y, xerr=[d["mu_star"] - d["mu_star_lo"], d["mu_star_hi"] - d["mu_star"]],
                fmt="none", ecolor=INK2, elinewidth=0.7, capsize=0, zorder=3)
    if labels:
        ax.set_yticks(y, [f"{SHORT[f]}  {direction(r)}" for f, r in d.iterrows()])
    else:
        ax.set_yticks(y, [direction(r) for _, r in d.iterrows()])
    ax.set_ylim(-0.6, len(d) - 0.4)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, None)
    ax.set_xlabel(xlabel)
    ax.xaxis.grid(True, color=GRID, lw=0.5); ax.set_axisbelow(True)
    if noise is not None:
        ax.axvline(noise, color=MUTED, lw=0.8, ls=(0, (3, 2)), zorder=1)


# ---- Figure 5: ranking for mean exposure ----------------------------------------------------
sd = base.loc["mean_exposure", "std"]
fig, ax = plt.subplots(figsize=(4.6, 3.6))
mu_star_bars(ax, "mean_exposure", "μ*: mean change in mean daily exposure per person (°C·min)", noise=sd)
ax.text(sd, len(ORDER) - 0.45, f" seed SD ({sd:.0f})", fontsize=6.5, color=MUTED, va="bottom", ha="left")
save(fig, "fig5_morris_mean_exposure")

# ---- Figure 6: duration vs temperature ------------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(DOUBLE, 3.6), sharey=True, gridspec_kw={"wspace": 0.08})
mu_star_bars(axes[0], "mean_outdoor_min", "μ*: minutes outdoors per person", noise=base.loc["mean_outdoor_min", "std"])
mu_star_bars(axes[1], "mean_temp_experienced", "μ*: mean UTCI while outdoors (°C)",
             noise=base.loc["mean_temp_experienced", "std"])
# shared y: label panel a with names; give b its own arrows via text
d = get("mean_temp_experienced").loc[ORDER[::-1]]
for yy, (_, r) in enumerate(d.iterrows()):
    axes[1].text(-0.012, yy, direction(r), transform=axes[1].get_yaxis_transform(), ha="right", va="center",
                 fontsize=7, color=INK2)
d = get("mean_outdoor_min").loc[ORDER[::-1]]
axes[0].set_yticks(range(len(d)), [f"{SHORT[f]}  {direction(r)}" for f, r in d.iterrows()])
axes[1].tick_params(axis="y", labelleft=False)
axes[0].set_title("Duration", loc="left", fontsize=7.5); axes[1].set_title("Temperature", loc="left", fontsize=7.5)
panel_label(axes[0], "a", -0.01); panel_label(axes[1], "b", -0.03)
save(fig, "fig6_duration_vs_temperature")

# ---- Figure 7: all outcomes, relative mu* ---------------------------------------------------
OUTS = [("mean_exposure", "Mean\nexposure"), ("median_exposure", "Median\nexposure"),
        ("p90_exposure", "90th pct\nexposure"), ("mean_outdoor_min", "Minutes\noutdoors"),
        ("mean_temp_experienced", "UTCI while\noutdoors"), ("transit_trip_share", "Transit\ntrip share"),
        ("return_exposure_share", "Share on\ntrip home"), ("returned_share", "Share home\nby 20:00"),
        ("rwi_gap", "Wealth gap\n(Q1 − Q5)"), ("informality_gap", "Informality\ngap")]
rel = idx.assign(rel=idx["mu_star"] / idx.groupby("outcome")["mu_star"].transform("max"))
mat = rel.pivot(index="factor", columns="outcome", values="rel").loc[ORDER, [o for o, _ in OUTS]]
fig, ax = plt.subplots(figsize=(DOUBLE, 4.0))
im = ax.imshow(mat.to_numpy(), cmap=HEAT, vmin=0, vmax=1, aspect="auto")
ax.set_yticks(range(len(mat)), [SHORT[f] for f in mat.index])
ax.set_xticks(range(len(OUTS)), [lab for _, lab in OUTS], fontsize=6.5)
ax.xaxis.tick_top(); ax.tick_params(length=0)
for s in ax.spines.values():
    s.set_visible(False)
ax.set_xticks(np.arange(-0.5, len(OUTS)), minor=True); ax.set_yticks(np.arange(-0.5, len(mat)), minor=True)
ax.grid(which="minor", color="white", lw=1.2); ax.tick_params(which="minor", length=0)
ax.axvline(7.5, color=INK2, lw=0.8)  # separate the city-wide outcomes from the equity gaps
for i in range(mat.shape[0]):
    for j in range(mat.shape[1]):
        v = mat.iat[i, j]
        ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=5.8, color="white" if v > 0.6 else INK2)
cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.015)
cb.set_label("μ* relative to the top factor for that outcome", fontsize=7)
cb.outline.set_linewidth(0.4); cb.ax.tick_params(labelsize=6.5, width=0.5)
save(fig, "fig7_outcome_heatmap")

# ---- Figure 8: the wait-tolerance threshold -------------------------------------------------
F = "transit_wait_tolerance_min"
mr = runs[runs["kind"] == "morris"]  # Morris grid levels only (baseline replicates sit at 15 min)
lev = mr[F].round(2)
levels = sorted(lev.unique())
fig, axes = plt.subplots(1, 2, figsize=(DOUBLE * 0.72, 2.3), gridspec_kw={"wspace": 0.38})
jit = np.random.default_rng(2026).uniform(-0.35, 0.35, len(mr))
for ax, col, ylab in ((axes[0], "mean_exposure", "Mean daily exposure per person (°C·min)"),
                      (axes[1], "mean_outdoor_min", "Minutes outdoors per person")):
    ax.scatter(lev + jit, mr[col], s=7, color=BAR, alpha=0.45, lw=0, zorder=2)
    means = mr.groupby(lev)[col].mean()
    ax.plot(means.index, means.values, color=INK, lw=1.2, marker="o", ms=4, mfc="white", mew=1.0, zorder=3)
    ax.set_xticks(levels, [f"{v:.1f}".removesuffix(".0") for v in levels])
    ax.set_xlabel("Wait tolerance (min)")
    ax.set_ylabel(ylab)
    ax.set_ylim(0, None)
    ax.yaxis.grid(True, color=GRID, lw=0.5); ax.set_axisbelow(True)
    ax.axvline(settings["factors"]["transit_mean_wait_min"][2], color=MUTED, lw=0.8, ls=(0, (3, 2)))
axes[0].text(settings["factors"]["transit_mean_wait_min"][2], axes[0].get_ylim()[1] * 0.97, " mean wait\n (5.65 min)",
             fontsize=6.3, color=MUTED, va="top")
panel_label(axes[0], "a"); panel_label(axes[1], "b")
save(fig, "fig8_wait_tolerance")

# ---- Tables ---------------------------------------------------------------------------------
tables: dict = {}


def fmt(v, f):
    return "" if pd.isna(v) else format(v, f)


def num(v):
    return f"{v:g}" if abs(v) >= 1 or v == 0 else f"{v:.2f}".rstrip("0")


# Table 7: factors and ranges
rows = []
for _, r in factors.iterrows():
    u = UNITS[r["factor"]]
    rows.append([r["label"], f"{num(r['low'])}–{num(r['high'])}{u}", f"{num(r['baseline'])}{u}", r["source"]])
GROUPS = {0: "Destination and route choice", 3: "Walking", 5: "Waiting for transit",
          7: "Outbound departure time", 12: "Trip purpose and the trip home"}
order7 = ["destination_distance_decay", "walk_time_weight", "walk_share_shift_pp", "walk_speed_mean_mps",
          "walk_speed_std_mps", "transit_mean_wait_min", "transit_wait_tolerance_min", "peak1_hour",
          "peak1_weight", "peak2_hour", "peak2_weight", "departure_tilt_strength", "work_share",
          "work_end_hour_mean", "school_end_hour_mean", "market_dwell_median_min", "other_dwell_median_min"]
fpos = {f: i for i, f in enumerate(factors["factor"])}
rows = [rows[fpos[f]] for f in order7]
tables["table7"] = {"header": ["Factor", "Range", "Baseline", "Source of baseline / range"], "rows": rows,
                    "section_rows": {str(k): v for k, v in GROUPS.items()}}
factors.to_csv(HERE / "table7_factors.csv", index=False)

# Table 8: baseline replicates
OUT_LAB = {"mean_exposure": ("Mean exposure (°C·min)", ".0f"), "median_exposure": ("Median exposure (°C·min)", ".0f"),
           "p90_exposure": ("90th-percentile exposure (°C·min)", ".0f"),
           "mean_outdoor_min": ("Minutes outdoors", ".1f"), "mean_temp_experienced": ("Mean UTCI while outdoors (°C)", ".2f"),
           "transit_trip_share": ("Share of trips using transit", ".3f"),
           "walk_trip_mean_exposure": ("Mean exposure, walk-only trips (°C·min)", ".0f"),
           "transit_trip_mean_exposure": ("Mean exposure, transit trips (°C·min)", ".0f"),
           "return_exposure_share": ("Share of exposure on the trip home", ".3f"),
           "returned_share": ("Share home by 20:00", ".3f"),
           "rwi_gap": ("Wealth gap, poorest − richest RWI quintile (°C·min)", ".0f"),
           "informality_gap": ("Informality gap, medium/high − low (°C·min)", ".0f")}
rows = []
for o, (lab, f) in OUT_LAB.items():
    b = base.loc[o]
    rows.append([lab, fmt(b["mean"], f), fmt(b["std"], f), f"{b['cv'] * 100:.1f}%"])
tables["table8"] = {"header": ["Outcome", "Mean", "SD", "CV"], "rows": rows}
base.to_csv(HERE / "table8_baseline_replicates.csv")

# Table 9: Morris indices, main outcomes
om, ot = get("mean_outdoor_min"), get("mean_temp_experienced")
rows = []
for f, r in me.iterrows():
    rows.append([int(r["rank"]), factors.set_index("factor").loc[f, "label"], direction(r),
                 f"{r['mu_star']:.0f} ({r['mu_star_lo']:.0f}–{r['mu_star_hi']:.0f})", f"{r['mu']:.0f}",
                 f"{r['sigma']:.0f}", f"{om.loc[f, 'mu_star']:.1f}", f"{ot.loc[f, 'mu_star']:.2f}"])
tables["table9"] = {"header": ["Rank", "Factor", "Dir.", "μ* (95% CI)", "μ", "σ", "μ* minutes outdoors",
                               "μ* UTCI (°C)"], "rows": rows}
idx.pivot(index="factor", columns="outcome", values="mu_star").loc[ORDER].to_csv(HERE / "table9_mu_star_all_outcomes.csv")
idx.to_csv(HERE / "morris_indices.csv", index=False)

# Numbers quoted in the text
wt = mr.groupby(lev)[["mean_exposure", "mean_outdoor_min"]].mean()
tables["numbers"] = {
    "n_agents": settings["n_agents"], "trajectories": settings["trajectories"], "n_factors": len(factors),
    "n_runs": len(runs), "n_morris": int((runs["kind"] == "morris").sum()),
    "n_baseline": int((runs["kind"] == "baseline").sum()),
    "base_mean": base.loc["mean_exposure", "mean"], "base_sd": sd,
    "base_outdoor": base.loc["mean_outdoor_min", "mean"],
    "base_return_share": base.loc["return_exposure_share", "mean"] * 100,
    "range_min": runs["mean_exposure"].min(), "range_max": runs["mean_exposure"].max(),
    "top": [[{"walk_speed_mean_mps": "Mean walking speed"}.get(f, SHORT[f]), me.loc[f, "mu_star"]] for f in ORDER[:5]],
    "wait_tol_5": wt.loc[5.0, "mean_exposure"], "wait_tol_5_out": wt.loc[5.0, "mean_outdoor_min"],
    "wait_tol_n5": int((lev == 5.0).sum()),
    "wait_tol_ge13_lo": wt.loc[wt.index > 6, "mean_exposure"].min(),
    "wait_tol_ge13_hi": wt.loc[wt.index > 6, "mean_exposure"].max(),
    "n_above_noise": int((me["mu_star"] > 2 * sd).sum()),
}
(HERE / "tables.json").write_text(json.dumps(tables, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(tables["numbers"], indent=1, ensure_ascii=False))
