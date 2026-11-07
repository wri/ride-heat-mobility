# RDM batch analysis (Phase 4)

→ [Back to index](index.md) | Phase gate: `pytest tests/test_phase4.py -x`

## Overview

Phase 4 builds the Latin Hypercube sampler, parallel batch runner, outcome analysis, and the RDM Explorer tab. Phases 2 and 3 must be complete first.

For the scientific rationale for the RDM approach see [methodology: RDM approach](../methodology/rdm-approach.md).

## 1. Parameter space — `rdm/sampling.py`

<!-- TODO: document ParameterRange dataclass, STANDARD_RANGES, why those bounds -->

### `ParameterRange`

### `STANDARD_RANGES`

### `generate_lhs_scenarios()`

## 2. Batch runner — `rdm/batch.py`

<!-- TODO: document ProcessPoolExecutor usage, ordering guarantee, exception-per-scenario, progress callback -->

### `run_batch()`

### Error handling — failed scenarios return Exception, not raise

### Progress callback threading contract

## 3. Outcome metrics — `rdm/analysis.py`

<!-- TODO: document compute_outcomes dict keys, RDMResultSet, build_result_set, sensitivity_analysis -->

### `compute_outcomes()`

### `RDMResultSet`

### `build_result_set()`

### `sensitivity_analysis()` — Spearman rank correlation

## 3b. Behavioural sensitivity analysis — `rdm/sensitivity.py`, `rdm/run_sensitivity.py`

Morris elementary-effects screening of **behavioural** parameters only (geography and transit service fixed); method and outcomes are in [RDM approach](../methodology/rdm-approach.md#behavioural-sensitivity-morris-elementary-effects).

- `BEHAVIOURAL_FACTORS`: name, label, range, baseline, source and an `apply(base, value)` that returns the `TravelBehaviorParams` fields to change. Composite factors: `departure_tilt_strength` raises every survey tilt to a power, and `work_share` sets the work purpose share while keeping the others' relative shares. 17 factors, including four that time the trip home (`work_end_hour_mean`, `school_end_hour_mean`, `market_dwell_median_min`, `other_dwell_median_min`).
- `morris_design(k, r)`, `elementary_effects()`, `morris_indices()` (μ, μ\* with bootstrap CI, σ); `scenario_outcomes(result, home_tags)`.
- `python -m nairobi_heat_abm.rdm.run_sensitivity` reads `config.yaml` → `sensitivity`. It loads heat, graph, router, rasters and SES layers once, runs baseline replicates and the Morris design sequentially, appends each finished run to `runs.csv`, then writes `morris_indices.csv` and `baseline_summary.csv`. The output directory is `outputs/sensitivity_roundtrip/` (round trips, 26 °C UTCI threshold); `outputs/sensitivity/` keeps the earlier one-way batch. Rerunning resumes; changing settings with the same output directory is refused. `--analyse-only` recomputes indices.
- `notebooks/02_behavioural_sensitivity.ipynb` plots the results.

Runs execute in one process rather than with `run_batch()`, because each worker would need its own ~3 GB graph.

## 3c. Calibration — `calibration.py`

`python -m nairobi_heat_abm.calibration` fits `destination_distance_decay` and `walk_time_weight` to the WRI rider survey's Q8 and Q11 over a parameter grid (resumable; outputs in `outputs/calibration/`). Method and result: [Travel behaviour](../methodology/travel-behaviour.md#calibration-of-β-and-the-walking-time-weight).

## 3d. Outbound departure profile for round trips — `departure_fit.py`

`python -m nairobi_heat_abm.departure_fit --off-peak 0.2` refits `peak1_hour`, `peak1_weight`, `peak2_hour` and `peak2_weight` so that outbound plus return departures reproduce the earlier all-journey departure distribution. It runs the model once (one-way, to get trip durations by purpose; cached in the output directory), then fits with a fast stand-in (`RoundTripSampler`) that draws departures as the model does and times trips home with `return_hours()`, a vectorised `return_departure_hour()`. Outputs in `outputs/departure_fit/` (`fit.json`, `hourly_shares.csv`). Method and result: [Travel behaviour](../methodology/travel-behaviour.md#departure-time-profile).

## 4. RDM Explorer tab

See [Panel app — RDM Explorer](panel-app.md) for the UI implementation.

## Phase gate checklist

- [ ] `pytest tests/test_phase4.py -x` passes
- [ ] Batch of 10 scenarios runs to completion via `ProcessPoolExecutor`
- [ ] Results are in the same order as input scenarios
- [ ] A failed scenario does not abort the batch
- [ ] Two batch runs with the same scenarios produce identical exposure arrays

See [Testing](testing.md) for fixture details.
