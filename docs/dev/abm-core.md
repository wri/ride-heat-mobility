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

A single unified shortest path over the WHOLE graph (walk + access-link + transit edges together), not a three-phase nearest-stop-then-ride search — so mode choice (walk vs. transit) and route choice (which matatu route, if any) both emerge from real comparative time instead of being decided separately. `_band_edge_weight()` gives each transit edge that is in service during the agent's frequency band a planning weight of `travel_time + transit_mean_wait_min` (edges with no service in that band are excluded); every other edge uses `walk_time_weight × _real_walk_cost()`. `walk_time_weight` (`TravelBehaviorParams`) is how much a minute of walking counts against a minute riding when choosing the route; it changes the choice only, and the walk itself still takes `length / speed`. At 1.0, simulated riders walked past nearby stops to reach more direct routes (median access walk 21 min vs. ~7 min in the rider survey). The default is calibrated to the survey; see [Travel behaviour](../methodology/travel-behaviour.md#walking-time-weight-in-route-choice). Dijkstra then picks whichever combination minimizes total weight, including choosing to walk the whole way when that's genuinely cheaper — there's no separate nearest-stop snapping step, since the graph's own access-link edges already let the search reach and leave stops as part of one path.

**`_real_walk_cost()` exists because of a real, consequential bug found while building this**: osmnx's `add_edge_speeds()`/`add_edge_travel_times()` (`data/graph.py::build_graph()`) impute *vehicle* speed for ordinary street edges from OSM `maxspeed`/highway-type, even though the network is fetched as `network_type="walk"` (osmnx has no pedestrian-speed mode) — so an edge's own `travel_time` can be wildly faster than real walking pace (observed on the real Nairobi graph: a 30km stretch showing ~33 minutes, i.e. ~54 km/h). The very first version of this unified search compared that vehicle-paced "walk" cost directly against a real transit wait cost and found walking free every time — 0/3858 simulated trips ever chose transit, down from ~33% under the old three-phase design. `_real_walk_cost()` recomputes `length / walk_speed_mps` (this agent's own real speed, threaded in from `pool.speed_mps[i]` via `assign_routes()`) for anything that isn't a transit ride; only a transit edge's own `travel_time` (real GTFS ride time) is trusted as-is. After the fix, transit wins for ~73% of a 300-trip real sample (932m–30km), walking wins for short local hops (median ~1,036m) — i.e. transit becomes worthwhile once wait + access overhead is outweighed by distance saved, which is the qualitatively expected shape.

`_distinct_bands()` derives the set of real frequency-band boundaries directly from the data (currently 6-9/9-15/15-21, matching the DigitalMatatus feed) rather than hardcoding them, and `assign_routes()` computes this once per call, not once per agent. The agent's actual departure time picks which band's weights to search with — a rider departing at 7am and one departing at noon can get different routes for the same OD pair only where a route runs in one band but not the other. The headway itself no longer affects the cost: the feed's headways are a uniform placeholder schedule, so the expected wait is the survey-calibrated `transit_mean_wait_min` in every band (see [Travel behaviour](../methodology/travel-behaviour.md#transit-wait-time-and-wait-tolerance)).

Once a path is chosen, if it boards a matatu at all, the ACTUAL wait for that first boarding is `Exponential(mean=transit_mean_wait_min)`, drawn up front for every agent in `assign_routes()` as a standard exponential and scaled by the mean — plan on the expectation, experience the randomness. If that drawn wait exceeds `wait_tolerance_min`, or the boarding edge has no coverage at the agent's exact time, or the agent's departure time falls outside every band, or the graph has no transit edges at all (e.g. `tiny_graph` in tests, or any graph built without `gtfs_path`) — `route_transit()` falls back to a plain `route_walk()` instead of failing the trip outright. Only the first boarding's wait is charged; transfers to another route at a shared stop are free (a deliberate simplification, not an oversight).

### Fast route search — `FastRouter`

`route_walk()` / `route_transit()` above are the reference implementations, written with networkx and a Python weight function evaluated on every edge relaxation. On the Nairobi graph (124k nodes, 307k edges), that costs ~50 ms per agent. `FastRouter` (same module) compiles the graph once into CSR arrays and runs the same searches in scipy's C Dijkstra (`scipy.sparse.csgraph.dijkstra`). `assign_routes()` uses it by default (`FastRouter.for_graph(G)`, cached per graph object).

- **Parallel edges collapse** to two numbers per node pair: the shortest walkable (non-transit) edge's length, and, per frequency band, the fastest in-service transit edge's travel time. An agent's cost for the pair is `min(walk_time_weight × length / speed, travel_time + mean_wait)`, the same quantity `_band_edge_weight()` minimises over the parallel edges. The chosen key is the one achieving it.
- **Walk paths don't depend on speed** (every walk edge costs length / one speed), so one length-weighted search serves every agent.
- **Bounded searches.** A walk search first explores to 1.4× the straight-line distance + 300 m, then 2.5× + 1 km, then the whole graph, stopping as soon as the destination is reached (a bounded search that reaches it has found the true shortest path). A transit search is bounded by the agent's weighted pure-walking cost, which is always feasible in the combined graph. If walking takes less than the expected wait, any route that boards must be slower, so the search is skipped.
- **Same decisions** as `route_transit()`: band selection, the in-service check on the boarding edge at the exact departure time, wait draw vs. tolerance, and walk fallbacks.

Checked against networkx on 150 real Nairobi OD pairs: identical routes, except 2 equal-cost ties. Routing takes ~20 ms per agent, vs. ~50 ms with networkx (`tests/test_fast_router_sensitivity.py` checks equivalence on the test graphs).

### Batch route assignment — `assign_routes()`

Note `assign_routes()` never sets `pool.active = True` on success — only `= False` on failure. Activation happens later, in `simulation.py::run()`'s tick loop, once the simulation clock reaches the agent's own `departure_tick`. A newly-routed agent's first edge is set up via the same `_activate_edge()` helper `tick()` uses for every later edge transition (below), so the two never drift apart.

On a routing failure, `assign_routes()` also sets `departure_ticks[i] = -1` (the same "never travels" sentinel `simulation.py` uses for a failed travel-probability gate). Without this, `run()`'s tick loop would still flip the agent active at its original (still-valid) departure tick despite having an empty `route_edges`, closing it out as a bogus zero-length, zero-exposure "completed" trip that very tick — polluting `trip_log`/`agent_modes` with phantom entries for a trip that was never actually assigned.

**Walk or ride.** For each agent, `assign_routes()` first finds the shortest walking route (`FastRouter.walk_distance()`). With `walk_choice="distance"` (default), the agent walks it if a per-agent uniform draw is below `walk_probability(purpose, distance)`, the JICA Nairobi walk-split curves (see [Travel behaviour](../methodology/travel-behaviour.md#mode-split)). Otherwise it plans a transit-capable route with `route_transit()`, reusing the walking route as its fallback and search bound. The walk draw and the boarding-wait draw are made up front, one per agent, before any route is searched, plus a second boarding-wait draw for the trip home. A change in one behavioural parameter therefore doesn't reshuffle the random draws of agents it doesn't affect (see **Determinism and random streams**, below).

The per-trip logic is `plan_route()`, which `assign_routes()` calls for every outbound trip and `run()` calls again for each trip home (see §5). `assign_routes()` returns the draws the trips home need (`RouteDraws`: the walk draws and the return-wait draws); `start_route()` puts an agent at the start of a route.

## 4. Time loop — `model/scheduler.py`

<!-- TODO: document tick() step by step: movement vectorisation, edge transitions, heat sampling -->

`tick()`'s heat/time-density accumulation is **outdoor exposure only**: agents whose current mode is `MODE_TRANSIT` (actually riding, not waiting) are excluded from both `heat_exposure_degC_min` and `time_density` — a matatu passenger isn't exposed to ambient heat the way a walking or waiting pedestrian is. Walking (including access-link legs to/from a stop) and `MODE_WAIT` (standing at a stop before boarding) both still count; only the in-vehicle segment is skipped.

### Transit-boarding wait

Before the position update, agents with `mode == MODE_WAIT` have `wait_ticks_remaining` decremented; once it hits 0, mode flips to the current edge's real mode (walk or transit) in the same `tick()` call, so movement can begin that same tick rather than wasting one. A waiting agent's position is frozen at `edge_u` throughout (excluded from the progress update below) — heat still accumulates each tick at that fixed point, since standing at an exposed stage is itself a real exposure scenario.

### Continuous movement within a tick

Agents move continuously: an agent that reaches the end of its edge partway through a tick carries the rest of the tick onto the next edge, through as many edges as the time allows. It stops early only at the end of its route or at a transit-boarding edge, where it waits at the stop for the rest of the tick. Agents that stay on one edge all tick are updated in one vectorised step; only agents that change edge go through a per-agent Python loop.

Before November 2026, an agent could finish at most one edge per tick and the leftover time was discarded. Half of walking time is on OSM edges shorter than one minute's walk (72 m), so this slowed walkers down by about 60%: 488,000 person-minutes on walked edges against 300,000 at their real speeds (10,000 agents). Outdoor minutes and exposure were inflated accordingly; the earlier calibration was not affected, because access and ride times are measured on planned routes.

**Boarding waits.** An agent reaching a stop with *s* of the tick left waits there for that remainder, and the countdown lets it board in the tick its `wait_ticks_remaining` reaches 0, i.e. after *s* + (`wait_ticks` − 1) ticks. If *s* < 0.5 the countdown gets one extra tick, so the realised wait is within half a tick of `wait_ticks` and right on average.

### Vectorised progress update

Progress advances using `pool.edge_speed_mps`, not `pool.speed_mps` directly: `_activate_edge()` (`model/routing.py`) sets it to the agent's personal walk speed for a walk/access-link edge (unchanged from pre-transit behaviour), but to the transit edge's own `length / travel_time` while riding — a matatu segment moves at its own implied road speed, not the rider's walking pace.

### Edge transition (Python loop over finishing agents)

Delegates to the same `_activate_edge()` helper `assign_routes()` uses for an agent's first edge (see §3 above) — position, edge length, mode, and `edge_speed_mps` are all set in that one place.

### Heat accumulation

Each tick is split into pieces, one per edge or stop the agent spent time on, each with its share of the tick. The outdoor share is the sum of walking and waiting pieces; time riding a transit edge isn't outdoors. UTCI is sampled once per agent per tick, at its end-of-tick position (the destination node for an agent that arrives during the tick), and:

```
heat_exposure_degC_min += max(UTCI − utci_threshold_c, 0) × outdoor_share × timestep_minutes
utci_degC_min          += UTCI × outdoor_share × timestep_minutes
outdoor_min            += outdoor_share × timestep_minutes
```

`utci_threshold_c` is 26 °C (`SimulationParams.utci_threshold_c`, passed to `tick()`); see [Heat exposure metric](../methodology/heat-exposure-metric.md). `utci_degC_min` keeps the raw total for the mean UTCI experienced.

If a `SegmentExposure` (`model/segment_exposure.py`) is passed, each walking piece's heat and minutes go to its directed edge `(u, v, key)`, and each waiting piece's to its stop node (`edge_u` of the transit edge to be boarded). A 5 m edge crossed in 4 seconds therefore gets 4 seconds, not a minute. Per edge or stop it keeps total °C·min above the threshold, person-minutes and **distinct agents** (`n_persons`, each agent counted once however long it spent there). Summed over edges and stops, the attributed heat equals the sum of all agents' exposure.

### Performance notes

The tick loop is cheap: ~2.5 s for 3,000 agents over 14 simulated hours. A run's time goes to loading the graph (~25 s, avoidable with a shared `SimulationContext`, below) and to routing (~20 ms per agent).

## 5. Simulation runner — `model/simulation.py`

<!-- TODO: document SimulationParams, ScenarioResult, run() structure, population synthesis helpers -->

### `SimulationParams`

### `ScenarioResult`

Per agent (arrays of length `n_agents`): the whole day's exposure (°C·min above the UTCI threshold, both trips), raw UTCI × minutes (`agent_utci_degC_min`), outdoor minutes, outbound trip mode (`MODE_TRANSIT` if the route rides at all), purpose, age group, gender, SES, home node and its lon/lat, and trip-timing fields:

| Field | Meaning |
|---|---|
| `agent_access_walk_min` | planned walk from home to the first boarding stop, outbound (NaN if no transit) |
| `agent_ride_min` | planned time from boarding the first vehicle to leaving the last, including transfer walks, outbound (NaN if no transit) |
| `agent_trip_min` | outbound door-to-door duration, departure to arrival (NaN if not arrived by `end_hour`) |
| `agent_outbound_exposure_degC_min` | the part of the day's exposure picked up on the way out |
| `agent_return_departure_hour` | when the trip home was due to leave (NaN if the agent never arrived or return trips are off; may be past `end_hour`) |
| `agent_return_modes` | the trip home's mode; `NO_RETURN` (255) if it never started |
| `agent_returned` | home again by `end_hour` |
| `agent_return_trip_min` | door-to-door duration of the trip home (NaN if unfinished) |

`trip_log` has one entry per finished leg, with `leg` = `"outbound"` or `"return"` and that leg's own exposure.

Spatial: `time_density` (person-minutes per grid cell), `segment_exposure` (one row per directed edge walked: `u, v, key, heat_degC_min, person_min, n_persons`) and `stop_exposure` (one row per stop waited at). `data/export.py` merges the two directions of each street into one line, adds `mean_heat_degC`, `heat_degC_min_per_100m`, `heat_degC_min_per_person` and `min_per_person`, and writes styled GeoPackage layers.

### Shared inputs — `SimulationContext` / `load_context()`

`run(params, context=None)`. Graph, router, amenity index and population rasters don't depend on behaviour parameters, so `load_context(params, G=None)` loads them once and any number of runs can share them. Pass an already-loaded graph as `G` (the notebook does) to avoid holding two ~3 GB copies. A context is only valid for runs with the same graph, amenity and raster paths and bbox.

### `run()` — population synthesis

### `run()` — time loop, trips home and trip logging

Each tick, `run()` first sets off agents whose outbound departure tick it is, then starts the trips home due that tick (`_start_return_trip()`: `plan_route()` from the destination to home at the current tick, with the agent's outbound walk draw and its return-wait draw). After `tick()`, agents that just finished a leg are logged. For an outbound leg, `return_departure_hour()` (`model/agent.py`) sets the time it leaves again from the arrival time and the agent's `returns`-stream z-score: work and school by an end-of-day clock time (but at least `min_stay_min` after arriving), market and other by a lognormal dwell. A trip home due after `end_hour` is not started. See [Travel behaviour](../methodology/travel-behaviour.md#return-trips).

Outbound statistics (`agent_modes`, access and ride times) are taken from the planned outbound routes before the loop, because a trip home replaces the agent's `route_edges`.

### Determinism and random streams

A run is deterministic given `params.seed`. The seed is split (`numpy.random.SeedSequence.spawn`) into one independent stream per model component: spawn locations, demographics, trip counts, purposes, departures, the travel gate, destinations, walking speed, routing and return times. New streams are added at the end of `_RNG_STREAMS`: `SeedSequence.spawn(n)[i]` doesn't depend on *n*, so adding the `returns` stream left every existing stream's draws unchanged (with the same parameters, a one-way run reproduces the earlier results exactly). Departure ticks and destinations are drawn with one uniform per agent through the inverse CDF, and walking speed is mean + SD × a fixed per-agent z-score.

The point is **common random numbers**: two runs with the same seed that differ in one behavioural parameter share every draw that parameter doesn't touch. For example, a faster mean walking speed gives the same homes, destinations and departure times, with every speed shifted by the same amount. Sensitivity analysis and calibration rely on this. Results are numerically different from runs made before this scheme (Nov 2026) at the same seed, though statistically equivalent.

## Phase gate checklist

- [ ] `pytest tests/test_phase2.py -x` passes
- [ ] `TravelBehaviorParams` JSON roundtrip is lossless
- [ ] `tick()` advances progress correctly at known edge lengths and speeds
- [ ] Heat accumulates at exactly `max(UTCI − 26, 0) × timestep_minutes` per tick
- [ ] Two runs with the same seed produce identical `agent_exposure_degC_min`

See [Testing](testing.md) for fixture details.
