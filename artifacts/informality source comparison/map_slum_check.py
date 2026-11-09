"""Usage: python map_slum_check.py [repo root] [out dir]  -> ulu_vs_ideamaps_slums.png. Needs internet (Esri tiles).

Maps: does ULU / IDEAMAPS mark Nairobi's known informal settlements?
Rows = places; columns = satellite imagery (Esri World Imagery), IDEAMAPS class, ULU class."""
import io
import math
import os
import sys
from pathlib import Path

import rasterio  # noqa: E402  (set PROJ paths to rasterio's own before use)
os.environ["PROJ_DATA"] = os.environ["PROJ_LIB"] = str(Path(rasterio.__file__).parent / "proj_data")
os.environ["GDAL_DATA"] = str(Path(rasterio.__file__).parent / "gdal_data")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from matplotlib.collections import PatchCollection
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch, Rectangle
from PIL import Image
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds

HERE = Path(__file__).resolve().parent
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[1]
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE
ULU = ROOT / "data/raw/nairobi_ulu-all.tif"
IDEA = ROOT / "data/raw/ses/nairobi_ideamaps_morphological_informality.csv"

HALF_W, HALF_H = 0.0125, 0.0095  # ~2.8 x 2.1 km
PLACES = [("Kibera", 36.7875, -1.3130), ("Mathare", 36.8600, -1.2600),
          ("Mukuru", 36.8820, -1.3130), ("Karen (planned suburb, control)", 36.7100, -1.3200)]

ULU_NAMES = ["Open space", "Non-residential", "Atomistic", "Informal", "Formal", "Housing project"]
ULU_COLS = ["#f2efe6", "#b9b6ad", "#7b3fa0", "#d7301f", "#4a7fc1", "#3fa39b"]
IDEA_NAMES = ["Low", "Medium", "High"]
IDEA_COLS = ["#fbe9c9", "#f39c4a", "#8c1d18"]

idea = pd.read_csv(IDEA)
idea["cls"] = idea["result"].round().astype(int)


def tiles(lon0, lat0, lon1, lat1, z=17):
    def xy(lon, lat):
        n = 2 ** z
        x = (lon + 180) / 360 * n
        y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
        return x, y
    x0, y1 = xy(lon0, lat0); x1, y0 = xy(lon1, lat1)
    tx = range(int(x0), int(x1) + 1); ty = range(int(y0), int(y1) + 1)
    img = Image.new("RGB", (256 * len(tx), 256 * len(ty)))
    s = requests.Session(); s.headers["User-Agent"] = "nairobi-heat-abm-figure"
    for i, x in enumerate(tx):
        for j, y in enumerate(ty):
            for attempt in range(6):
                r = s.get(f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", timeout=30)
                if r.ok:
                    break
                import time; time.sleep(1 + attempt)
            r.raise_for_status()
            img.paste(Image.open(io.BytesIO(r.content)).convert("RGB"), (256 * i, 256 * j))
    def inv(x, y):
        n = 2 ** z
        lon = x / n * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        return lon, lat
    L, T = inv(tx[0], ty[0]); R, B = inv(tx[-1] + 1, ty[-1] + 1)
    return np.asarray(img), (L, R, B, T)


fig, axes = plt.subplots(len(PLACES), 3, figsize=(11, 3.05 * len(PLACES)), constrained_layout=True)
with rasterio.open(ULU) as src, WarpedVRT(src, crs="EPSG:4326", resampling=Resampling.nearest) as vrt:
    for row, (name, lon, lat) in enumerate(PLACES):
        b = (lon - HALF_W, lat - HALF_H, lon + HALF_W, lat + HALF_H)
        ext = (b[0], b[2], b[1], b[3])
        # satellite
        im, e = tiles(*b)
        axes[row, 0].imshow(im, extent=e)
        # IDEAMAPS
        ax = axes[row, 1]
        sub = idea[(idea.lon_max > b[0]) & (idea.lon_min < b[2]) & (idea.lat_max > b[1]) & (idea.lat_min < b[3])]
        ax.add_collection(PatchCollection(
            [Rectangle((r.lon_min, r.lat_min), r.lon_max - r.lon_min, r.lat_max - r.lat_min) for r in sub.itertuples()],
            facecolors=[IDEA_COLS[c] for c in sub.cls], edgecolors="none"))
        ax.set_facecolor("#ffffff")
        hi = (sub.cls == 2).mean() * 100
        # ULU
        w = from_bounds(*b, transform=vrt.transform)
        u = vrt.read(1, window=w)
        uc = np.where(np.isnan(u), -1, u).astype(int)
        um = np.ma.masked_less(uc, 0)
        axes[row, 2].imshow(um, extent=ext, cmap=ListedColormap(ULU_COLS), vmin=-0.5, vmax=5.5,
                            interpolation="nearest")
        valid = uc >= 0
        inf = (uc[valid] == 3).mean() * 100; atom = (uc[valid] == 2).mean() * 100
        titles = [f"{name}\nsatellite (Esri World Imagery)",
                  f"IDEAMAPS: {hi:.0f}% of cells high",
                  f"ULU: {inf:.0f}% informal, {atom:.1f}% atomistic"]
        for c in range(3):
            a = axes[row, c]
            a.set_xlim(b[0], b[2]); a.set_ylim(b[1], b[3]); a.set_aspect("equal")
            a.set_xticks([]); a.set_yticks([])
            a.set_title(titles[c], fontsize=9, loc="left")
        # scale bar 1 km
        a = axes[row, 0]; km = 1 / 111.32
        x0 = b[0] + 0.0015; y0 = b[1] + 0.0015
        a.plot([x0, x0 + km], [y0, y0], color="white", lw=2.5)
        a.text(x0 + km / 2, y0 + 0.0007, "1 km", color="white", ha="center", fontsize=7.5)

fig.legend(handles=[Patch(color=c, label=f"IDEAMAPS {n}") for n, c in zip(IDEA_NAMES, IDEA_COLS)],
           loc="lower center", bbox_to_anchor=(0.52, -0.035), ncol=3, fontsize=8, frameon=False)
fig.legend(handles=[Patch(color=c, label=f"ULU {n}") for n, c in zip(ULU_NAMES, ULU_COLS)],
           loc="lower center", bbox_to_anchor=(0.52, -0.06), ncol=6, fontsize=8, frameon=False)
fig.text(0.0, -0.075, "Imagery: Esri, Maxar, Earthstar Geographics. IDEAMAPS morphological informality, Nairobi v2 "
         "(100 m, CC BY-NC 4.0). WRI CIF Urban Land Use V1 (5 m). Boxes ~2.8 x 2.1 km, centred by hand.",
         fontsize=7, color="#555")
fig.savefig(OUT / "ulu_vs_ideamaps_slums.png", dpi=150, bbox_inches="tight")
print("saved", OUT / "ulu_vs_ideamaps_slums.png")
