from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np

from nairobi_heat_abm.model.agent import DemographicParams, GENDER_FEMALE, SES_FORMAL, SES_INFORMAL


def draw_age_gender(
    demo: DemographicParams,
    n: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Independent weighted draws of age group and gender for n agents, from
    demo.age_group_shares / demo.gender_shares. Not spatial — location-independent.
    """
    age_codes = np.array(list(demo.age_group_shares.keys()), dtype=np.uint8)
    age_probs = np.array(list(demo.age_group_shares.values()), dtype=np.float64)
    age_probs /= age_probs.sum()
    age_group = age_codes[rng.choice(len(age_codes), size=n, p=age_probs)]

    gender_codes = np.array(list(demo.gender_shares.keys()), dtype=np.uint8)
    gender_probs = np.array(list(demo.gender_shares.values()), dtype=np.float64)
    gender_probs /= gender_probs.sum()
    gender = gender_codes[rng.choice(len(gender_codes), size=n, p=gender_probs)]

    return age_group, gender


def draw_age_gender_spatial(
    rasters: dict[str, np.ndarray],
    rows: np.ndarray,
    cols: np.ndarray,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Spatially-varying age/gender draw from per-pixel demographic-group population
    counts (nairobipop_{total,children,adult,elderly,female}.tif, loaded via
    data/population.py::load_population_rasters onto a shared grid). For each agent,
    (rows[i], cols[i]) is the density cell it was spawned in
    (data/population.py::sample_spawn_nodes) — age group and gender are drawn from
    that cell's local composition, so e.g. an agent spawned in a pixel with a high
    elderly share is more likely to be drawn as elderly.

    Only "children" (age <=14), "adult" (age >=20, includes elderly), "elderly"
    (age >=60), and "female" (any age) group counts are available — not a full
    age x sex cross-tabulation — so the four AGE_* bins are reconstructed from these
    overlapping counts:
      - child  = children raster directly
      - elderly = elderly raster directly
      - adult  = adult raster minus elderly (elderly is a subset of the 20+ adult count)
      - youth  = residual (total minus children minus adult), i.e. the 15-19 gap not
                 covered by any raster
    and gender is drawn independently of age, from the female raster's local share
    (male is the residual). Because each raster is reprojected independently, per-pixel
    values can fail to sum to exactly "total" near demographic boundaries (bilinear
    interpolation doesn't preserve that identity) — probabilities are clipped to >=0 and
    renormalized per agent rather than trusted to sum to 1 on their own.
    """
    total = rasters["total"][rows, cols].astype(np.float64)
    children = np.nan_to_num(rasters["children"][rows, cols]).astype(np.float64)
    adult20 = np.nan_to_num(rasters["adult"][rows, cols]).astype(np.float64)
    elderly = np.nan_to_num(rasters["elderly"][rows, cols]).astype(np.float64)
    female = np.nan_to_num(rasters["female"][rows, cols]).astype(np.float64)

    p_child = children / total
    p_elderly = elderly / total
    p_adult = (adult20 - elderly) / total
    p_youth = 1.0 - p_child - p_elderly - p_adult

    # Order matches AGE_CHILD=0, AGE_YOUTH=1, AGE_ADULT=2, AGE_ELDERLY=3.
    age_probs = np.clip(np.stack([p_child, p_youth, p_adult, p_elderly], axis=1), 0.0, None)
    age_probs /= age_probs.sum(axis=1, keepdims=True)

    n = len(rows)
    r = rng.random(n)
    age_cum = np.cumsum(age_probs, axis=1)
    # Count how many cumulative bins r has passed -> first bin where r <= cum, vectorized.
    age_group = (r[:, None] > age_cum).sum(axis=1).astype(np.uint8)

    p_female = np.clip(female / total, 0.0, 1.0)
    gender = np.where(rng.random(n) < p_female, GENDER_FEMALE, 1 - GENDER_FEMALE).astype(np.uint8)

    return age_group, gender


def load_informal_settlement_boundaries(path: str | Path | None) -> gpd.GeoDataFrame | None:
    """
    Loads a vector file (e.g. GeoJSON) of informal-settlement boundary polygons.
    Returns None if no path is given — real Nairobi boundary data is not yet available;
    callers must treat that as "no SES data", not silently skip the field.
    """
    if path is None:
        return None
    gdf = gpd.read_file(path)
    if gdf.crs is not None and gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


def assign_ses(
    spawn_nodes: np.ndarray,
    G: nx.MultiDiGraph,
    boundary_gdf: gpd.GeoDataFrame | None,
) -> np.ndarray:
    """
    Point-in-polygon test of each agent's spawn-node coordinates against
    boundary_gdf. boundary_gdf=None means no real boundary data is available yet,
    so every agent is assigned SES_FORMAL (documented placeholder, not a silent
    failure — see DemographicParams.informal_settlement_path).
    """
    if boundary_gdf is None or boundary_gdf.empty:
        return np.full(len(spawn_nodes), SES_FORMAL, dtype=np.uint8)

    lons = np.array([G.nodes[int(nid)]["x"] for nid in spawn_nodes])
    lats = np.array([G.nodes[int(nid)]["y"] for nid in spawn_nodes])
    points = gpd.GeoSeries(gpd.points_from_xy(lons, lats), crs="EPSG:4326")

    boundary = boundary_gdf.geometry.union_all()
    # intersects (inclusive of the boundary edge) rather than within (strict interior) —
    # a graph node that snaps exactly onto a settlement boundary line should still count.
    inside = points.intersects(boundary).to_numpy()
    return np.where(inside, SES_INFORMAL, SES_FORMAL).astype(np.uint8)
