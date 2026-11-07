# Architecture

→ [Back to index](index.md)

## Repository layout

```
nairobi_heat_abm/
├── data/        # Static data loading (graph, population, heat, amenities)
├── model/       # Agent state, routing, time loop, simulation runner
├── rdm/         # LHS sampling, batch runner, outcome analysis, behavioural sensitivity
├── calibration.py  # fit behavioural parameters to the WRI rider survey
├── departure_fit.py  # refit the outbound departure profile for round trips
├── analysis/    # Exposure metrics and chart builders (post-run)
├── schemas/     # JSON Schema for TravelBehaviorParams
└── app/         # Panel web application (four tabs)
    ├── pages/   # One file per tab
    └── widgets/ # Reusable param-backed form widgets

data/raw/        # Gitignored — OSM cache, rasters, WorldPop, GTFS
tests/           # pytest suite, one file per phase
config.yaml      # Bbox, time range, paths, defaults, sensitivity settings
outputs/         # Gitignored — GeoPackages, sensitivity and calibration results
```

## Data flow

```
config.yaml
    │
    ▼
data/graph.py ──────────────────────────────┐
data/population.py                          │
data/amenities.py   ──► model/simulation.py ──► ScenarioResult ──► analysis/
data/heat.py ───────────────────────────────┘                    ──► app/pages/results.py

rdm/sampling.py ──► list[SimulationParams]
                         │
                         ▼
              rdm/batch.py (ProcessPoolExecutor)
                         │
                         ▼
              list[ScenarioResult] ──► rdm/analysis.py ──► RDMResultSet
                                                        ──► app/pages/rdm_explorer.py
```

## Key design constraints

**Agent state is columnar.** All agents are stored as parallel NumPy arrays in `AgentPool`. There are no per-agent Python objects. This is mandatory for the vectorised position and heat-accumulation updates in the hot loop. See [ABM core](abm-core.md).

**`simulation.run()` is a pure function.** It takes a `SimulationParams` and returns a `ScenarioResult` with no side effects and no global state. This is what makes `ProcessPoolExecutor`-based batch runs safe.

**`app/` never imports from itself into `model/` or `rdm/`.** Panel must not be imported in simulation worker processes or it will hang `ProcessPoolExecutor`. Enforce this by keeping the dependency graph strictly one-way: `app` → `rdm`/`model`/`data`, never the reverse.

**All raster CRS handling goes through `data/heat.py`.** Model code calls `sample_temperature()` only; it never calls rasterio directly.

**Shared inputs are loaded once per process.** `simulation.load_context()` holds the graph, `FastRouter`, amenities and rasters for any number of `run()` calls. Batch drivers (`rdm/run_sensitivity.py`, `calibration.py`) run sequentially in one process because of the graph's memory footprint (~3 GB).

**The graph is read-only after build.** `data/graph.py` builds and serialises the graph. At runtime the graph is loaded once and never mutated.

## Module responsibilities

<!-- TODO: expand each entry as implementation proceeds -->

| Module | Responsibility |
|---|---|
| `data/graph.py` | Build OSM walkable graph, integrate GTFS stops and edges, cache to GraphML |
| `data/population.py` | Load WorldPop raster, sample weighted spawn nodes |
| `data/amenities.py` | Fetch OSM POIs by category, snap to graph nodes |
| `data/heat.py` | Load multi-band heat raster, bilinear interpolation at agent positions |
| `model/agent.py` | `TravelBehaviorParams` dataclass, `AgentPool` columnar arrays, mode constants |
| `model/routing.py` | Walk and transit shortest-path routing, batch route assignment |
| `model/scheduler.py` | Vectorised single-timestep advance: movement, edge transitions, heat accumulation |
| `model/simulation.py` | `run()` entry point, population synthesis, time loop, `ScenarioResult` |
| `rdm/sampling.py` | Latin Hypercube Sampling over parameter ranges |
| `rdm/batch.py` | `ProcessPoolExecutor` batch runner with progress callbacks |
| `rdm/analysis.py` | Outcome metrics, `RDMResultSet`, Spearman sensitivity analysis |
| `app/state.py` | Module-level `AppState` singleton shared across pages |
| `app/main.py` | Panel entry point, four-tab template |

See the per-phase documents for full implementation details:
[Data infrastructure](data-infrastructure.md) · [ABM core](abm-core.md) · [Panel app](panel-app.md) · [RDM](rdm.md)
