# Phase 1 — Data infrastructure

Build and cache all static data assets the model needs before any agents run. No simulation code in this phase.

**Completion gate:** `pytest tests/test_phase1.py -x` passes with a real Nairobi bbox.

---

## 1.1 Project scaffold

Create the package skeleton and `pyproject.toml` before writing any logic.

```
nairobi_heat_abm/
├── __init__.py
├── app/
│   ├── __init__.py
│   ├── main.py
│   └── pages/
│       └── __init__.py
├── data/
│   ├── __init__.py
│   ├── graph.py
│   ├── population.py
│   ├── amenities.py
│   └── heat.py
├── model/
│   ├── __init__.py
│   ├── agent.py
│   ├── routing.py
│   ├── scheduler.py
│   └── simulation.py
├── rdm/
│   ├── __init__.py
│   ├── sampling.py
│   ├── batch.py
│   └── analysis.py
├── analysis/
│   ├── __init__.py
│   ├── exposure.py
│   └── viz.py
├── schemas/
│   └── travel_behavior.json
├── tests/
│   ├── conftest.py
│   ├── test_phase1.py
│   ├── test_phase2.py
│   ├── test_phase3.py
│   └── test_phase4.py
├── data/
│   └── raw/          # gitignored — OSM cache, rasters, WorldPop
├── config.yaml
└── pyproject.toml
```

See `@docs/dependencies.md` for the full `pyproject.toml`.

---

## 1.2 `data/graph.py` — OSM + GTFS graph

### Build function signature

```python
def build_graph(
    bbox: tuple[float, float, float, float],  # (south, west, north, east)
    gtfs_path: str | Path | None = None,
    cache_path: str | Path = "data/raw/graph.graphml",
    force_rebuild: bool = False,
) -> nx.MultiDiGraph:
```

### OSM walkable network

```python
import osmnx as ox

G = ox.graph_from_bbox(
    north=bbox[2], south=bbox[0], east=bbox[3], west=bbox[1],
    network_type="walk",
    retain_all=False,
    clean_periphery=True,
)
G = ox.add_edge_speeds(G)
G = ox.add_edge_travel_times(G)
G = ox.project_graph(G, to_crs="EPSG:4326")
```

Every edge must have: `length` (m), `travel_time` (s), `geometry` (LineString).

### Node attributes to store

```python
# After building, tag node types
nx.set_node_attributes(G, "intersection", name="node_type")
```

Node types used later: `"intersection"`, `"transit_stop"`, `"amenity"`.

### GTFS integration

If `gtfs_path` is provided:

1. Parse `stops.txt` → insert each stop as a node with `node_type="transit_stop"` and attributes: `stop_id`, `stop_name`, `lat`, `lon`.
2. For each stop, find the nearest walkable node via `ox.nearest_nodes`. Add a bidirectional **access edge** with:
   - `edge_type = "access_link"`
   - `length` = Haversine distance (m)
   - `travel_time` = length / 1.2 (walk speed)
   - `weight` = travel_time (used by routing)
3. Parse `stop_times.txt` and `trips.txt`. For each consecutive stop-pair on a route, add a directed **boarding edge**:
   - `edge_type = "transit"`
   - `route_id`, `trip_id`
   - `departure_time` (seconds since midnight)
   - `travel_time` = arrival_time − departure_time
   - `weight` = travel_time
4. If `stop_times.txt` is large (>1M rows), use chunked pandas reads.

### Serialisation

```python
ox.save_graphml(G, filepath=cache_path)
# load with:
G = ox.load_graphml(cache_path)
```

Always check cache first; only rebuild if `force_rebuild=True` or cache absent.

---

## 1.3 `data/amenities.py` — OSM points of interest

### Build function signature

```python
def build_amenity_index(
    bbox: tuple[float, float, float, float],
    G: nx.MultiDiGraph,
    cache_path: str | Path = "data/raw/amenities.json",
    force_rebuild: bool = False,
) -> dict[str, list[int]]:
    """
    Returns: { "school": [node_id, ...], "shop": [...], "health": [...], "other": [...] }
    """
```

### OSM tags to query

```python
AMENITY_TAGS = {
    "school":   {"amenity": ["school", "university", "college"]},
    "shop":     {"shop": True, "amenity": ["marketplace", "supermarket"]},
    "health":   {"amenity": ["hospital", "clinic", "pharmacy", "doctors"]},
    "other":    {"amenity": ["place_of_worship", "community_centre", "library"]},
}
```

Use `ox.features_from_bbox()` for each tag group.

For each POI, snap to nearest walkable node via `ox.nearest_nodes` and add `node_type="amenity"` and `amenity_type=<category>` to that node.

Return a dict mapping category → list of graph node IDs. Serialise as JSON.

---

## 1.4 `data/population.py` — WorldPop spawn sampling

### Load function

```python
def load_population_raster(
    tif_path: str | Path,
    bbox: tuple[float, float, float, float],
) -> tuple[np.ndarray, rasterio.Affine]:
    """
    Returns (density_array, transform).
    density_array shape: (rows, cols), values: people per pixel.
    Clips to bbox. Reprojects to EPSG:4326 if needed.
    """
```

### Spawn sampler

```python
def sample_spawn_nodes(
    density_array: np.ndarray,
    transform: rasterio.Affine,
    G: nx.MultiDiGraph,
    n_agents: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Returns array of shape (n_agents,) with graph node IDs.
    Weighted sample of grid cells by population density,
    then snap each sampled cell centre to nearest graph node.
    Zero-density cells are excluded.
    """
```

Steps:
1. Flatten `density_array` and normalise to a probability vector (exclude zeros and NaNs).
2. `rng.choice(len(flat_density), size=n_agents, p=probs)` — vectorised, no Python loop.
3. Convert flat indices → (row, col) → (lon, lat) via `rasterio.transform.xy`.
4. Batch-snap to graph: `ox.nearest_nodes(G, X=lons, Y=lats)` — returns array of node IDs.

---

## 1.5 `data/heat.py` — raster heat surface

### Load function

```python
def load_heat_surface(
    tif_path: str | Path,
    target_hours: list[int] | None = None,
) -> HeatSurface:
```

### `HeatSurface` dataclass

```python
@dataclass
class HeatSurface:
    array: np.ndarray          # shape (n_hours, rows, cols), float32, °C
    transform: rasterio.Affine # maps pixel → lon/lat (EPSG:4326)
    hours: list[int]           # hour-of-day index per band, e.g. [6, 9, 12, 15, 18]
    crs: str                   # source CRS string
    name: str                  # filename stem, used for display + RDM labelling
```

### Loading logic

- Accept multi-band GeoTIFF (one band per hour) or a directory of single-band files.
- Reproject to EPSG:4326 if needed using `rasterio.warp.reproject`.
- If `target_hours` is given, select only those bands.
- Cast to `float32` to keep memory low.
- Replace nodata values with `np.nan`.

### Interpolation function

```python
def sample_temperature(
    surface: HeatSurface,
    lons: np.ndarray,   # shape (N,)
    lats: np.ndarray,   # shape (N,)
    hour: int,          # 0–23
) -> np.ndarray:        # shape (N,) °C
```

Steps:
1. Find the nearest available hour index in `surface.hours`.
2. Convert (lon, lat) → fractional pixel (col, row) using `~surface.transform`.
3. Use `scipy.ndimage.map_coordinates` with `order=1` (bilinear) and `mode='nearest'`.
4. Return temperatures as float32 array. NaN where pixel is outside raster extent.

---

## 1.6 `config.yaml`

```yaml
bbox:
  south: -1.444
  west: 36.649
  north: -1.163
  east: 37.104

simulation:
  start_hour: 6
  end_hour: 20
  timestep_seconds: 60
  default_n_agents: 5000
  default_seed: 42

walk_speed_default_mps: 1.2

paths:
  graph_cache: data/raw/graph.graphml
  amenity_cache: data/raw/amenities.json
  worldpop_tif: data/raw/worldpop_nairobi.tif
  gtfs_dir: data/raw/gtfs/
  heat_dir: data/raw/heat/

app:
  port: 5006
  title: "Nairobi Heat Exposure ABM"
```

---

## 1.7 Tests for Phase 1

File: `tests/test_phase1.py`

```python
# conftest.py provides: small_bbox (a ~2km² patch of Nairobi), tiny_graph (10-node mock)

def test_graph_builds_and_has_required_edge_attributes(small_bbox):
    G = build_graph(small_bbox, force_rebuild=True)
    for u, v, data in G.edges(data=True):
        assert "length" in data
        assert "travel_time" in data

def test_graph_caches_and_reloads(small_bbox, tmp_path):
    cache = tmp_path / "graph.graphml"
    G1 = build_graph(small_bbox, cache_path=cache)
    G2 = build_graph(small_bbox, cache_path=cache)
    assert G1.number_of_nodes() == G2.number_of_nodes()

def test_amenity_index_returns_expected_categories(small_bbox, tiny_graph):
    index = build_amenity_index(small_bbox, tiny_graph, force_rebuild=True)
    assert set(index.keys()) == {"school", "shop", "health", "other"}

def test_spawn_sampling_returns_valid_node_ids(tiny_graph):
    density = np.ones((10, 10))
    transform = rasterio.transform.from_bounds(36.8, -1.3, 36.9, -1.2, 10, 10)
    rng = np.random.default_rng(42)
    nodes = sample_spawn_nodes(density, transform, tiny_graph, n_agents=50, rng=rng)
    assert len(nodes) == 50
    assert all(n in tiny_graph.nodes for n in nodes)

def test_heat_surface_loads_and_interpolates(sample_tif):
    surface = load_heat_surface(sample_tif)
    lons = np.array([36.82, 36.85])
    lats = np.array([-1.28, -1.30])
    temps = sample_temperature(surface, lons, lats, hour=12)
    assert temps.shape == (2,)
    assert np.all(np.isfinite(temps))
```
