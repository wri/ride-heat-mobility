# Nairobi Heat Exposure ABM

Agent-based model of pedestrian and transit-user mobility in Nairobi, with heat exposure tracking. Pure Python, Panel web UI, RDM batch analysis.

## Project goal

Simulate how long people are exposed to heat as they travel through the city, under varying travel-behaviour assumptions and heat surface scenarios. Supports interactive single runs and batch RDM sweeps of hundreds of scenarios.

## Quick orientation

```
nairobi_heat_abm/
├── app/          # Panel web application (4 tabs)
├── data/         # Graph, population, amenities, heat loading
├── model/        # Agent state, routing, time loop, simulation runner
├── rdm/          # Latin Hypercube sampling, batch runner, analysis
├── analysis/     # Exposure metrics, chart builders
├── schemas/      # JSON Schema for travel_behavior.json
└── config.yaml   # Bbox, time range, defaults
```

## Commands

```bash
pip install -e ".[dev]"          # install project + dev deps
python -m nairobi_heat_abm.app   # launch Panel app (localhost:5006)
pytest tests/ -x                 # run test suite
python -m nairobi_heat_abm.data.graph --build   # download + cache OSM graph
```

## Hard rules — check before every action

1. Never commit data files (OSM cache, rasters, WorldPop grids) — they live in `data/raw/` which is gitignored.
2. Agent state arrays are NumPy columnar — never use per-agent Python objects in the hot loop.
3. The NetworkX graph is read-only after `graph.py` builds it — no mutation at runtime.
4. All raster CRS handling goes through `data/heat.py` — never call `rasterio` directly from model code.
5. `simulation.py:run()` must be pure (no global state) so `ProcessPoolExecutor` workers can call it safely.

## Non-obvious conventions

- Travel behaviour parameters always flow as a `TravelBehaviorParams` dataclass — never as raw dicts.
- Heat interpolation is always bilinear — no nearest-neighbour shortcuts.
- Timestep is 60 seconds throughout; do not make it configurable without updating the routing engine.
- All agent metrics accumulate in `°C·min` (Celsius × minutes of exposure).

## Reference documents — load when relevant

| Task | Read first |
|---|---|
| Anything touching the graph or routing | @docs/phase1-data-infrastructure.md |
| Agent movement or the time loop | @docs/phase2-abm-core.md |
| Panel UI, widgets, JSON schema | @docs/phase3-panel-app.md |
| Batch runs, LHS sampling, RDM Explorer | @docs/phase4-rdm.md |
| Adding tests or debugging a phase | @docs/testing-strategy.md |
| Dependency versions or pyproject.toml | @docs/dependencies.md |

## Prototyping workflow

Before wiring up the Phase 3 Panel UI, the Phase 1 + Phase 2 pipeline is validated end-to-end in a notebook: `notebooks/01_nairobi_heat_abm.ipynb`. The notebook imports directly from `nairobi_heat_abm/` (no reimplementation) and walks through graph → population → heat → amenities → simulation → results, with synthetic fallbacks for any real data file (WorldPop TIF, heat rasters) that isn't present yet in `data/raw/`.

**Why:** de-risk the data pipeline and simulation core against real Nairobi data before investing in UI plumbing. Bugs found this way (e.g. a CRS-handling bug in `population.py` that only surfaced with real, non-4326 WorldPop data) are fixed in the library code itself, not the notebook — the notebook is a harness, not where logic lives.

Only move to Phase 3 (`@docs/phase3-panel-app.md`) once the notebook runs cleanly end-to-end on real data and the `pytest tests/test_phase1.py` / `test_phase2.py` gates pass.

## Current status

Phase 1 + Phase 2 code is written. Currently prototyping in the notebook against real data: OSM graph and WorldPop population loading are confirmed working end-to-end; the heat surface is blocked on real Nairobi UTCI tiles landing in the WRI TCM S3 bucket (format: tiled UTM GeoTIFFs, one mosaic-and-reproject pass needed per hour — see `data/heat.py:load_utci_tiles()`). Test suites (`tests/test_phase1.py` onward) have not been run yet. Phase 3 (Panel UI) not started.
