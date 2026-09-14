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

Shortest path weighted by `_real_walk_cost()` — this agent's own `length / walk_speed_mps` for every edge, never the edge's stored `travel_time` (see the vehicle-speed bug below). Excludes `edge_type == "transit"` edges entirely (`_non_transit_weight()`), so a "walk-only" trip (or a wait-tolerance-exceeded fallback from `route_transit()`) can never silently ride a matatu for free — access-link edges (walking to/from a stop) are still fair game, since those are genuinely walked, not ridden.

### Transit routing — `route_transit()`

A single unified `nx.shortest_path()` over the WHOLE graph (walk + access-link + transit edges together), not a three-phase nearest-stop-then-ride search — so mode choice (walk vs. transit) and route choice (which matatu route, if any) both emerge from real comparative time instead of being decided separately. `_band_edge_weight()` gives each transit edge a planning weight of `travel_time + expected_wait_for_this_band` (mean = headway); every other edge uses `_real_walk_cost()`. Dijkstra then picks whichever combination minimizes total weight, including choosing to walk the whole way when that's genuinely cheaper — there's no separate nearest-stop snapping step, since the graph's own access-link edges already let the search reach and leave stops as part of one path.

**`_real_walk_cost()` exists because of a real, consequential bug found while building this**: osmnx's `add_edge_speeds()`/`add_edge_travel_times()` (`data/graph.py::build_graph()`) impute *vehicle* speed for ordinary street edges from OSM `maxspeed`/highway-type, even though the network is fetched as `network_type="walk"` (osmnx has no pedestrian-speed mode) — so an edge's own `travel_time` can be wildly faster than real walking pace (observed on the real Nairobi graph: a 30km stretch showing ~33 minutes, i.e. ~54 km/h). The very first version of this unified search compared that vehicle-paced "walk" cost directly against a real transit wait cost and found walking free every time — 0/3858 simulated trips ever chose transit, down from ~33% under the old three-phase design. `_real_walk_cost()` recomputes `length / walk_speed_mps` (this agent's own real speed, threaded in from `pool.speed_mps[i]` via `assign_routes()`) for anything that isn't a transit ride; only a transit edge's own `travel_time` (real GTFS ride time) is trusted as-is. After the fix, transit wins for ~73% of a 300-trip real sample (932m–30km), walking wins for short local hops (median ~1,036m) — i.e. transit becomes worthwhile once wait + access overhead is outweighed by distance saved, which is the qualitatively expected shape.

`_distinct_bands()` derives the set of real frequency-band boundaries directly from the data (currently 6-9/9-15/15-21, matching the DigitalMatatus feed) rather than hardcoding them, and `assign_routes()` computes this once per call, not once per agent. The agent's actual departure time picks which band's weights to search with — a rider departing at 7am and one departing at noon can get genuinely different routes for the same OD pair, because the same physical edge looks cheap or expensive depending on time-of-day service frequency.

Once a path is chosen, if it boards a matatu at all, the ACTUAL wait for that first boarding is drawn from `Exponential(mean=headway)` at the agent's exact departure time (not the band-representative estimate used for planning) — plan on the expectation, experience the randomness. If that drawn wait exceeds `wait_tolerance_min`, or the boarding edge has no coverage at the agent's exact time, or the agent's departure time falls outside every band, or the graph has no transit edges at all (e.g. `tiny_graph` in tests, or any graph built without `gtfs_path`) — `route_transit()` falls back to a plain `route_walk()` instead of failing the trip outright. Only the first boarding's wait is charged; transfers to another route at a shared stop are free (a deliberate simplification, not an oversight).

### Batch route assignment — `assign_routes()`

Note `assign_routes()` never sets `pool.active = True` on success — only `= False` on failure. Activation happens later, in `simulation.py::run()`'s tick loop, once the simulation clock reaches the agent's own `departure_tick`. A newly-routed agent's first edge is set up via the same `_activate_edge()` helper `tick()` uses for every later edge transition (below), so the two never drift apart.

On a routing failure, `assign_routes()` also sets `departure_ticks[i] = -1` (the same "never travels" sentinel `simulation.py` uses for a failed travel-probability gate). Without this, `run()`'s tick loop would still flip the agent active at its original (still-valid) departure tick despite having an empty `route_edges`, closing it out as a bogus zero-length, zero-exposure "completed" trip that very tick — polluting `trip_log`/`agent_modes` with phantom entries for a trip that was never actually assigned.

`_distinct_bands(G)` and each agent's own `pool.speed_mps[i]` are computed/read once per `assign_routes()` call (the bands) or per agent (the walk speed) and threaded into `route_walk()`/`route_transit()` — neither depends on more than that.

## 4. Time loop — `model/scheduler.py`

<!-- TODO: document tick() step by step: movement vectorisation, edge transitions, heat sampling -->

`tick()`'s heat/time-density accumulation is **outdoor exposure only**: agents whose current mode is `MODE_TRANSIT` (actually riding, not waiting) are excluded from both `heat_exposure_degC_min` and `time_density` — a matatu passenger isn't exposed to ambient heat the way a walking or waiting pedestrian is. Walking (including access-link legs to/from a stop) and `MODE_WAIT` (standing at a stop before boarding) both still count; only the in-vehicle segment is skipped.

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
