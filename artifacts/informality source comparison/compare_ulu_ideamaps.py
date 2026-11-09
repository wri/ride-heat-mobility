"""Usage: python compare_ulu_ideamaps.py [repo root]  (prints tables; saved copy in comparison_output.txt).

ULU 'informal' (3) vs. 'informal + atomistic' (2+3) as slum definitions, against IDEAMAPS and
known settlements, and exposure at agents' homes (current 20k run)."""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from scipy.stats import spearmanr

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
ULU = ROOT / "data/raw/nairobi_ulu-all.tif"
IDEA = ROOT / "data/raw/ses/nairobi_ideamaps_morphological_informality.csv"
GPKG = ROOT / "outputs/heat_exposure_heat_20000agents_seed42.gpkg"

with rasterio.open(ULU) as r:
    arr = r.read(1); tr, crs, shape = r.transform, r.crs, r.shape
codes = np.where(np.isnan(arr), -1, arr).astype(np.int8); del arr
to_utm = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
MASKS = {"informal": codes == 3, "informal+atomistic": (codes == 3) | (codes == 2),
         "residential": np.isin(codes, [2, 3, 4, 5])}
SAT = {}
for k, m in MASKS.items():
    s = np.zeros((shape[0] + 1, shape[1] + 1), dtype=np.int32)
    np.cumsum(np.cumsum(m, axis=0, dtype=np.int32), axis=1, out=s[1:, 1:]); SAT[k] = s
TOT = {k: int(m.sum()) for k, m in MASKS.items()}
del MASKS


def boxes(x0, y0, x1, y1):
    inv = ~tr
    c0, r0 = inv * (np.asarray(x0), np.asarray(y0)); c1, r1 = inv * (np.asarray(x1), np.asarray(y1))
    f = lambda a, n: np.clip(a.astype(int), 0, n)
    return (f(np.floor(np.minimum(r0, r1)), shape[0]), f(np.ceil(np.maximum(r0, r1)), shape[0]),
            f(np.floor(np.minimum(c0, c1)), shape[1]), f(np.ceil(np.maximum(c0, c1)), shape[1]))


def counts(b, k):
    r0, r1, c0, c1 = b; s = SAT[k]
    return s[r1, c1] - s[r0, c1] - s[r1, c0] + s[r0, c0]


def shares(b):
    area = np.maximum((b[1] - b[0]) * (b[3] - b[2]), 1)
    return {k: counts(b, k) / area for k in SAT}


DEFS = ["informal", "informal+atomistic"]

# ---- 1. Known settlements (approximate lon/lat boxes) -----------------------------------------
PLACES = {"Kibera": (36.775, -1.322, 36.800, -1.305), "Mathare": (36.850, -1.266, 36.872, -1.255),
          "Mukuru": (36.870, -1.322, 36.900, -1.305), "Korogocho": (36.880, -1.248, 36.895, -1.238),
          "Karen (planned suburb)": (36.690, -1.340, 36.730, -1.300)}
print("1. Share of area in each ULU definition (approximate boxes)")
for p, (a0, b0, a1, b1) in PLACES.items():
    x0, y0 = to_utm.transform(a0, b0); x1, y1 = to_utm.transform(a1, b1)
    s = shares(boxes([x0], [y0], [x1], [y1]))
    print(f"  {p:24s} " + "  ".join(f"{d} {s[d][0]*100:5.1f}%" for d in DEFS)
          + f"  residential {s['residential'][0]*100:5.1f}%")

# ---- 2. IDEAMAPS cells ------------------------------------------------------------------------
idea = pd.read_csv(IDEA)
x0, y0 = to_utm.transform(idea.lon_min.to_numpy(), idea.lat_min.to_numpy())
x1, y1 = to_utm.transform(idea.lon_max.to_numpy(), idea.lat_max.to_numpy())
b = boxes(x0, y0, x1, y1)
cls = idea["result"].round().astype(int).map({0: "low", 1: "medium", 2: "high"})
area = np.maximum((b[1] - b[0]) * (b[3] - b[2]), 1)
print("\n2. Against IDEAMAPS cells")
for d in DEFS:
    n = counts(b, d); sh = n / area
    df = pd.DataFrame({"cls": cls, "sh": sh, "n": n})
    g = df.groupby("cls").agg(mean_share=("sh", "mean"), any_=("sh", lambda s: (s > 0).mean()),
                               maj=("sh", lambda s: (s >= 0.5).mean()), px=("n", "sum")).reindex(["low", "medium", "high"])
    g["where_%"] = g.px / g.px.sum() * 100
    print(f"  -- ULU {d}  (whole raster: {TOT[d]*25/1e6:.0f} km2)")
    print((g.drop(columns="px") * [100, 100, 100, 1]).round(1).to_string())
    hi = (cls == "high").to_numpy()
    print(f"     share of IDEAMAPS-high area that ULU calls {d}: {n[hi].sum()/area[hi].sum()*100:.0f}%;"
          f" share of ULU {d} area (inside IDEAMAPS extent) in high cells: {n[hi].sum()/n.sum()*100:.1f}%")
    res = counts(b, "residential")
    ok = res / area > 0.05
    print(f"     Spearman vs IDEAMAPS class: all cells {spearmanr(idea['result'], sh)[0]:.2f};"
          f" as share of residential area (cells >5% residential) {spearmanr(idea['result'][ok], (n/np.maximum(res,1))[ok])[0]:.2f}")

# ---- 3. Exposure at agents' homes (100 m box) -------------------------------------------------
a = gpd.read_file(GPKG, layer="agent_homes").to_crs(crs)
hx, hy = a.geometry.x.to_numpy(), a.geometry.y.to_numpy()
hs = shares(boxes(hx - 50, hy - 50, hx + 50, hy + 50))
e = a["heat_degC_min"].to_numpy()


def ci(x):
    bt = np.random.default_rng(0).choice(x, (2000, len(x))).mean(1)
    return f"{len(x):6,d}  {x.mean():4.0f} [{np.percentile(bt,2.5):.0f}-{np.percentile(bt,97.5):.0f}]  median {np.median(x):.0f}"


print("\n3. Mean daily exposure (degC.min) by home group, current run")
for lab in ["low", "medium", "high"]:
    print(f"  IDEAMAPS {lab:22s} {ci(e[(a.informality_label == lab).to_numpy()])}")
print(f"  IDEAMAPS no class          {ci(e[a.informality_label.isna().to_numpy()])}")
for d in DEFS:
    s = hs[d]
    for lab, m in [("none within 100 m", s == 0), ("1-49%", (s > 0) & (s < 0.5)), (">=50%", s >= 0.5)]:
        print(f"  ULU {d:18s} {lab:18s} {ci(e[m])}")
    hi_inf = (a.informality_label == "high").to_numpy()
    print(f"     ULU {d} >=50% homes that IDEAMAPS calls high: {(hi_inf & (s >= .5)).sum()/(s >= .5).sum()*100:.0f}%;"
          f" IDEAMAPS-high homes ULU {d} >=50%: {(hi_inf & (s >= .5)).sum()/hi_inf.sum()*100:.0f}%")
    # restrict to IDEAMAPS extent for a like-for-like gap
    inext = a.informality_label.notna().to_numpy()
    print(f"     within IDEAMAPS extent: >=50% {e[inext & (s>=.5)].mean():.0f} vs none {e[inext & (s==0)].mean():.0f}")
