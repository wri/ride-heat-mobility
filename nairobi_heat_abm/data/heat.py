from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
import rasterio.warp
import scipy.ndimage


@dataclass
class HeatSurface:
    array: np.ndarray       # shape (n_hours, rows, cols), float32, °C
    transform: rasterio.Affine
    hours: list[int]        # hour-of-day index per band, e.g. [6, 9, 12, 15, 18]
    crs: str
    name: str               # filename stem, used for display + RDM labelling


def load_heat_surface(
    tif_path: str | Path,
    target_hours: list[int] | None = None,
) -> HeatSurface:
    """
    Load a multi-band GeoTIFF heat surface. One band per hour.
    Reprojects to EPSG:4326 if needed. Casts to float32.
    """
    raise NotImplementedError


def sample_temperature(
    surface: HeatSurface,
    lons: np.ndarray,   # shape (N,)
    lats: np.ndarray,   # shape (N,)
    hour: int,
) -> np.ndarray:        # shape (N,) °C, float32
    """Bilinear interpolation of heat surface at agent positions."""
    hour_idx = min(range(len(surface.hours)), key=lambda i: abs(surface.hours[i] - hour))
    band = surface.array[hour_idx]

    inv = ~surface.transform
    cols = inv.a * lons + inv.b * lats + inv.c
    rows = inv.d * lons + inv.e * lats + inv.f

    result = scipy.ndimage.map_coordinates(band, [rows, cols], order=1, mode="nearest")
    return result.astype(np.float32)
