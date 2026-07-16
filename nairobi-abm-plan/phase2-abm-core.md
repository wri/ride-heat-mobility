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

### Walk routing

```python
def route_walk(
    G: nx.MultiDiGraph,
    origin_node: int,
    destination_node: int,
    weight: str = "travel_time",
) -> list[tuple[int, int, int]]:
    """
    Returns list of (u, v, key) edge tuples forming the shortest path.
    Raises nx.NetworkXNoPath if no path exists.
    """
    path_nodes = nx.shortest_path(G, origin_node, destination_node, weight=weight)
    edges = []
    for u, v in zip(path_nodes[:-1], path_nodes[1:]):
        # MultiDiGraph: pick minimum-weight edge between u and v
        key = min(G[u][v], key=lambda k: G[u][v][k].get(weight, float("inf")))
        edges.append((u, v, key))
    return edges
```

### Transit routing

```python
def route_transit(
    G: nx.MultiDiGraph,
    origin_node: int,
    destination_node: int,
    departure_tick: int,           # simulation tick (minutes since start_hour)
    wait_tolerance_min: float,
    start_hour: int = 6,
) -> list[tuple[int, int, int]]:
    """
    Two-phase routing:
      Phase 1: walk origin → nearest reachable transit stop
      Phase 2: find valid boarding edge (departure within wait_tolerance)
               ride to stop nearest destination
      Phase 3: walk final stop → destination
    Falls back to full walk route if no valid transit found.
    """
```

Implementation notes:
- Filter transit edges to those with `departure_time` within `[current_time, current_time + wait_tolerance]`.
- Use a subgraph containing only walk edges + valid transit edges for path-finding.
- Do not call `nx.shortest_path` on the full graph with mixed edge types — pre-filter.

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
) -> None:
    """Mutates pool.route_edges and pool.route_index in-place."""
```

Assign routes for all agents. Use a simple loop here (routing is pre-simulation, not in the hot loop). Log a warning for any agent where no path is found; mark that agent `active=False`.

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

### Vectorised position update

```python
active = pool.active   # bool mask

# Advance progress for walking and transit agents (not waiting)
moving = active & (pool.mode != MODE_WAIT)
pool.progress[moving] += (pool.speed_mps[moving] * timestep_s
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
    spawn_nodes = sample_spawn_nodes(density, transform, G, params.n_agents, rng)
    n_trips = draw_trip_counts(params.behavior, params.n_agents, rng)
    departure_ticks = draw_departure_ticks(params.behavior, n_trips, params.start_hour, rng)
    dest_nodes = draw_destinations(amenities, spawn_nodes, params.behavior, rng)
    modes = draw_modes(params.behavior, params.n_agents, rng)

    # Build agent pool
    pool = AgentPool.create(params.n_agents)
    assign_routes(pool, G, spawn_nodes, dest_nodes, departure_ticks, params.behavior, rng)

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
