from __future__ import annotations

import logging

import networkx as nx
import numpy as np

from nairobi_heat_abm.model.agent import AgentPool, MODE_TRANSIT, MODE_WAIT, MODE_WALK, TravelBehaviorParams

logger = logging.getLogger(__name__)


def _real_walk_cost(attr: dict, walk_speed_mps: float) -> float:
    """
    Real time to traverse one edge, in seconds -- NOT the edge's own stored
    "travel_time" for anything but a transit ride. osmnx's add_edge_speeds()/
    add_edge_travel_times() (data/graph.py::build_graph()) impute VEHICLE speed from
    OSM maxspeed/highway-type even though the network was fetched as
    network_type="walk" (osmnx has no pedestrian-speed mode) -- so an ordinary street
    edge's "travel_time" reflects driving pace, not walking pace (a 30km stretch can
    show ~33 minutes, i.e. ~54 km/h). access_link edges happen to already use a
    hardcoded 1.2 m/s (data/graph.py::_integrate_gtfs), closer but not this specific
    agent's own speed. Recomputing length/walk_speed_mps for every non-transit edge
    makes every walked segment consistent with the agent's real pace, which matters a
    lot once this cost is compared directly against a transit edge's wait+ride time --
    comparing a vehicle-paced "walk" against a real transit cost would make walking
    always look free, regardless of actual distance.
    """
    if attr.get("edge_type") == "transit":
        return attr.get("travel_time", 1.0)  # real GTFS ride time -- already trustworthy
    return attr.get("length", 1.0) / walk_speed_mps


def _non_transit_weight(walk_speed_mps: float):
    """Weight-function factory excluding edge_type=="transit" edges entirely (using
    real walking time for the rest, see _real_walk_cost) — used so a "walk" path can
    never silently ride a matatu for free (with no wait charged and no acknowledgment
    the agent ever boarded a vehicle)."""
    def weight_fn(u, v, d):
        walkable = [_real_walk_cost(attr, walk_speed_mps) for attr in d.values() if attr.get("edge_type") != "transit"]
        return min(walkable) if walkable else float("inf")
    return weight_fn


def route_walk(
    G: nx.MultiDiGraph,
    origin_node: int,
    destination_node: int,
    walk_speed_mps: float,
) -> list[tuple[int, int, int, int]]:
    """
    Shortest walk path as a list of (u, v, key, wait_ticks) edge tuples — wait_ticks is
    always 0 here (a pure walk never waits); the 4th element exists so callers can treat
    a route_walk() and a route_transit() result the same way. Never uses a "transit"
    edge (see _non_transit_weight) — access_link edges (walking to/from a stop) are
    still fair game, since those are genuinely walked, not ridden. Weighted by this
    agent's own real walking pace (see _real_walk_cost), not the graph's own
    (vehicle-calibrated) "travel_time" attribute.
    Raises nx.NetworkXNoPath if no path exists.
    """
    path_nodes = nx.shortest_path(G, origin_node, destination_node, weight=_non_transit_weight(walk_speed_mps))
    edges = []
    for u, v in zip(path_nodes[:-1], path_nodes[1:]):
        candidates = {k: attr for k, attr in G[u][v].items() if attr.get("edge_type") != "transit"}
        key = min(candidates, key=lambda k: _real_walk_cost(candidates[k], walk_speed_mps))
        edges.append((u, v, key, 0))
    return edges


def _transit_stops_subgraph(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """All transit_stop nodes — a general-purpose spatial view (e.g. counting stops,
    nearest-stop diagnostics). Not used internally by route_transit()/assign_routes()
    anymore (routing searches the whole graph in one pass), but kept as a utility."""
    stop_ids = [n for n, d in G.nodes(data=True) if d.get("node_type") == "transit_stop"]
    return G.subgraph(stop_ids)


def _transit_edges_subgraph(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Only the "transit" (ride) edges — a general-purpose view (e.g. counting ride
    edges). Not used internally by route_transit()/assign_routes() anymore, but kept
    as a utility."""
    transit_edges = [(u, v, k) for u, v, k, d in G.edges(keys=True, data=True) if d.get("edge_type") == "transit"]
    if not transit_edges:
        return nx.MultiDiGraph()
    return G.edge_subgraph(transit_edges)


def _headway_at(frequencies: list[list[int]], time_of_day_s: float) -> int | None:
    """Headway (seconds) for the frequency band covering time_of_day_s, or None if
    time_of_day_s falls outside every band (e.g. late night, when this feed has no
    defined service)."""
    for start_s, end_s, headway_s in frequencies:
        if start_s <= time_of_day_s < end_s:
            return headway_s
    return None


def _distinct_bands(G: nx.MultiDiGraph) -> list[tuple[int, int]]:
    """
    Every distinct (start_s, end_s) frequency-band boundary used anywhere in G's
    transit edges, sorted. Derived from the data rather than hardcoded, so this
    adapts automatically if a future feed's bands differ from this one's — but it
    does assume bands are shared/aligned across trips (true of the current
    DigitalMatatus feed: every trip with frequency data uses the same three
    boundaries, 6-9/9-15/15-21). Empty if G has no transit edges at all.
    """
    bands: set[tuple[int, int]] = set()
    for _, _, d in G.edges(data=True):
        if d.get("edge_type") != "transit":
            continue
        for start_s, end_s, _headway in d.get("frequencies", []):
            bands.add((start_s, end_s))
    return sorted(bands)


def _band_edge_weight(band_mid_s: float, walk_speed_mps: float):
    """
    Weight-function factory for a single frequency band: a transit edge's weight is
    its own (real GTFS) travel_time PLUS the expected wait for boarding it in this
    band (mean = headway, matching route_transit()'s Exponential(mean=headway) model)
    — a transit edge with no coverage for this band is excluded (infinite weight).
    Every other edge uses this agent's real walking pace (see _real_walk_cost), not
    the graph's own travel_time (vehicle-calibrated for ordinary street edges).

    band_mid_s is a representative instant used only to look up which of an edge's
    OWN frequency bands applies (via _headway_at) — since every edge in this feed
    shares the same band boundaries, this reduces to an exact lookup in practice.
    """
    def weight_fn(u, v, d):
        best = float("inf")
        for attr in d.values():
            if attr.get("edge_type") == "transit":
                headway = _headway_at(attr.get("frequencies", []), band_mid_s)
                if headway is None:
                    continue  # no service in this band on this parallel edge
                cost = attr.get("travel_time", 1.0) + headway
            else:
                cost = _real_walk_cost(attr, walk_speed_mps)
            best = min(best, cost)
        return best
    return weight_fn


def _select_edge(G: nx.MultiDiGraph, u: int, v: int, weight_fn) -> int:
    """The parallel-edge key between u and v that weight_fn would have picked —
    reconstructs shortest_path()'s per-hop choice so the returned edge list matches
    the cost the search actually minimized."""
    candidates = G[u][v]
    return min(candidates, key=lambda k: weight_fn(u, v, {k: candidates[k]}))


def route_transit(
    G: nx.MultiDiGraph,
    origin_node: int,
    destination_node: int,
    departure_tick: int,
    wait_tolerance_min: float,
    timestep_s: float,
    bands: list[tuple[int, int]],
    rng: np.random.Generator,
    walk_speed_mps: float,
    start_hour: int = 6,
) -> list[tuple[int, int, int, int]]:
    """
    Single unified shortest path over the WHOLE graph (walk + access-link + transit
    edges together), weighted so that mode choice and route choice both emerge from
    real comparative time instead of being decided separately: a transit edge's
    planning weight is its own travel_time plus the EXPECTED wait for that edge's
    frequency band (mean = headway) — see _band_edge_weight(). Dijkstra then picks
    whichever combination of walking and riding minimizes total planning-weight,
    including picking pure walking when that's genuinely faster; there's no separate
    nearest-stop snapping step, since the graph's own access_link edges already let
    the search reach and leave stops as part of the same path.

    Once a path is chosen, if it boards a matatu at all, the ACTUAL wait for that
    FIRST boarding is drawn from Exponential(mean=headway) at the agent's real
    departure time (not the band-representative estimate used for planning) — plan on
    the expectation, experience the randomness. Transfers to another route at a shared
    stop are free wherever the path crosses one (only the first boarding's wait is
    charged; transfer wait time isn't modeled — a deliberate simplification, not an
    oversight). If the drawn wait exceeds wait_tolerance_min, or the boarding edge
    turns out to have no coverage at the agent's exact departure time, this trip falls
    back to a plain route_walk() instead of failing outright.

    Falls back to route_walk() immediately if G has no transit edges at all, or if the
    agent's departure time falls outside every known frequency band.
    """
    if not bands:
        return route_walk(G, origin_node, destination_node, walk_speed_mps)

    time_of_day_s = (start_hour * 3600 + departure_tick * timestep_s) % 86400
    band = next((b for b in bands if b[0] <= time_of_day_s < b[1]), None)
    if band is None:
        return route_walk(G, origin_node, destination_node, walk_speed_mps)

    weight_fn = _band_edge_weight((band[0] + band[1]) / 2.0, walk_speed_mps)
    try:
        path_nodes = nx.shortest_path(G, origin_node, destination_node, weight=weight_fn)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return route_walk(G, origin_node, destination_node, walk_speed_mps)

    edges = [[u, v, _select_edge(G, u, v, weight_fn), 0] for u, v in zip(path_nodes[:-1], path_nodes[1:])]

    first_transit_idx = next(
        (i for i, (u, v, key, _) in enumerate(edges) if G[u][v][key].get("edge_type") == "transit"),
        None,
    )
    if first_transit_idx is None:
        return [tuple(e) for e in edges]  # walking alone was the cheapest option this band

    u, v, key, _ = edges[first_transit_idx]
    headway_s = _headway_at(G[u][v][key].get("frequencies", []), time_of_day_s)
    if headway_s is None:
        return route_walk(G, origin_node, destination_node, walk_speed_mps)

    wait_s = float(rng.exponential(scale=headway_s))
    if wait_s > wait_tolerance_min * 60.0:
        return route_walk(G, origin_node, destination_node, walk_speed_mps)

    edges[first_transit_idx][3] = int(round(wait_s / timestep_s))
    return [tuple(e) for e in edges]


def _activate_edge(pool: AgentPool, i: int, G: nx.MultiDiGraph, u: int, v: int, key: int, wait_ticks: int) -> None:
    """
    Set agent i's current-edge state — position, edge length, movement mode, and the
    effective per-tick speed for that edge. Shared by assign_routes() (the agent's
    first edge) and scheduler.py::tick() (every later edge transition) so the two stay
    consistent.

    wait_ticks > 0 means this edge is a transit boarding: the agent sits at u
    (mode=MODE_WAIT, progress frozen at 0) for wait_ticks ticks before actually riding.
    """
    pool.edge_u[i] = u
    pool.edge_v[i] = v
    pool.edge_key[i] = key
    edge_data = G[u][v][key]
    length = float(edge_data.get("length", 1.0))
    pool.edge_length[i] = length
    is_transit = edge_data.get("edge_type") == "transit"

    if wait_ticks > 0:
        pool.mode[i] = MODE_WAIT
        pool.wait_ticks_remaining[i] = wait_ticks
    else:
        pool.mode[i] = MODE_TRANSIT if is_transit else MODE_WALK
        pool.wait_ticks_remaining[i] = 0

    if is_transit:
        travel_time = float(edge_data.get("travel_time", length))
        pool.edge_speed_mps[i] = length / travel_time if travel_time > 0 else pool.speed_mps[i]
    else:
        pool.edge_speed_mps[i] = pool.speed_mps[i]


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
    """
    Mutates pool.route_edges and pool.route_index in-place for all agents.
    Agents with no reachable path are marked active=False and their departure_ticks
    entry is set to -1 (the same "never travels" sentinel simulation.py uses for a
    failed travel-probability gate) so run()'s tick loop never reactivates them at
    their original departure tick -- without this, a departure tick still in the
    future would flip pool.active back to True, and the agent would then close out
    as a bogus zero-length, zero-exposure "completed" trip on that very tick (empty
    route_edges immediately satisfies route_index >= len(route_edges)), polluting
    trip_log/agent_modes with phantom entries even though no route was ever assigned.
    """
    walk_only_mask = rng.random(pool.n) < params.walk_only_share
    bands = _distinct_bands(G)

    for i in range(pool.n):
        origin = int(origin_nodes[i])
        dest = int(destination_nodes[i])
        walk_speed_mps = float(pool.speed_mps[i])
        try:
            if walk_only_mask[i]:
                edges = route_walk(G, origin, dest, walk_speed_mps)
            else:
                edges = route_transit(
                    G, origin, dest,
                    departure_tick=int(departure_ticks[i]),
                    wait_tolerance_min=params.transit_wait_tolerance_min,
                    timestep_s=timestep_s,
                    bands=bands,
                    rng=rng,
                    walk_speed_mps=walk_speed_mps,
                    start_hour=start_hour,
                )
        except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
            logger.warning("No path for agent %d (%d → %d): %s", i, origin, dest, exc)
            pool.active[i] = False
            departure_ticks[i] = -1
            continue

        pool.route_edges[i] = edges
        if edges:
            u, v, key, wait_ticks = edges[0]
            _activate_edge(pool, i, G, u, v, key, wait_ticks)
