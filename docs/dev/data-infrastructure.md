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

`build_amenity_index(bbox, G, cache_path, force_rebuild)` fetches OSM points of interest for five categories and snaps each to its nearest walk-graph node, tagging that node's `amenity_type` for later use (`model/simulation.py::_draw_destinations`).

**Categories** (`AMENITY_TAGS: dict[str, list[dict]]`): each category maps to a *list* of separate `osmnx.features_from_bbox()` tag queries, fetched and merged/deduped independently rather than as one combined query per category:

- `school` — `amenity` in `{school, university, college}`
- `food` — `shop=supermarket` and `amenity=marketplace` only — deliberately narrow: not `shop=convenience` (too granular/ubiquitous to be a meaningful trip destination) and not restaurants/cafes (`amenity=restaurant|fast_food|cafe` is food *service*, not food *shopping*)
- `health` — `amenity` in `{hospital, clinic, pharmacy, doctors}`
- `other` — `amenity` in `{place_of_worship, community_centre, library}`
- `work` — office/craft/landuse/building/amenity(townhall|courthouse|bank) tags, plus `shop=True` — every shop is a workplace, not just the food-shop subset that `food` surfaces as a destination category

**Why per-query, not per-category, fetching**: a single combined multi-key query (e.g. the old catch-all `shop=True` merged into the same request as several `amenity` values) can be large/expensive enough that the Overpass API times out on it — and a bare `except Exception: pass` around one combined query silently empties the *whole* category on any failure. Splitting into separate per-tag queries, each independently caught, means one query failing only drops that query's contribution, not its neighbors.

**Work overlap** (`_add_work_overlap`, `_WORK_OVERLAP_CATEGORIES = ("school", "food", "health")`): schools, food shops, and health facilities also employ workers, so their nodes are merged into `"work"` too (deduplicated) after all categories are fetched. `work`'s own `shop=True` query already covers non-food shops; the `food`→`work` merge mainly contributes `amenity=marketplace` nodes, which `shop=True` doesn't catch.

**Snapping and caching**: each matched feature's centroid is snapped to the nearest walk-graph node via `ox.nearest_nodes()`; that node gets `node_type="amenity"` and `amenity_type=<category>` (first category to claim a node wins, via `setdefault`). The full `{category: [node_id, ...]}` result is cached as JSON to `cache_path` (default `data/raw/amenities.json`); `force_rebuild=False` with an existing cache file short-circuits straight to `load_amenity_index()`, skipping OSM entirely.

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
- [ ] Amenity index has all five categories (`school`, `food`, `health`, `other`, `work`)
- [ ] Heat interpolation returns finite values inside the bbox

See [Testing](testing.md) for fixture details.
