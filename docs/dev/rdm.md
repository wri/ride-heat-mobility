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

## 4. RDM Explorer tab

See [Panel app — RDM Explorer](panel-app.md) for the UI implementation.

## Phase gate checklist

- [ ] `pytest tests/test_phase4.py -x` passes
- [ ] Batch of 10 scenarios runs to completion via `ProcessPoolExecutor`
- [ ] Results are in the same order as input scenarios
- [ ] A failed scenario does not abort the batch
- [ ] Two batch runs with the same scenarios produce identical exposure arrays

See [Testing](testing.md) for fixture details.
