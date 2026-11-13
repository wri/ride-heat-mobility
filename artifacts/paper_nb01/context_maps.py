"""
Context maps of the model's inputs, for the data / study-area section:
  fig_ctx_network.{svg,png}     OSM walking network and matatu stands (GTFS stops)
  fig_ctx_population.{svg,png}  WorldPop population density
  fig_ctx_amenities.{svg,png}   destinations by type (school, market, other; work not shown)
Same frame, place labels and scale bar as the other paper maps. No titles (captions carry them).

Run from the repo root:  .venv/Scripts/python.exe artifacts/paper_nb01/context_maps.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile
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
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patheffects as pe  # noqa: E402
import numpy as np  # noqa: E402
import osmnx as ox  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
import yaml  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, LogNorm  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402
from rasterio.vrt import WarpedVRT  # noqa: E402
from shapely.geometry import box  # noqa: E402

sys.path.insert(0, str(HERE))
from run_config import N_AGENTS  # noqa: E402

BBOX = (36.649, -1.444, 37.104, -1.163)  # west, south, east, north (config.yaml)
CRS_M = "EPSG:32737"
PATHS = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))["paths"]
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
mpl.rcParams.update({
    "font.family": "Arial", "font.size": 9, "legend.frameon": False, "svg.fonttype": "none",
    "savefig.dpi": 300, "figure.dpi": 150,
})
FS = 1.25  # label scale for full-width single maps (as fig_ward_exposure_map)

frame = gpd.GeoDataFrame(geometry=[box(*BBOX)], crs="EPSG:4326").to_crs(CRS_M)
wards = gpd.read_file(ROOT / "outputs" / f"heat_exposure_heat_{N_AGENTS}agents_seed42.gpkg", layer="wards")
wards_m = gpd.clip(wards.to_crs(CRS_M), frame)

# ---- shared map furniture (as make_figures.py) -----------------------------------------
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
    halo = [pe.withStroke(linewidth=2.0, foreground="white")]
    for label, names in PLACES.items():
        sel = wards_m[wards_m["ward"].isin(names)]
        if sel.empty:
            continue
        pt = sel.geometry.union_all().representative_point()
        ax.plot(pt.x, pt.y, marker="o", ms=2.6, mfc=INK, mec="white", mew=0.6, zorder=7)
        dx, dy, ha, va = PLACE_OFFSETS.get(label, (450, 350, "left", "bottom"))
        ax.text(pt.x + dx, pt.y + dy, label, fontsize=fontsize, color=INK, ha=ha, va=va, path_effects=halo, zorder=7)


def scalebar(ax, km: float = 5, loc=(0.06, 0.06)) -> None:
    x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
    x = x0 + loc[0] * (x1 - x0); y = y0 + loc[1] * (y1 - y0)
    ax.add_patch(mpl.patches.Rectangle((x - 0.012 * (x1 - x0), y - 0.025 * (y1 - y0)), km * 1000 + 0.024 * (x1 - x0),
                                       0.11 * (y1 - y0), facecolor="white", edgecolor="none", alpha=0.9, zorder=8))
    ax.plot([x, x + km * 1000], [y, y], color=INK, lw=1.4, solid_capstyle="butt", zorder=9)
    ax.text(x + km * 500, y + 0.015 * (y1 - y0), f"{km:g} km", ha="center", va="bottom", fontsize=7 * FS, zorder=9)


def new_map():
    fig, ax = plt.subplots(figsize=(6.5, 4.7))
    b = frame.total_bounds
    ax.set_xlim(b[0], b[2]); ax.set_ylim(b[1], b[3]); ax.set_aspect("equal"); ax.set_axis_off()
    return fig, ax


def finish(fig, ax, name: str) -> None:
    wards_m.boundary.plot(ax=ax, color="#c9c7bf", lw=0.3, zorder=1, rasterized=True)
    add_places(ax)
    scalebar(ax)
    for ext in ("svg", "png"):
        fig.savefig(HERE / f"{name}.{ext}", bbox_inches="tight", pad_inches=0.02, facecolor="white")
    plt.close(fig)
    print("wrote", name)


# ---- data ------------------------------------------------------------------------------
print("loading street graph ...")
G = ox.load_graphml(ROOT / PATHS["graph_cache"])
_, edges = ox.graph_to_gdfs(G, nodes=True, edges=True)
streets = edges[~edges.get("edge_type", pd.Series(index=edges.index, dtype=object)).isin(["transit", "access_link"])]
streets = gpd.clip(streets.to_crs(CRS_M), frame)

with zipfile.ZipFile(ROOT / PATHS["gtfs_path"]) as z:
    name = next(n for n in z.namelist() if n.endswith("stops.txt"))
    stops = pd.read_csv(io.BytesIO(z.read(name)))
stops = gpd.GeoDataFrame(stops, geometry=gpd.points_from_xy(stops.stop_lon, stops.stop_lat), crs="EPSG:4326").to_crs(CRS_M)
stops = gpd.clip(stops, frame)

# ---- Figure: walking network and matatu stands -------------------------------------------
fig, ax = new_map()
streets.plot(ax=ax, color="#9a9890", lw=0.18, zorder=2, rasterized=True)
stops.plot(ax=ax, color="#2a78d6", markersize=2.2, linewidth=0, zorder=3, rasterized=True)
ax.legend(handles=[mpl.lines.Line2D([], [], color="#9a9890", lw=1, label=f"Walkable street or path (OpenStreetMap)"),
                   mpl.lines.Line2D([], [], color="#2a78d6", marker="o", ms=4, lw=0,
                                    label=f"Matatu stand ({len(stops):,}, DigitalMatatus GTFS 2019)")],
          loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=2, fontsize=7 * FS, handlelength=1.6)
finish(fig, ax, "fig_ctx_network")

# ---- Figure: population density (WorldPop) -----------------------------------------------
b = frame.total_bounds
res = 100.0
with rasterio.open(ROOT / PATHS["worldpop_tif"]) as src:
    w, h = int((b[2] - b[0]) / res), int((b[3] - b[1]) / res)
    tr = rasterio.transform.from_origin(b[0], b[3], res, res)
    # people per source cell -> people per km2 of that cell
    cell_km2 = (abs(src.res[0] * src.res[1]) / 1e6 if src.crs.is_projected
                else (abs(src.res[0] * src.res[1]) * 111.32 ** 2))
    with WarpedVRT(src, crs=CRS_M, transform=tr, width=w, height=h, resampling=Resampling.nearest) as vrt:
        pop = vrt.read(1).astype(float)
dens = np.ma.masked_invalid(pop / cell_km2)
dens = np.ma.masked_less_equal(dens, 1.0)
src_res_m = np.sqrt(cell_km2) * 1000
BLUES = LinearSegmentedColormap.from_list("one_hue", ["#e6eef8", "#9ec5f4", "#3987e5", "#1c5cab", "#0d366b"])
fig, ax = new_map()
im = ax.imshow(dens, extent=(b[0], b[2], b[1], b[3]), cmap=BLUES, norm=LogNorm(100, 100_000),
               interpolation="nearest", zorder=0, rasterized=True)
cb = fig.colorbar(im, ax=ax, orientation="horizontal", fraction=0.05, pad=0.02, aspect=30, extend="both")
cb.set_label("Population density (people per km², WorldPop, log scale)", fontsize=7 * FS)
cb.outline.set_linewidth(0.4); cb.ax.tick_params(labelsize=6.5 * FS, width=0.5)
finish(fig, ax, "fig_ctx_population")
print(f"WorldPop source cell ~{src_res_m:.0f} m; density range {dens.min():.0f}-{dens.max():.0f} per km2")

# ---- Figure: destinations by type (work not shown) ----------------------------------------
amen = json.loads((ROOT / PATHS["amenity_cache"]).read_text())
CATS = [("school", "School, college, university", "#2a78d6"),
        ("food", "Market (supermarket, marketplace)", "#eb6834"),
        ("other", "Other (worship, community centre, library)", "#1baf7a")]
fig, ax = new_map()
streets.plot(ax=ax, color="#e3e1da", lw=0.15, zorder=1, rasterized=True)
handles = []
for key, label, col in CATS:
    ids = [n for n in amen.get(key, []) if n in G.nodes]
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy([G.nodes[n]["x"] for n in ids], [G.nodes[n]["y"] for n in ids]),
                           crs="EPSG:4326").to_crs(CRS_M)
    pts = gpd.clip(pts, frame)
    pts.plot(ax=ax, color=col, markersize=3.5, linewidth=0, alpha=0.85, zorder=3, rasterized=True)
    handles.append(mpl.lines.Line2D([], [], color=col, marker="o", ms=4.5, lw=0, label=f"{label} ({len(pts):,})"))
ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=2, fontsize=7 * FS, handlelength=1.0)
finish(fig, ax, "fig_ctx_amenities")
