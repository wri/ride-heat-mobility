# Data infrastructure (Phase 1)

→ [Back to index](index.md) | Phase gate: `pytest tests/test_phase1.py -x`

## Overview

Phase 1 builds and caches all static data assets the model needs before any agents run. No simulation logic is written in this phase.

## 1. OSM walking graph — `data/graph.py`

<!-- TODO: document the osmnx call chain, edge attribute requirements, CRS handling -->

### Build process

### GTFS integration

`_integrate_gtfs(G, gtfs_path)` (called from `build_graph()` when `gtfs_path` is given) mutates the walk graph in-place, reading a DigitalMatatus-style feed from either a directory of `.txt` files or a `.zip` at its root. It adds one `transit_stop` node per `stop_id`, bidirectional `access_link` edges to the nearest walk node, and one `transit` edge per consecutive stop-pair actually ridden by a trip that has `frequencies.txt` coverage — see [Transport network](../methodology/transport-network.md#matatu-network-gtfs) for why frequency bands (not `stop_times.txt` clock times) are the thing that actually drives routing here, and `model/routing.py::route_transit()` for how those bands turn into an expected wait.

Each transit edge's `frequencies` attribute is a plain Python list of `[start_s, end_s, headway_secs]` triples — stored as a native list (not JSON), since osmnx's `save_graphml`/`load_graphml` already round-trips any string-valued attribute that looks like a Python list/dict via `ast.literal_eval`.

### Serialisation and caching

### Known issues and edge cases

## 2. Amenity index — `data/amenities.py`

<!-- TODO: document AMENITY_TAGS categories, snapping logic, JSON cache format -->

## 3. Population raster — `data/population.py`

<!-- TODO: document WorldPop loading, bbox clipping, reprojection, weighted sampling -->

### Loading and clipping

### Spawn node sampling

## 4. Heat surface — `data/heat.py`

<!-- TODO: document multi-band GeoTIFF format, HeatSurface dataclass, bilinear interpolation -->

### `HeatSurface` dataclass

### Loading multi-band rasters

### `sample_temperature()` — bilinear interpolation

## 5. Configuration — `config.yaml`

<!-- TODO: annotate each field and explain how it flows into build calls -->

## Phase gate checklist

- [ ] `python -m nairobi_heat_abm.data.graph --build` completes on the Nairobi bbox
- [ ] `pytest tests/test_phase1.py -x` passes
- [ ] Graph has `length` and `travel_time` on every edge
- [ ] Amenity index has all four categories
- [ ] Heat interpolation returns finite values inside the bbox

See [Testing](testing.md) for fixture details.
