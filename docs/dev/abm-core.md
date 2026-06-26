# ABM core (Phase 2)

→ [Back to index](index.md) | Phase gate: `pytest tests/test_phase2.py -x`

## Overview

Phase 2 implements the agent state representation, routing engine, time loop, and simulation runner. No UI code is written in this phase.

## 1. `TravelBehaviorParams` — `model/agent.py`

<!-- TODO: document each field, units, validation in __post_init__, JSON roundtrip -->

### Fields and defaults

### `params_to_json` / `params_from_json`

### JSON Schema validation

## 2. Agent state — `AgentPool` — `model/agent.py`

<!-- TODO: explain columnar design decision, each array and its dtype, AgentPool.create() -->

### Columnar array layout

### Mode constants (`MODE_WALK`, `MODE_WAIT`, `MODE_TRANSIT`)

### `AgentPool.create(n)`

## 3. Routing — `model/routing.py`

<!-- TODO: document route_walk, route_transit two-phase approach, assign_routes loop -->

### Walk routing — `route_walk()`

### Transit routing — `route_transit()`

### Batch route assignment — `assign_routes()`

## 4. Time loop — `model/scheduler.py`

<!-- TODO: document tick() step by step: movement vectorisation, edge transitions, heat sampling -->

### Vectorised progress update

### Edge transition (Python loop over finishing agents)

### Heat accumulation

### Performance notes

## 5. Simulation runner — `model/simulation.py`

<!-- TODO: document SimulationParams, ScenarioResult, run() structure, population synthesis helpers -->

### `SimulationParams`

### `ScenarioResult`

### `run()` — population synthesis

### `run()` — time loop and trip logging

### Determinism guarantee

## Phase gate checklist

- [ ] `pytest tests/test_phase2.py -x` passes
- [ ] `TravelBehaviorParams` JSON roundtrip is lossless
- [ ] `tick()` advances progress correctly at known edge lengths and speeds
- [ ] Heat accumulates at exactly `temperature × timestep_minutes` per tick
- [ ] Two runs with the same seed produce identical `agent_exposure_degC_min`

See [Testing](testing.md) for fixture details.
