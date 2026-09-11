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
    dst_transform: rasterio.Affine | None = None,
    dst_shape: tuple[int, int] | None = None,
) -> tuple[np.ndarray, rasterio.Affine]:
    """
    Load WorldPop raster clipped to bbox. Reprojects to EPSG:4326 if needed.
    Returns (density_array, transform) where density_array is people-per-pixel.

    If dst_transform/dst_shape are given, reprojects onto that exact grid instead of
    computing its own — used by load_population_rasters() so multiple demographic-group
    rasters end up pixel-aligned with each other regardless of their own native
    resolution/extent/CRS, so per-pixel values across rasters can be compared directly.
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

        # rasterio.windows.from_bounds requires (right-left)/transform.a >= 0 and
        # (bottom-top)/transform.e >= 0 — i.e. the bound args must be ordered to match
        # the transform's own axis direction. Most rasters are north-up (transform.e < 0,
        # row 0 = north edge), but some WorldPop exports are south-up (transform.e > 0,
        # row 0 = south edge); swap bottom/top so the call is valid either way — the
        # result is the same window regardless, since from_bounds takes min/max over all
        # four corners internally.
        win_left, win_right = (src_left, src_right) if src.transform.a >= 0 else (src_right, src_left)
        win_bottom, win_top = (src_bottom, src_top) if src.transform.e < 0 else (src_top, src_bottom)
        window = rasterio.windows.from_bounds(
            win_left, win_bottom, win_right, win_top, transform=src.transform,
        ).round_lengths().round_offsets()
        window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))

        src_array = src.read(1, window=window)
        src_transform = src.window_transform(window)

        if dst_transform is None or dst_shape is None:
            dst_transform, dst_width, dst_height = rasterio.warp.calculate_default_transform(
                src.crs, dst_crs, window.width, window.height,
                left=src_left, bottom=src_bottom, right=src_right, top=src_top,
            )
        else:
            dst_height, dst_width = dst_shape
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


def load_population_rasters(
    tif_paths: dict[str, str | Path],
    bbox: tuple[float, float, float, float],  # (south, west, north, east)
) -> tuple[dict[str, np.ndarray], rasterio.Affine]:
    """
    Load multiple demographic-group WorldPop rasters (e.g. nairobipop_{total,children,
    adult,elderly,female}.tif) clipped to bbox, all reprojected onto the SAME target
    grid as "total" — so a given (row, col) means the same location in every returned
    array, and per-pixel values across rasters can be combined directly (see
    data/demographics.py::draw_age_gender_spatial).

    tif_paths must include a "total" key; it's loaded first to fix the grid that every
    other raster is reprojected onto, regardless of its own native resolution/extent.
    Returns ({key: density_array, ...}, transform).
    """
    total_array, transform = load_population_raster(tif_paths["total"], bbox)
    rasters: dict[str, np.ndarray] = {"total": total_array}
    dst_shape = total_array.shape

    for key, path in tif_paths.items():
        if key == "total":
            continue
        array, _ = load_population_raster(path, bbox, dst_transform=transform, dst_shape=dst_shape)
        rasters[key] = array

    return rasters, transform


def grid_transform_for_bbox(
    bbox: tuple[float, float, float, float],  # (south, west, north, east)
    shape: tuple[int, int],  # (rows, cols)
) -> rasterio.Affine:
    """Affine transform for a plain north-up grid covering bbox at the given shape —
    used for accumulator grids (e.g. model/simulation.py's time-density grid) that
    have no source raster of their own to inherit a transform from."""
    south, west, north, east = bbox
    rows, cols = shape
    return rasterio.transform.from_bounds(west, south, east, north, cols, rows)


def lonlat_to_rowcol(
    transform: rasterio.Affine,
    lons: np.ndarray,
    lats: np.ndarray,
    shape: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Inverse of rasterio.transform.xy: map lon/lat arrays to grid (row, col) indices
    for `transform`, clipped to `shape` so a position exactly on (or numerically just
    past, e.g. an agent standing at the bbox's own edge node) the grid's edge lands in
    the nearest valid cell instead of raising or silently falling outside it."""
    rows, cols = rasterio.transform.rowcol(transform, lons, lats)
    rows = np.clip(np.asarray(rows), 0, shape[0] - 1)
    cols = np.clip(np.asarray(cols), 0, shape[1] - 1)
    return rows, cols


def sample_spawn_nodes(
    density_array: np.ndarray,
    transform: rasterio.Affine,
    G: nx.MultiDiGraph,
    n_agents: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Weighted sample of grid cells by population density, snapped to nearest graph node.
    Returns (node_ids, rows, cols), each of shape (n_agents,): node_ids are graph node
    IDs; rows/cols are the sampled density_array cell indices themselves (before
    snapping), so callers can look up the same cells in other pixel-aligned rasters —
    see data/population.py::load_population_rasters and
    data/demographics.py::draw_age_gender_spatial.
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
    return np.array(node_ids, dtype=np.int64), np.asarray(rows), np.asarray(cols)
