# Phase 2 — ABM core

Build the agent state representation, routing engine, time loop, and simulation runner. No UI code in this phase.

**Completion gate:** `pytest tests/test_phase2.py -x` passes. A single `simulation.run()` call on a small graph with 100 agents produces a non-empty `ScenarioResult`.

---

## 2.1 `TravelBehaviorParams` dataclass

File: `model/agent.py`

```python
from dataclasses import dataclass, field

@dataclass
class TravelBehaviorParams:
    # Trip generation
    trip_rate_mean: float = 3.2        # trips per day
    trip_rate_std: float = 1.1
    trip_rate_distribution: str = "normal"  # "normal" | "poisson"

    # Departure time profile
    departure_profile: str = "bimodal"      # "bimodal" | "uniform" | "custom"
    peak1_hour: float = 7.5
    peak1_weight: float = 0.45
    peak2_hour: float = 17.0
    peak2_weight: float = 0.35

    # Mode split (must sum to 1.0)
    walk_only_share: float = 0.55
    # walk_transit_share = 1.0 - walk_only_share (derived)

    # Trip purpose weights (normalised internally)
    purpose_weights: dict[str, float] = field(default_factory=lambda: {
        "work": 0.40, "school": 0.20, "market": 0.25, "other": 0.15
    })

    # Movement
    walk_speed_mean_mps: float = 1.2
    walk_speed_std_mps: float = 0.15
    transit_wait_tolerance_min: float = 15.0
    transit_wait_tolerance_std: float = 5.0

    def __post_init__(self):
        total = sum(self.purpose_weights.values())
        self.purpose_weights = {k: v / total for k, v in self.purpose_weights.items()}
        if not 0.0 <= self.walk_only_share <= 1.0:
            raise ValueError("walk_only_share must be in [0, 1]")
```

### JSON serialisation

```python
import json, dataclasses

def params_to_json(p: TravelBehaviorParams) -> str:
    d = dataclasses.asdict(p)
    d["schema_version"] = "1.0"
    return json.dumps(d, indent=2)

def params_from_json(s: str) -> TravelBehaviorParams:
    d = json.loads(s)
    d.pop("schema_version", None)
    return TravelBehaviorParams(**d)
```

Also validate against `schemas/travel_behavior.json` using `jsonschema.validate` on load.

### Demographic modifiers and composition

File: `model/agent.py` (added alongside `TravelBehaviorParams`)

Age group (`AGE_CHILD`/`AGE_YOUTH`/`AGE_ADULT`/`AGE_ELDERLY`), gender (`GENDER_MALE`/`GENDER_FEMALE`), and SES/informality (`SES_FORMAL`/`SES_INFORMAL`) codes, mirroring the `MODE_*`/`PURPOSE_*` code convention above.

```python
@dataclass
class ParamModifier:
    trip_rate_mean_mult: float = 1.0
    trip_rate_std_mult: float = 1.0
    purpose_weight_mult: dict[str, float] = field(default_factory=dict)

@dataclass
class DemographicParams:
    age_group_shares: dict[int, float] = field(default_factory=lambda: {...})  # city-wide, not spatial
    gender_shares: dict[int, float] = field(default_factory=lambda: {...})     # city-wide, not spatial
    population_raster_paths: dict[str, Path] | None = None  # spatial age/gender source; see below
    informal_settlement_path: Path | None = None  # spatial SES source; None = all SES_FORMAL
    age_modifiers: dict[int, ParamModifier] = field(default_factory=dict)
    gender_modifiers: dict[int, ParamModifier] = field(default_factory=dict)
    ses_modifiers: dict[int, ParamModifier] = field(default_factory=dict)
```

`SimulationParams.demographics: DemographicParams | None = None` — when `None`, `simulation.run()` behaves exactly as it did before demographics existed (single global `TravelBehaviorParams` draw). When set, `run()` draws `age_group`/`gender` per agent one of two ways:

- `population_raster_paths=None` (default): from the flat city-wide shares (`data/demographics.py::draw_age_gender`, not spatial).
- `population_raster_paths` set to `{"total", "children", "adult", "elderly", "female"}` raster paths (see [1.4](phase1-data-infrastructure.md) `load_population_rasters`): spatially, from each agent's own spawn pixel's local demographic composition (`data/demographics.py::draw_age_gender_spatial`) — an agent spawned in a pixel with a high elderly share is more likely to be drawn elderly, etc. In this mode, `population_raster_paths["total"]` also supersedes `SimulationParams.worldpop_tif_path` as the spawn-density surface for this run, so both spawn location and age/gender come from the same underlying data rather than two independently-loaded "total population" sources.

Either way, `run()` then assigns `ses` via a point-in-polygon join against `informal_settlement_path` (`data/demographics.py::assign_ses`), then for each unique `(age, gender, ses)` segment present, resolves an effective `TravelBehaviorParams` (`simulation.py::_effective_behavior` — combines all three modifiers multiplicatively, relies on `TravelBehaviorParams.__post_init__` to renormalize `purpose_weights`) and draws that segment's trip counts/departure times/purposes from it. See [Population model](../docs/methodology/population-model.md#demographic-composition) for the modeling rationale, including the still-pending informal-settlement boundary data.

---

## 2.2 Agent state — columnar NumPy arrays

File: `model/agent.py`

All agents are stored as parallel arrays, **never** as a list of objects. This is mandatory for vectorised position updates.

```python
@dataclass
class AgentPool:
    n: int

    # Position
    edge_u: np.ndarray        # int64, shape (n,) — source node of current edge
    edge_v: np.ndarray        # int64, shape (n,) — target node of current edge
    edge_key: np.ndarray      # int32, shape (n,) — MultiDiGraph edge key
    progress: np.ndarray      # float32, shape (n,) — 0.0 (at u) to 1.0 (at v)
    edge_length: np.ndarray   # float32, shape (n,) — metres, cached on route assignment

    # Mode: 0=walk, 1=wait, 2=transit
    mode: np.ndarray          # uint8, shape (n,)

    # Movement
    speed_mps: np.ndarray     # float32, shape (n,) — per-agent walk speed

    # Trip state
    active: np.ndarray        # bool, shape (n,) — False when trip complete
    trip_purpose: np.ndarray  # uint8, shape (n,) — 0=work,1=school,2=market,3=other

    # Demographics — zero-initialized (AGE_CHILD/GENDER_MALE/SES_FORMAL) when not modeled
    age_group: np.ndarray     # uint8, shape (n,)
    gender: np.ndarray        # uint8, shape (n,)
    ses: np.ndarray           # uint8, shape (n,)

    # Exposure accumulation
    heat_exposure_degC_min: np.ndarray  # float32, shape (n,) — running total

    # Routing
    route_edges: list[list[tuple]]   # per-agent list of (u, v, key) tuples
    route_index: np.ndarray          # int32, shape (n,) — current position in route

    @classmethod
    def create(cls, n: int) -> "AgentPool":
        return cls(
            n=n,
            edge_u=np.zeros(n, dtype=np.int64),
            edge_v=np.zeros(n, dtype=np.int64),
            edge_key=np.zeros(n, dtype=np.int32),
            progress=np.zeros(n, dtype=np.float32),
            edge_length=np.ones(n, dtype=np.float32),
            mode=np.zeros(n, dtype=np.uint8),
            speed_mps=np.full(n, 1.2, dtype=np.float32),
            active=np.zeros(n, dtype=bool),
            trip_purpose=np.zeros(n, dtype=np.uint8),
            heat_exposure_degC_min=np.zeros(n, dtype=np.float32),
            route_edges=[[] for _ in range(n)],
            route_index=np.zeros(n, dtype=np.int32),
        )
```

---

## 2.3 `model/routing.py` — path-finding

Every route edge is a **4-tuple** `(u, v, key, wait_ticks)`, not the 3-tuple used
pre-transit — `wait_ticks` is 0 for every edge except a transit-boarding edge, where
it's how many ticks the agent should wait at that stop before the ride actually begins.
Folding wait into the edge tuple (rather than a separate return value or a synthetic
graph self-loop) lets `route_walk()` and `route_transit()` share a return type, and
lets `AgentPool.route_edges` stay the single source of truth for both routing and
`tick()`'s edge-transition loop.

### Walk routing

```python
def route_walk(
    G: nx.MultiDiGraph,
    origin_node: int,
    destination_node: int,
    weight: str = "travel_time",
) -> list[tuple[int, int, int, int]]:
    """
    Returns list of (u, v, key, wait_ticks) edge tuples forming the shortest path;
    wait_ticks is always 0 (a pure walk never waits).
    Raises nx.NetworkXNoPath if no path exists.
    """
    path_nodes = nx.shortest_path(G, origin_node, destination_node, weight=weight)
    edges = []
    for u, v in zip(path_nodes[:-1], path_nodes[1:]):
        # MultiDiGraph: pick minimum-weight edge between u and v
        key = min(G[u][v], key=lambda k: G[u][v][k].get(weight, float("inf")))
        edges.append((u, v, key, 0))
    return edges
```

### Transit routing

```python
def route_transit(
    G: nx.MultiDiGraph,
    origin_node: int,
    destination_node: int,
    departure_tick: int,
    wait_tolerance_min: float,
    timestep_s: float,
    bands: list[tuple[int, int]],   # distinct (start_s, end_s) frequency-band boundaries in G
    rng: np.random.Generator,
    start_hour: int = 6,
) -> list[tuple[int, int, int, int]]:
    """
    A single nx.shortest_path() over the WHOLE graph (walk + access-link + transit
    edges together) -- not a three-phase nearest-stop-then-ride search. Each transit
    edge's planning weight is travel_time + expected_wait_for_this_band (mean =
    headway, via _band_edge_weight()); walk/access-link edges just use travel_time.
    So mode choice and route choice both emerge from real comparative time -- Dijkstra
    can pick pure walking when that's genuinely cheaper, with no forced transit
    consideration and no separate nearest-stop snapping step.
    Falls back to route_walk() if G has no transit edges, the departure time falls
    outside every band, the chosen boarding edge has no coverage at the agent's exact
    time, or the actual drawn wait exceeds wait_tolerance_min.
    """
```

The feed is frequency-based (see [1.2](phase1-data-infrastructure.md) `_integrate_gtfs`)
— there's no literal departure clock time to match against `departure_tick`, only
headway bands (`frequencies`, stored on each transit edge). `_distinct_bands()` derives
the set of real band boundaries directly from the data (currently 6-9/9-15/15-21) rather
than hardcoding them, and `assign_routes()` computes this once per call, not per agent.
For **route selection**, each transit edge's weight uses the EXPECTED wait for whichever
band the agent departs in (mean = headway) — this is what lets Dijkstra fairly compare a
frequent-but-slower route against an infrequent-but-faster one. Once a path is chosen,
if it boards a matatu at all, the ACTUAL wait for that first boarding is drawn from
`Exponential(mean=headway)` at the agent's exact departure time (not the band estimate)
— plan on the expectation, experience the randomness. Only the first boarding's wait is
charged; transfers to another route at a shared stop are free. If that drawn wait
exceeds `wait_tolerance_min` (or the edge has no coverage at the exact time, or no band
covers the departure time, or G has no transit at all), `route_transit()` falls back to
a plain `route_walk()` instead of failing the trip outright — `route_walk()` itself
excludes `edge_type=="transit"` edges so a walk trip can never silently ride for free.

### Batch route assignment

```python
def assign_routes(
    pool: AgentPool,
    G: nx.MultiDiGraph,
    origin_nodes: np.ndarray,
    destination_nodes: np.ndarray,
    departure_ticks: np.ndarray,
    params: TravelBehaviorParams,
    rng: np.random.Generator,
    start_hour: int,
    timestep_s: float,
) -> None:
    """Mutates pool.route_edges and pool.route_index in-place."""
```

Assign routes for all agents. Use a simple loop here (routing is pre-simulation, not in the hot loop). Log a warning for any agent where no path is found; mark that agent `active=False`. A successfully-routed agent's first edge is activated via the shared `_activate_edge()` helper (below) — `assign_routes()` does **not** itself set `active=True`; that happens later, in `simulation.run()`'s tick loop, once the simulation clock reaches the agent's own `departure_tick`.

### Shared edge-activation helper

```python
def _activate_edge(pool: AgentPool, i: int, G: nx.MultiDiGraph, u: int, v: int, key: int, wait_ticks: int) -> None:
    """Set agent i's current-edge state: position, edge length, mode, and the
    effective per-tick speed for that edge. Used by both assign_routes() (the agent's
    first edge) and scheduler.py::tick() (every later transition), so the two agree."""
```

- `pool.edge_speed_mps` is set here, not just `pool.speed_mps` used directly: for a walk/access-link edge it equals the agent's own personal walk speed (unchanged behaviour); for a transit edge it's that edge's own `length / travel_time` — a matatu segment isn't traversed at the rider's walking pace. `scheduler.py::tick()`'s progress-advance line reads `edge_speed_mps`, not `speed_mps`, so this is what actually makes riding faster than walking.
- If `wait_ticks > 0`, the agent is put in `MODE_WAIT` with `pool.wait_ticks_remaining[i] = wait_ticks` instead of the edge's real mode — see `tick()` below for how that count winds down.

---

## 2.4 `model/scheduler.py` — time loop

```python
def tick(
    pool: AgentPool,
    G: nx.MultiDiGraph,
    surface: HeatSurface,
    sim_tick: int,          # current tick number
    timestep_s: float,      # seconds per tick (60.0)
    start_hour: int,        # simulation start hour
) -> None:
    """
    Advance all active agents by one timestep. Mutates pool in-place.
    """
```

### Transit-boarding wait countdown

```python
waiting = active & (pool.mode == MODE_WAIT)
pool.wait_ticks_remaining[waiting] = np.maximum(pool.wait_ticks_remaining[waiting] - 1, 0)
done_waiting = waiting & (pool.wait_ticks_remaining == 0)
for i in np.where(done_waiting)[0]:
    # switch to the current edge's real mode now that the wait has elapsed
    ...
```

A waiting agent's position stays exactly at `edge_u` (the boarding stop) throughout —
it's excluded from the progress-advance step below by `mode == MODE_WAIT`, so heat
exposure still accumulates each tick at that fixed location, which is the point: standing
at an exposed matatu stage is itself a real heat-exposure scenario worth modeling
explicitly, not something to skip over.

### Vectorised position update

```python
active = pool.active   # bool mask

# Advance progress for agents that are moving (not waiting)
moving = active & (pool.mode != MODE_WAIT)
pool.progress[moving] += (pool.edge_speed_mps[moving] * timestep_s
                          / pool.edge_length[moving])

# Identify agents who have finished current edge
finished_edge = active & (pool.progress >= 1.0)
```

### Edge transition (Python loop over finishing agents only)

```python
for i in np.where(finished_edge)[0]:
    pool.progress[i] = 0.0
    pool.route_index[i] += 1
    if pool.route_index[i] >= len(pool.route_edges[i]):
        pool.active[i] = False   # trip complete
        continue
    u, v, key = pool.route_edges[i][pool.route_index[i]]
    pool.edge_u[i] = u
    pool.edge_v[i] = v
    pool.edge_key[i] = key
    edge_data = G[u][v][key]
    pool.edge_length[i] = edge_data["length"]
    edge_type = edge_data.get("edge_type", "walk")
    pool.mode[i] = MODE_TRANSIT if edge_type == "transit" else MODE_WALK
```

### Heat sampling (vectorised)

```python
# Interpolate lon/lat from edge progress
hour = start_hour + sim_tick * timestep_s // 3600

# For active agents: interpolate position along edge
u_lons = np.array([G.nodes[u]["x"] for u in pool.edge_u[active]])
u_lats = np.array([G.nodes[u]["y"] for u in pool.edge_u[active]])
v_lons = np.array([G.nodes[v]["x"] for v in pool.edge_v[active]])
v_lats = np.array([G.nodes[v]["y"] for v in pool.edge_v[active]])

p = pool.progress[active]
lons = u_lons + p * (v_lons - u_lons)
lats = u_lats + p * (v_lats - u_lats)

temps = sample_temperature(surface, lons, lats, int(hour))

# Accumulate: °C × (timestep_s / 60) → °C·min
pool.heat_exposure_degC_min[active] += temps * (timestep_s / 60.0)
```

Note: The node coordinate lookup loop above is the main remaining Python bottleneck. If profiling shows it is slow, precompute a node coordinate array indexed by node ID.

---

## 2.5 `model/simulation.py` — runner

### Input/output types

```python
@dataclass
class SimulationParams:
    bbox: tuple[float, float, float, float]
    n_agents: int
    start_hour: int
    end_hour: int
    timestep_s: float
    seed: int
    behavior: TravelBehaviorParams
    graph_cache_path: Path
    amenity_cache_path: Path
    worldpop_tif_path: Path
    heat_surface: HeatSurface           # pre-loaded by caller

@dataclass
class ScenarioResult:
    params: SimulationParams
    agent_exposure_degC_min: np.ndarray   # shape (n_agents,)
    agent_modes: np.ndarray               # uint8, shape (n_agents,)
    agent_purposes: np.ndarray            # uint8, shape (n_agents,)
    agent_n_trips: np.ndarray             # int32, shape (n_agents,)
    trip_log: list[dict]                  # one dict per completed trip
    elapsed_seconds: float
```

### `run()` function

```python
def run(params: SimulationParams) -> ScenarioResult:
    """
    Pure function. No global state. Safe to call from ProcessPoolExecutor workers.
    """
    rng = np.random.default_rng(params.seed)
    G = ox.load_graphml(params.graph_cache_path)
    amenities = load_amenity_index(params.amenity_cache_path)
    density, transform = load_population_raster(params.worldpop_tif_path, params.bbox)

    # Synthesise population
    spawn_nodes, spawn_rows, spawn_cols = sample_spawn_nodes(density, transform, G, params.n_agents, rng)
    n_trips = draw_trip_counts(params.behavior, params.n_agents, rng)
    departure_ticks = draw_departure_ticks(params.behavior, n_trips, params.start_hour, rng)
    dest_nodes = draw_destinations(amenities, spawn_nodes, params.behavior, rng)
    modes = draw_modes(params.behavior, params.n_agents, rng)

    # Build agent pool
    pool = AgentPool.create(params.n_agents)
    assign_routes(pool, G, spawn_nodes, dest_nodes, departure_ticks, params.behavior, rng,
                  params.start_hour, params.timestep_s)

    # Time loop
    n_ticks = int((params.end_hour - params.start_hour) * 3600 / params.timestep_s)
    trip_log = []
    t0 = time.perf_counter()

    for tick_i in range(n_ticks):
        # Activate agents whose departure tick has arrived
        departing = (departure_ticks == tick_i) & ~pool.active
        pool.active[departing] = True

        tick(pool, G, params.heat_surface, tick_i, params.timestep_s, params.start_hour)

        # Log newly completed trips
        just_finished = ~pool.active & (pool.route_index > 0)
        for i in np.where(just_finished)[0]:
            trip_log.append({
                "agent_id": int(i),
                "purpose": int(pool.trip_purpose[i]),
                "mode": int(pool.mode[i]),
                "heat_degC_min": float(pool.heat_exposure_degC_min[i]),
            })

    return ScenarioResult(
        params=params,
        agent_exposure_degC_min=pool.heat_exposure_degC_min.copy(),
        agent_modes=pool.mode.copy(),
        agent_purposes=pool.trip_purpose.copy(),
        agent_n_trips=n_trips,
        trip_log=trip_log,
        elapsed_seconds=time.perf_counter() - t0,
    )
```

---

## 2.6 Tests for Phase 2

File: `tests/test_phase2.py`

```python
def test_params_normalises_purpose_weights():
    p = TravelBehaviorParams(purpose_weights={"work": 2, "school": 1, "market": 1, "other": 0})
    assert abs(sum(p.purpose_weights.values()) - 1.0) < 1e-6

def test_params_json_roundtrip():
    p = TravelBehaviorParams()
    p2 = params_from_json(params_to_json(p))
    assert p == p2

def test_walk_route_returns_connected_edges(tiny_graph):
    edges = route_walk(tiny_graph, origin, dest)
    for i in range(len(edges) - 1):
        assert edges[i][1] == edges[i + 1][0]   # edge chain is continuous

def test_tick_advances_progress(tiny_graph, flat_heat_surface):
    pool = AgentPool.create(10)
    # set up pool with known positions and speeds
    pool.active[:] = True
    pool.mode[:] = MODE_WALK
    pool.speed_mps[:] = 1.2
    pool.edge_length[:] = 120.0   # 100-second edge at 1.2 m/s
    tick(pool, tiny_graph, flat_heat_surface, sim_tick=0, timestep_s=60.0, start_hour=6)
    assert np.all(pool.progress[pool.active] == pytest.approx(0.6, abs=1e-4))

def test_heat_accumulates_correctly(tiny_graph, flat_heat_surface_30C):
    pool = AgentPool.create(5)
    pool.active[:] = True
    pool.mode[:] = MODE_WALK
    tick(pool, tiny_graph, flat_heat_surface_30C, 0, 60.0, 6)
    # 30°C × 1 minute = 30 °C·min
    assert np.all(pool.heat_exposure_degC_min[pool.active] == pytest.approx(30.0, abs=0.1))

def test_simulation_run_returns_result(mini_simulation_params):
    result = run(mini_simulation_params)
    assert isinstance(result, ScenarioResult)
    assert result.agent_exposure_degC_min.shape == (mini_simulation_params.n_agents,)
    assert len(result.trip_log) > 0

def test_simulation_is_deterministic(mini_simulation_params):
    r1 = run(mini_simulation_params)
    r2 = run(mini_simulation_params)
    np.testing.assert_array_equal(r1.agent_exposure_degC_min, r2.agent_exposure_degC_min)
```
