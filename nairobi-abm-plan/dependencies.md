# Dependencies

Full `pyproject.toml` and version pins. Read this before touching `pyproject.toml` or installing packages.

---

## `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "nairobi-heat-abm"
version = "0.1.0"
description = "Agent-based model of pedestrian mobility and heat exposure in Nairobi"
requires-python = ">=3.11"
dependencies = [
    # Graph
    "networkx>=3.3",
    "osmnx>=1.9",

    # Raster / geospatial
    "rasterio>=1.3",
    "shapely>=2.0",
    "pyproj>=3.6",
    "geopandas>=0.14",

    # Numerics
    "numpy>=1.26",
    "scipy>=1.13",
    "pandas>=2.2",

    # UI
    "panel>=1.4",
    "param>=2.1",
    "hvplot>=0.10",
    "geoviews>=1.12",
    "plotly>=5.22",
    "bokeh>=3.4",

    # Config
    "pyyaml>=6.0",

    # Validation
    "jsonschema>=4.22",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-xdist>=3.5",   # parallel test execution
]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["slow: marks tests requiring network access or large data"]

[tool.hatch.build.targets.wheel]
packages = ["nairobi_heat_abm"]
```

---

## Key version notes

**osmnx >= 1.9**: The API changed significantly at 1.0. Do not use any pre-1.0 `ox.graph_from_point` or `ox.save_load` patterns from old tutorials — they no longer exist. Use `ox.graph_from_bbox`, `ox.save_graphml`, `ox.load_graphml`.

**panel >= 1.4**: Uses the new `pn.template.FastListTemplate`. The `pn.extension()` call must list all component types used (tabulator, plotly) or they will fail to render.

**rasterio >= 1.3**: Use `rasterio.transform.from_bounds` and `rasterio.warp.reproject`. Do not use deprecated `rasterio.crs.CRS.from_epsg` — use `CRS.from_epsg` from `pyproj` instead.

**numpy >= 1.26**: Use `np.random.default_rng(seed)` (Generator API) everywhere. Never use `np.random.seed()` global state — it breaks `ProcessPoolExecutor` reproducibility.

**networkx >= 3.3**: `nx.shortest_path` with `weight=` parameter is stable. `nx.MultiDiGraph` edge access is `G[u][v][key]`.

---

## What NOT to install

- **mesa**: The Mesa ABM framework. This project does not use it — agents are NumPy arrays, not Mesa Agents.
- **shapely < 2.0**: The pre-2.0 API is incompatible with geopandas >= 0.14.
- **fiona**: Not needed; osmnx and rasterio handle all I/O.
- **cartopy**: Too heavy; hvplot + geoviews covers all mapping needs.

---

## Data file dependencies (not pip packages)

These must be downloaded manually and placed in `data/raw/`:

| File | Source | Notes |
|---|---|---|
| `worldpop_nairobi.tif` | https://hub.worldpop.org | 100m resolution population grid, Kenya |
| `gtfs/` directory | DigitalMatatus or Nairobi City County | GTFS feed for matatu network |
| `heat/*.tif` | Provided by research team | Temperature raster(s) |

The OSM graph is downloaded automatically by `data/graph.py --build` and cached to `data/raw/graph.graphml`.

All files in `data/raw/` are gitignored. Add them to `.gitignore`:

```
data/raw/
*.graphml
*.tif
*.tiff
```
