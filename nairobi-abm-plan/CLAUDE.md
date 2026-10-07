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

Phase 1 + Phase 2 are code-complete and validated against real data in the notebook: OSM walk network, WorldPop spawn density, OSM amenities, age/gender/SES demographics (spatially-derived from 5 WorldPop group rasters), and DigitalMatatus GTFS transit routing (frequency-based, not a literal timetable) are all confirmed working end-to-end — the real Nairobi graph carries 4,050 transit stops / 6,753 transit ride edges, and a full 5,000-agent run shows a genuine walk-vs-transit exposure split (66.8% walk / 33.2% transit). `pytest tests/ -m "not slow"` is green except the expected Phase 3 stub failure and 4 pre-existing `_integrate_gtfs` tests that call it without the `bbox` argument commit `5e76d36` made required (not yet fixed); `@pytest.mark.slow` (real-network) tests haven't been re-run recently.

Route choice (`model/routing.py::route_transit()`) is a single unified time-weighted `nx.shortest_path()` over the whole graph, not a three-phase nearest-stop-then-ride search — mode choice and route choice both emerge from real comparative time (walk time via each agent's own speed, transit time = ride + survey-calibrated expected wait `transit_mean_wait_min`, on routes in service during the agent's departure-time frequency band), with `walk_only_share` kept as an independent taste/preference gate on top. The actual boarding wait is stochastic (`Exponential(mean=headway)`, modeling matatus as irregular/Poisson-arrival paratransit — plan on the expectation, experience the randomness). Heat exposure and the time-density heatmap are outdoor-only: in-vehicle transit riding is excluded, only walking (incl. access-link legs to/from a stop) and waiting at a stop count. See `docs/dev/abm-core.md` for the full design, including a real vehicle-speed-vs-walking-speed bug found and fixed while building this (osmnx imputes vehicle speed for the "walk" network's `travel_time`, which made transit look permanently non-competitive until corrected).

Still blocked: real heat surface (waiting on Nairobi UTCI tiles in the WRI TCM S3 bucket — synthetic fallback used everywhere until then) and real informal-settlement boundary data (SES defaults to all-`SES_FORMAL` until then). Demographic/transit behavioural modifiers (`ParamModifier` on `DemographicParams`) are structurally wired but not yet populated with real values.

Phase 4 (RDM, `@docs/phase4-rdm.md`) is code-complete (`rdm/sampling.py`/`batch.py`/`analysis.py`) but has only ever been tested against synthetic `tiny_graph` scenarios, never against the real transit+demographics-enabled pipeline — see the project memory for exactly what's unverified before trusting a real sweep. Phase 3 (Panel UI) not started.
