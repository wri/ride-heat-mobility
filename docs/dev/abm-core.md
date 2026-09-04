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

<!-- TODO: document route_walk, assign_routes loop -->

Every route is a list of `(u, v, key, wait_ticks)` 4-tuples — `wait_ticks` is 0 except on a transit-boarding edge, where it's how many ticks the agent should wait at that stop before actually riding. Both `route_walk()` and `route_transit()` return this same shape, so `assign_routes()`/`tick()` don't need to special-case which produced a given route.

### Walk routing — `route_walk()`

### Transit routing — `route_transit()`

Three-phase: walk to the nearest transit stop, shortest-path across a transit-edges-only subgraph to the stop nearest the destination (free route transfers wherever two routes share a stop node), walk from there to the destination. Falls back to a full `route_walk()` if the graph has no transit stops/edges at all (e.g. `tiny_graph` in tests, or any graph built without `gtfs_path`).

Since the DigitalMatatus feed is frequency-based rather than a literal timetable (see `data/graph.py::_integrate_gtfs`), there's no departure clock time to check the agent's `departure_tick` against — instead, the headway band covering the agent's actual departure time (on the first ride edge's trip) gives an expected wait of `headway / 2`. If no band covers that time, or the wait exceeds `wait_tolerance_min`, `route_transit()` raises `nx.NetworkXNoPath`, exactly like a genuinely unreachable destination — `assign_routes()` doesn't distinguish the two, it just falls the agent back to walking (well, marks it inactive; see below) either way.

`stops_subgraph`/`transit_subgraph` (the transit-stop-only and transit-edge-only views used for the nearest-stop lookup and the ride leg) are computed once per `assign_routes()` call, not once per agent — they don't depend on any agent's origin/destination.

### Batch route assignment — `assign_routes()`

Note `assign_routes()` never sets `pool.active = True` on success — only `= False` on failure. Activation happens later, in `simulation.py::run()`'s tick loop, once the simulation clock reaches the agent's own `departure_tick`. A newly-routed agent's first edge is set up via the same `_activate_edge()` helper `tick()` uses for every later edge transition (below), so the two never drift apart.

## 4. Time loop — `model/scheduler.py`

<!-- TODO: document tick() step by step: movement vectorisation, edge transitions, heat sampling -->

### Transit-boarding wait

Before the position update, agents with `mode == MODE_WAIT` have `wait_ticks_remaining` decremented; once it hits 0, mode flips to the current edge's real mode (walk or transit) in the same `tick()` call, so movement can begin that same tick rather than wasting one. A waiting agent's position is frozen at `edge_u` throughout (excluded from the progress update below) — heat still accumulates each tick at that fixed point, since standing at an exposed stage is itself a real exposure scenario.

### Vectorised progress update

Progress advances using `pool.edge_speed_mps`, not `pool.speed_mps` directly: `_activate_edge()` (`model/routing.py`) sets it to the agent's personal walk speed for a walk/access-link edge (unchanged from pre-transit behaviour), but to the transit edge's own `length / travel_time` while riding — a matatu segment moves at its own implied road speed, not the rider's walking pace.

### Edge transition (Python loop over finishing agents)

Delegates to the same `_activate_edge()` helper `assign_routes()` uses for an agent's first edge (see §3 above) — position, edge length, mode, and `edge_speed_mps` are all set in that one place.

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
