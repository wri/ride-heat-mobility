# Setup

→ [Back to index](index.md)

## Prerequisites

- Python 3.10 or 3.11
- Git
- ~4 GB disk space for raw data files (not tracked in git)

## Installation

```bash
git clone <repo-url>
cd ride
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -e ".[dev]"
```

## Raw data files

Place the following in `data/raw/` before running the model. These files are gitignored and must be obtained separately.

| File | Source | Notes |
|---|---|---|
| `worldpop_nairobi.tif` | WorldPop Hub | 100 m resolution population grid, Kenya |
| `gtfs/` | DigitalMatatus or Nairobi City County | GTFS feed for matatu network |
| `heat/*.tif` | Research team | Temperature raster(s), one band per hour |

The OSM graph is downloaded automatically:

```bash
python -m nairobi_heat_abm.data.graph --build
```

This writes `data/raw/graph.graphml` and does not need to be re-run unless the bbox in `config.yaml` changes.

## Verifying the installation

```bash
pytest tests/ -x -m "not slow"
```

The `slow` mark requires a network connection and the raw data files above. All other tests use synthetic fixtures and should pass on a clean install once dependencies are installed.

## Configuration

All top-level settings live in [`config.yaml`](../../config.yaml). The most commonly adjusted values are the bounding box and the simulation time window.

## Key version notes

<!-- TODO: expand with any version-specific gotchas discovered during implementation -->

See [architecture](architecture.md) for how the modules relate to each other.
