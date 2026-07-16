from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
import rasterio.merge
import rasterio.transform
import rasterio.warp
import scipy.ndimage

# WRI TCM tile output, e.g. "UTCI_2024_164_1500D.tif" = day 164 of 2024, 15:00 local.
_UTCI_FILENAME_RE = re.compile(r"UTCI_(\d{4})_(\d{3})_(\d{2})(\d{2})D\.tif$")


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
    Also accepts a directory of single-band TIFs (sorted alphabetically, indexed 0…n-1).
    Reprojects to EPSG:4326 if needed. Casts to float32.
    """
    tif_path = Path(tif_path)
    dst_crs = "EPSG:4326"

    if tif_path.is_dir():
        files = sorted(tif_path.glob("*.tif")) + sorted(tif_path.glob("*.tiff"))
        if not files:
            raise FileNotFoundError(f"No .tif/.tiff files in {tif_path}")
        all_hours = list(range(len(files)))
        selected = [
            (i, f) for i, f in enumerate(files)
            if target_hours is None or i in target_hours
        ]
        bands, dst_transform, crs_str = [], None, dst_crs
        for _idx, f in selected:
            with rasterio.open(f) as src:
                tr, w, h = rasterio.warp.calculate_default_transform(
                    src.crs, dst_crs, src.width, src.height, *src.bounds
                )
                band = np.empty((h, w), dtype=np.float32)
                rasterio.warp.reproject(
                    source=rasterio.band(src, 1),
                    destination=band,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=tr,
                    dst_crs=dst_crs,
                    resampling=rasterio.warp.Resampling.bilinear,
                )
                if src.nodata is not None:
                    band[band == src.nodata] = np.nan
                bands.append(band)
                dst_transform = tr
                crs_str = src.crs.to_string()
        hours = [all_hours[i] for i, _ in selected]
        return HeatSurface(
            array=np.stack(bands).astype(np.float32),
            transform=dst_transform,
            hours=hours,
            crs=crs_str,
            name=tif_path.stem,
        )

    # Multi-band GeoTIFF
    with rasterio.open(tif_path) as src:
        n_bands = src.count
        all_hours = list(range(n_bands))
        band_indices = [
            i + 1 for i in all_hours
            if target_hours is None or i in target_hours
        ]
        hours = [i for i in all_hours if target_hours is None or i in target_hours]

        dst_transform, w, h = rasterio.warp.calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        array = np.empty((len(band_indices), h, w), dtype=np.float32)
        for out_i, band_i in enumerate(band_indices):
            rasterio.warp.reproject(
                source=rasterio.band(src, band_i),
                destination=array[out_i],
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=rasterio.warp.Resampling.bilinear,
            )
        if src.nodata is not None:
            array[array == src.nodata] = np.nan
        crs_str = src.crs.to_string()

    return HeatSurface(
        array=array,
        transform=dst_transform,
        hours=hours,
        crs=crs_str,
        name=tif_path.stem,
    )


def load_utci_tiles(
    tile_root: str | Path,
    target_hours: list[int] | None = None,
) -> HeatSurface:
    """
    Load a WRI TCM UTCI heat surface split across a regular grid of non-overlapping
    UTM tiles: `<tile>/tcm_results/UTCI_<year>_<day-of-year>_<HHMM>D.tif`.
    Mosaics all tiles sharing a timestamp, then reprojects the mosaic to EPSG:4326.
    Assumes a single calendar date across all tiles (multiple times of day are fine).
    """
    tile_root = Path(tile_root)
    dst_crs = "EPSG:4326"

    files = list(tile_root.glob("**/tcm_results/UTCI_*.tif"))
    if not files:
        raise FileNotFoundError(f"No UTCI_*.tif files under {tile_root}/**/tcm_results/")

    by_timestamp: dict[tuple[int, int, int], list[Path]] = defaultdict(list)
    for f in files:
        m = _UTCI_FILENAME_RE.search(f.name)
        if not m:
            continue
        year, doy, hh, _mm = (int(g) for g in m.groups())
        by_timestamp[(year, doy, hh)].append(f)

    if not by_timestamp:
        raise ValueError(
            f"No filenames under {tile_root} matched UTCI_<year>_<day-of-year>_<HHMM>D.tif"
        )

    dates = {(year, doy) for year, doy, _hh in by_timestamp}
    if len(dates) > 1:
        raise ValueError(f"Expected a single calendar date across UTCI tiles, found {sorted(dates)}")
    year, doy = next(iter(dates))

    all_hours = sorted(hh for _year, _doy, hh in by_timestamp)
    selected_hours = [h for h in all_hours if target_hours is None or h in target_hours]

    bands, dst_transform, crs_str = [], None, dst_crs
    for hh in selected_hours:
        datasets = [rasterio.open(p) for p in by_timestamp[(year, doy, hh)]]
        try:
            mosaic, mosaic_transform = rasterio.merge.merge(datasets)
            src_crs = datasets[0].crs
            src_nodata = datasets[0].nodata
        finally:
            for ds in datasets:
                ds.close()
        mosaic = mosaic[0]  # single band per tile

        src_bounds = rasterio.transform.array_bounds(mosaic.shape[0], mosaic.shape[1], mosaic_transform)
        tr, w, h = rasterio.warp.calculate_default_transform(
            src_crs, dst_crs, mosaic.shape[1], mosaic.shape[0], *src_bounds,
        )
        band = np.empty((h, w), dtype=np.float32)
        rasterio.warp.reproject(
            source=mosaic,
            destination=band,
            src_transform=mosaic_transform,
            src_crs=src_crs,
            dst_transform=tr,
            dst_crs=dst_crs,
            resampling=rasterio.warp.Resampling.bilinear,
        )
        if src_nodata is not None:
            band[band == src_nodata] = np.nan
        bands.append(band)
        dst_transform = tr
        crs_str = str(src_crs)

    return HeatSurface(
        array=np.stack(bands).astype(np.float32),
        transform=dst_transform,
        hours=selected_hours,
        crs=crs_str,
        name=f"UTCI_{year}_{doy:03d}",
    )


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
