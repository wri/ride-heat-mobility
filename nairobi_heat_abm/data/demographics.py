from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np

from nairobi_heat_abm.model.agent import DemographicParams, SES_FORMAL, SES_INFORMAL


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
