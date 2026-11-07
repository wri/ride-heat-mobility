"""
Neighbourhood + socioeconomic context for agents' home locations.

Sources (all downloaded to data/raw/ses/, see config.yaml `paths.ses`):
- Wards: geoBoundaries KEN ADM3 (2020 IEBC wards, CC BY 4.0).
- Relative Wealth Index: Data for Good at Meta, ~2.4 km Bing-quadkey (zoom 14) tiles,
  given as tile-centre points; relative within Kenya, not an absolute income (CC BY-NC 4.0).
- Morphological informality: IDEAMAPS, "Morphological Informality Modelled Dataset in
  Nairobi, Kenya" v2 (Hafner et al. 2026, Zenodo, doi:10.5281/zenodo.18313572; the file
  is the record's model-outputs.csv). 100 m cells of the GHS grid classed from building
  and road morphology, 0=low / 1=medium / 2=high, as an indication of deprivation
  (CC BY-NC 4.0). Column "focused" marks validation focus areas and is not used. Covers
  Nairobi's built-up core (lon 36.61-37.04, lat -1.42 to -1.12), not the whole study bbox.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import box

CRS = "EPSG:4326"
INFORMALITY_LABELS = {0: "low", 1: "medium", 2: "high"}

# Zoom-14 quadkey tiles are 360/2**14 ≈ 0.022° wide; a point inside a tile is at most
# half a diagonal (≈ 0.0155°) from its centre. Anything farther is outside RWI coverage.
_RWI_MAX_DIST_DEG = 0.016


def _bbox_poly(bbox: tuple[float, float, float, float]):
    south, west, north, east = bbox
    return box(west, south, east, north)


def load_wards(path: str | Path, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Ward polygons intersecting bbox (south, west, north, east): ward_id, ward, geometry."""
    g = gpd.read_file(path).to_crs(CRS)
    g = g[g.intersects(_bbox_poly(bbox))]
    return gpd.GeoDataFrame(
        {"ward_id": g["shapeID"].to_numpy(), "ward": g["shapeName"].to_numpy()},
        geometry=g.geometry.to_numpy(), crs=CRS,
    ).reset_index(drop=True)


def load_rwi(path: str | Path, bbox: tuple[float, float, float, float], margin_deg: float = 0.03) -> pd.DataFrame:
    """Relative Wealth Index tile centres (latitude, longitude, rwi, error) within bbox + margin."""
    south, west, north, east = bbox
    df = pd.read_csv(path)
    keep = (
        df["latitude"].between(south - margin_deg, north + margin_deg)
        & df["longitude"].between(west - margin_deg, east + margin_deg)
    )
    return df[keep].reset_index(drop=True)


def load_informality(path: str | Path, bbox: tuple[float, float, float, float]) -> pd.DataFrame:
    """IDEAMAPS morphological-informality grid cells overlapping bbox."""
    south, west, north, east = bbox
    df = pd.read_csv(path)
    keep = (df["lat_max"] >= south) & (df["lat_min"] <= north) & (df["lon_max"] >= west) & (df["lon_min"] <= east)
    df = df[keep].reset_index(drop=True)
    df["result"] = df["result"].astype(int)
    return df


def tag_homes(
    lons: np.ndarray,
    lats: np.ndarray,
    wards: gpd.GeoDataFrame | None = None,
    rwi: pd.DataFrame | None = None,
    informality: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Per-point neighbourhood/SES attributes. Columns (each only if its layer is given):
    ward_id, ward; rwi, rwi_error; informality (0/1/2, NaN outside coverage),
    informality_label. Rows align with the input arrays.
    """
    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)
    out = pd.DataFrame(index=np.arange(len(lons)))

    if wards is not None:
        pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lons, lats), crs=CRS)
        joined = gpd.sjoin(pts, wards[["ward_id", "ward", "geometry"]], how="left", predicate="within")
        joined = joined[~joined.index.duplicated(keep="first")]  # a point on a shared border
        out["ward_id"] = joined["ward_id"].to_numpy()
        out["ward"] = joined["ward"].to_numpy()

    if rwi is not None and len(rwi):
        tree = cKDTree(np.column_stack([rwi["longitude"], rwi["latitude"]]))
        dist, idx = tree.query(np.column_stack([lons, lats]))
        ok = dist <= _RWI_MAX_DIST_DEG
        out["rwi"] = np.where(ok, rwi["rwi"].to_numpy()[idx], np.nan)
        out["rwi_error"] = np.where(ok, rwi["error"].to_numpy()[idx], np.nan)

    if informality is not None and len(informality):
        tree = cKDTree(np.column_stack([informality["longitude"], informality["latitude"]]))
        _, idx = tree.query(np.column_stack([lons, lats]))
        cell = informality.iloc[idx]
        inside = (
            (lons >= cell["lon_min"].to_numpy()) & (lons <= cell["lon_max"].to_numpy())
            & (lats >= cell["lat_min"].to_numpy()) & (lats <= cell["lat_max"].to_numpy())
        )
        out["informality"] = np.where(inside, cell["result"].to_numpy(), np.nan)
        out["informality_label"] = pd.Series(out["informality"]).map(INFORMALITY_LABELS)

    return out


def ward_exposure_layer(agents: pd.DataFrame, wards: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Ward polygons with agent counts and exposure summaries, from a per-agent frame with
    columns ward_id, exposure_degC_min, travelled (bool), and optionally rwi / informality.
    Exposure stats are over agents who travelled (any time outdoors; not exposure > 0, which
    drops travellers who stayed below the UTCI threshold); wards with no resident
    agents are kept with NaN stats so the map shows them as no-data, not as zero.
    """
    g = agents.groupby("ward_id")
    travelled = agents[agents["travelled"]].groupby("ward_id")["exposure_degC_min"]
    summary = pd.DataFrame({
        "n_agents": g.size(),
        "n_travelled": g["travelled"].sum(),
        "mean_heat_degC_min": travelled.mean(),
        "median_heat_degC_min": travelled.median(),
        "p90_heat_degC_min": travelled.quantile(0.9),
    })
    if "rwi" in agents:
        summary["mean_rwi"] = g["rwi"].mean()
    if "informality" in agents:
        inf = agents.dropna(subset=["informality"]).groupby("ward_id")["informality"]
        summary["share_medium_high_informality"] = inf.apply(lambda s: (s >= 1).mean())
    out = wards.merge(summary, left_on="ward_id", right_index=True, how="left")
    out["n_agents"] = out["n_agents"].fillna(0).astype(int)
    out["n_travelled"] = out["n_travelled"].fillna(0).astype(int)
    return out
