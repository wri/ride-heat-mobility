from __future__ import annotations

from pathlib import Path

import numpy as np
import networkx as nx
import osmnx as ox
import rasterio
import rasterio.warp
import rasterio.windows
import rasterio.transform


def load_population_raster(
    tif_path: str | Path,
    bbox: tuple[float, float, float, float],  # (south, west, north, east)
) -> tuple[np.ndarray, rasterio.Affine]:
    """
    Load WorldPop raster clipped to bbox. Reprojects to EPSG:4326 if needed.
    Returns (density_array, transform) where density_array is people-per-pixel.
    """
    south, west, north, east = bbox
    dst_crs = "EPSG:4326"

    with rasterio.open(tif_path) as src:
        # bbox is in EPSG:4326; translate to the source CRS before windowing,
        # since the source (e.g. a UTM-projected WorldPop clip) may use a
        # different CRS and extent than the query bbox.
        if src.crs is not None and src.crs.to_string() != dst_crs:
            src_left, src_bottom, src_right, src_top = rasterio.warp.transform_bounds(
                dst_crs, src.crs, west, south, east, north,
            )
        else:
            src_left, src_bottom, src_right, src_top = west, south, east, north

        window = rasterio.windows.from_bounds(
            src_left, src_bottom, src_right, src_top, transform=src.transform,
        ).round_lengths().round_offsets()
        window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))

        src_array = src.read(1, window=window)
        src_transform = src.window_transform(window)

        dst_transform, dst_width, dst_height = rasterio.warp.calculate_default_transform(
            src.crs, dst_crs, window.width, window.height,
            left=src_left, bottom=src_bottom, right=src_right, top=src_top,
        )
        dst_array = np.empty((dst_height, dst_width), dtype=np.float32)
        rasterio.warp.reproject(
            source=src_array,
            destination=dst_array,
            src_transform=src_transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=rasterio.warp.Resampling.bilinear,
        )
        nodata = src.nodata

    if nodata is not None:
        dst_array[dst_array == nodata] = np.nan
    dst_array[dst_array < 0] = np.nan

    return dst_array, dst_transform


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
