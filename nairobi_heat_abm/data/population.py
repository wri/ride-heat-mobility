from __future__ import annotations

from pathlib import Path

import numpy as np
import networkx as nx
import osmnx as ox
import rasterio
import rasterio.warp
import rasterio.transform


def load_population_raster(
    tif_path: str | Path,
    bbox: tuple[float, float, float, float],  # (south, west, north, east)
) -> tuple[np.ndarray, rasterio.Affine]:
    """
    Load WorldPop raster clipped to bbox. Reprojects to EPSG:4326 if needed.
    Returns (density_array, transform) where density_array is people-per-pixel.
    """
    raise NotImplementedError


def sample_spawn_nodes(
    density_array: np.ndarray,
    transform: rasterio.Affine,
    G: nx.MultiDiGraph,
    n_agents: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Weighted sample of grid cells by population density, snapped to nearest graph node.
    Returns array of shape (n_agents,) with graph node IDs.
    """
    flat = density_array.flatten().astype(np.float64)
    valid = np.isfinite(flat) & (flat > 0)
    probs = np.where(valid, flat, 0.0)
    probs /= probs.sum()

    flat_indices = rng.choice(len(flat), size=n_agents, p=probs)
    rows, cols = np.unravel_index(flat_indices, density_array.shape)
    lons, lats = rasterio.transform.xy(transform, rows, cols)
    lons, lats = np.array(lons), np.array(lats)

    node_ids = ox.nearest_nodes(G, X=lons, Y=lats)
    return np.array(node_ids, dtype=np.int64)
