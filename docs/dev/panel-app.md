# Panel app (Phase 3)

→ [Back to index](index.md) | Phase gate: `pytest tests/test_phase3.py -x`

## Overview

Phase 3 builds the four-tab Panel web application. The ABM core (Phase 2) must be complete before starting this phase.

Launch with: `python -m nairobi_heat_abm.app`

## 1. Shared state — `app/state.py`

<!-- TODO: document AppState param fields, the module-level singleton, how pages subscribe -->

## 2. Entry point — `app/main.py`

<!-- TODO: document pn.extension() call, tab assembly, FastListTemplate -->

## 3. Setup tab — `app/pages/setup.py`

<!-- TODO: document heat raster upload, BehaviorForm, population parameters, graph status panel -->

### Heat surface upload

### Travel behaviour section

#### Widgets mode — `app/widgets/behavior_form.py`

#### JSON mode

#### RDM mode (read-only notice)

### Population parameters

### Graph status panel

## 4. Run tab — `app/pages/run.py`

<!-- TODO: document single-run mode, background thread pattern, live map, live histogram, stats row -->

### Single-run mode

### Background thread and `pn.state.execute`

### Live agent map

### Live exposure histogram

### Live stats row

## 5. Results tab — `app/pages/results.py`

<!-- TODO: document summary metrics row, exposure-by-mode chart, spatial heatmap, CSV export -->

### Summary metrics

### Exposure by mode (violin/box)

### Spatial heatmap

### CSV export

## 6. RDM Explorer tab — `app/pages/rdm_explorer.py`

<!-- TODO: cross-reference rdm.md; document parameter ranges form, outcome table, parallel coords, sensitivity chart -->

See [RDM](rdm.md) for the underlying analysis; this document covers only the UI layer.

## 7. JSON Schema — `schemas/travel_behavior.json`

<!-- TODO: explain schema structure, how it diverges from the flat dataclass, validation call site -->

## Phase gate checklist

- [ ] `pytest tests/test_phase3.py -x` passes
- [ ] `python -m nairobi_heat_abm.app` launches without error
- [ ] All four tabs render with mock data
- [ ] JSON export/import roundtrip preserves all parameter values exactly

See [Testing](testing.md) for fixture details.
