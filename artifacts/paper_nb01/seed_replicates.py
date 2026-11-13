"""Seed-to-seed variation of the main run: the notebook 01 run (20,000 agents) repeated with
seeds 42-45. Each seed draws new homes, destinations and behaviour. Reads
outputs/heat_exposure_heat_<N>agents_seed<S>.gpkg and writes seed_replicates.csv (one row per
outcome, one column per seed, plus mean / SD / range) and seed_replicates_wards.csv.

Run from the repository root:  python artifacts/paper_nb01/seed_replicates.py
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

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

sys.path.insert(0, str(HERE))
from run_config import N_AGENTS  # noqa: E402

SEEDS = [42, 43, 44, 45]
MIN_WARD_AGENTS = 15
QUINTILES = ["Q1 (poorest)", "Q2", "Q3", "Q4", "Q5 (richest)"]


def outcomes(gpkg: Path) -> tuple[dict, pd.DataFrame, set, set]:
    a = gpd.read_file(gpkg, layer="agent_homes", ignore_geometry=True)
    e = a["heat_degC_min"].to_numpy(float)
    mode = a["mode"].to_numpy()
    out = {"Mean exposure (all agents)": e.mean(), "Median exposure": np.median(e),
           "90th percentile": np.percentile(e, 90), "Zero exposure (%)": (e == 0).mean() * 100,
           "Walked out (%)": (mode == "walk").mean() * 100,
           "Mean, walked out": e[mode == "walk"].mean(), "Mean, rode transit": e[mode == "transit"].mean()}
    for g in ["child", "youth", "adult", "elderly"]:
        out[f"Mean, {g}"] = e[(a["age_group"] == g).to_numpy()].mean()
    # RWI quintiles over all tagged agents, as in make_figures.py
    ok = a["rwi"].notna()
    q = pd.Series(pd.NA, index=a.index, dtype="object")
    q[ok] = pd.qcut(a.loc[ok, "rwi"], 5, labels=QUINTILES).astype(str)
    for lab in QUINTILES:
        out[f"Mean, RWI {lab}"] = e[(q == lab).to_numpy()].mean()
    out["Wealth gap (Q1 - Q5)"] = out["Mean, RWI Q1 (poorest)"] - out["Mean, RWI Q5 (richest)"]
    inf = a["informality_label"]
    for lab in ["low", "medium", "high"]:
        out[f"Mean, informality {lab}"] = e[(inf == lab).to_numpy()].mean()
    out["Informality gap (high - low)"] = out["Mean, informality high"] - out["Mean, informality low"]
    out["Informality gap (medium/high - low)"] = e[inf.isin(["medium", "high"]).to_numpy()].mean() - out["Mean, informality low"]
    out["Agents in IDEAMAPS high (%)"] = (inf == "high").mean() * 100

    wards = gpd.read_file(gpkg, layer="wards", ignore_geometry=True)
    w = wards.loc[wards["n_travelled"] >= MIN_WARD_AGENTS, ["ward", "n_travelled", "mean_heat_degC_min"]]
    seg = gpd.read_file(gpkg, layer="segments", ignore_geometry=True)
    stops = gpd.read_file(gpkg, layer="stops", ignore_geometry=True)
    seg_key = seg.nlargest(10, "heat_degC_min").apply(lambda r: f"{r.get('u')}-{r.get('v')}" if "u" in seg else r["name"], axis=1)
    stop_key = stops.nlargest(10, "heat_degC_min")["stop_name"]
    out["Exposure while waiting at stops (%)"] = stops["heat_degC_min"].sum() / (seg["heat_degC_min"].sum() + stops["heat_degC_min"].sum()) * 100
    return out, w, set(seg_key), set(stop_key)


res, ward_tabs, segs, stps = {}, {}, {}, {}
for s in SEEDS:
    p = ROOT / "outputs" / f"heat_exposure_heat_{N_AGENTS}agents_seed{s}.gpkg"
    if not p.exists():
        print(f"missing {p.name}; skipped")
        continue
    res[s], ward_tabs[s], segs[s], stps[s] = outcomes(p)

t = pd.DataFrame(res)
t.columns = [f"seed {c}" for c in t.columns]
t["mean"] = t.mean(axis=1); t["sd"] = t.iloc[:, :len(res)].std(axis=1, ddof=1)
t["min"] = t.iloc[:, :len(res)].min(axis=1); t["max"] = t.iloc[:, :len(res)].max(axis=1)
t.index.name = "outcome"
t.to_csv(HERE / "seed_replicates.csv")
pd.set_option("display.width", 200)
print(t.round(1).to_string())

# Wards: how stable is the ward ranking?
seeds = list(ward_tabs)
wm = None
for s in seeds:
    x = ward_tabs[s].set_index("ward")[["mean_heat_degC_min", "n_travelled"]].add_suffix(f"_{s}")
    wm = x if wm is None else wm.join(x, how="outer")
wm.to_csv(HERE / "seed_replicates_wards.csv")
print(f"\nWards with >= {MIN_WARD_AGENTS} travelling agents in every seed: "
      f"{wm.dropna().shape[0]}")
both = wm.dropna()
cols = [f"mean_heat_degC_min_{s}" for s in seeds]
rhos = [spearmanr(both[cols[0]], both[c])[0] for c in cols[1:]]
print("Spearman rank correlation of ward means, seed 42 vs others: " + ", ".join(f"{r:.2f}" for r in rhos))
top10 = [set(both[c].nlargest(10).index) for c in cols]
print("Top-10 wards shared with seed 42: " + ", ".join(str(len(top10[0] & t_)) for t_ in top10[1:]))
print("Top-10 street segments shared with seed 42: " + ", ".join(str(len(segs[seeds[0]] & segs[s])) for s in seeds[1:]))
print("Top-10 stops shared with seed 42: " + ", ".join(str(len(stps[seeds[0]] & stps[s])) for s in seeds[1:]))
