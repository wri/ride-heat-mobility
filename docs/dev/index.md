# Developer documentation

Implementation notes for the Nairobi Heat Exposure ABM. Audience: engineers who want to understand, reproduce, or extend the codebase.

## Contents

| Document | What it covers |
|---|---|
| [Setup](setup.md) | Python environment, installation, data prerequisites |
| [Architecture](architecture.md) | Module map, data flow, key design constraints |
| [Data infrastructure](data-infrastructure.md) | Phase 1 — OSM graph, GTFS, WorldPop, heat rasters |
| [ABM core](abm-core.md) | Phase 2 — agent state, routing, time loop, simulation runner |
| [Panel app](panel-app.md) | Phase 3 — four-tab UI, shared state, live updates |
| [RDM batch analysis](rdm.md) | Phase 4 — LHS sampling, parallel runner, sensitivity analysis |
| [Testing](testing.md) | Fixture catalogue, phase gates, running the suite |

## How to navigate

Work through the documents in phase order (data → ABM → app → RDM). Each phase document corresponds to a completion gate: the phase is done when its pytest suite passes cleanly.

For a quick orientation to the repository layout, start with [Architecture](architecture.md).
