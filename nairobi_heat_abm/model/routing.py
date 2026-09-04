from __future__ import annotations

import logging

import networkx as nx
import numpy as np
import osmnx as ox

from nairobi_heat_abm.model.agent import AgentPool, MODE_TRANSIT, MODE_WAIT, MODE_WALK, TravelBehaviorParams

logger = logging.getLogger(__name__)


def route_walk(
    G: nx.MultiDiGraph,
    origin_node: int,
    destination_node: int,
    weight: str = "travel_time",
) -> list[tuple[int, int, int, int]]:
    """
    Shortest walk path as a list of (u, v, key, wait_ticks) edge tuples — wait_ticks is
    always 0 here (a pure walk never waits); the 4th element exists so callers can treat
    a route_walk() and a route_transit() result the same way.
    Raises nx.NetworkXNoPath if no path exists.
    """
    path_nodes = nx.shortest_path(G, origin_node, destination_node, weight=weight)
    edges = []
    for u, v in zip(path_nodes[:-1], path_nodes[1:]):
        key = min(G[u][v], key=lambda k: G[u][v][k].get(weight, float("inf")))
        edges.append((u, v, key, 0))
    return edges


def _transit_stops_subgraph(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """All transit_stop nodes, for nearest-stop spatial lookups. Computed once per
    assign_routes() call and reused across agents — not per agent, since it doesn't
    depend on any agent's origin/destination."""
    stop_ids = [n for n, d in G.nodes(data=True) if d.get("node_type") == "transit_stop"]
    return G.subgraph(stop_ids)


def _transit_edges_subgraph(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Only the "transit" (ride) edges, for the boarding->alighting leg of a transit
    trip — excludes access_link and walk edges so the search can't "cheat" by walking
    through the street network instead of actually riding."""
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


def route_transit(
    G: nx.MultiDiGraph,
    origin_node: int,
    destination_node: int,
    departure_tick: int,
    wait_tolerance_min: float,
    timestep_s: float,
    stops_subgraph: nx.MultiDiGraph,
    transit_subgraph: nx.MultiDiGraph,
    start_hour: int = 6,
) -> list[tuple[int, int, int, int]]:
    """
    Three-phase routing: walk origin -> nearest transit stop, ride the transit-only
    subgraph to the stop nearest the destination, walk that stop -> destination.
    Falls back to a full route_walk() (wait_ticks=0 throughout) if the graph has no
    transit stops/edges at all.

    This feed is frequency-based (see data/graph.py::_integrate_gtfs), so "does a
    matatu leave when I need it" is answered by headway, not a literal timetable
    lookup: the expected wait at boarding is half the applicable headway (a rider
    arriving at a random time under headway-based service waits headway/2 on average).
    If no frequency band covers the agent's departure time, or the expected wait
    exceeds wait_tolerance_min, this raises nx.NetworkXNoPath — same as "no path found"
    — and the caller (assign_routes) falls back the agent to walking that trip instead.

    Route transfers between different matatu routes are allowed for free wherever they
    share a physical stop (the transit-only shortest path can cross routes at a shared
    stop node) — but only the FIRST boarding's wait is charged; transfer wait time isn't
    modeled. This is a deliberate simplification, not an oversight.
    """
    if stops_subgraph.number_of_nodes() == 0 or transit_subgraph.number_of_nodes() == 0:
        return route_walk(G, origin_node, destination_node)

    o, d = G.nodes[origin_node], G.nodes[destination_node]
    stop_o = int(ox.nearest_nodes(stops_subgraph, X=o["x"], Y=o["y"]))
    stop_d = int(ox.nearest_nodes(stops_subgraph, X=d["x"], Y=d["y"]))
    if stop_o == stop_d:
        raise nx.NetworkXNoPath("origin and destination share the same nearest transit stop")

    ride_nodes = nx.shortest_path(transit_subgraph, stop_o, stop_d, weight="travel_time")
    ride_edges = []
    for u, v in zip(ride_nodes[:-1], ride_nodes[1:]):
        key = min(transit_subgraph[u][v], key=lambda k: transit_subgraph[u][v][k].get("travel_time", float("inf")))
        ride_edges.append((u, v, key))

    first_edge_data = G[ride_edges[0][0]][ride_edges[0][1]][ride_edges[0][2]]
    time_of_day_s = (start_hour * 3600 + departure_tick * timestep_s) % 86400
    headway_s = _headway_at(first_edge_data.get("frequencies", []), time_of_day_s)
    if headway_s is None:
        raise nx.NetworkXNoPath("no scheduled matatu service for this trip at the agent's departure time")

    wait_s = headway_s / 2.0
    if wait_s > wait_tolerance_min * 60.0:
        raise nx.NetworkXNoPath(f"expected wait {wait_s:.0f}s exceeds tolerance ({wait_tolerance_min:.0f} min)")
    wait_ticks = int(round(wait_s / timestep_s))

    access_out = route_walk(G, origin_node, stop_o)
    access_in = route_walk(G, stop_d, destination_node)
    ride_edges_4 = [(u, v, key, wait_ticks if idx == 0 else 0) for idx, (u, v, key) in enumerate(ride_edges)]

    return access_out + ride_edges_4 + access_in


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
    Agents with no reachable path are marked active=False.
    """
    walk_only_mask = rng.random(pool.n) < params.walk_only_share
    stops_subgraph = _transit_stops_subgraph(G)
    transit_subgraph = _transit_edges_subgraph(G)

    for i in range(pool.n):
        origin = int(origin_nodes[i])
        dest = int(destination_nodes[i])
        try:
            if walk_only_mask[i]:
                edges = route_walk(G, origin, dest)
            else:
                edges = route_transit(
                    G, origin, dest,
                    departure_tick=int(departure_ticks[i]),
                    wait_tolerance_min=params.transit_wait_tolerance_min,
                    timestep_s=timestep_s,
                    stops_subgraph=stops_subgraph,
                    transit_subgraph=transit_subgraph,
                    start_hour=start_hour,
                )
        except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
            logger.warning("No path for agent %d (%d → %d): %s", i, origin, dest, exc)
            pool.active[i] = False
            continue

        pool.route_edges[i] = edges
        if edges:
            u, v, key, wait_ticks = edges[0]
            _activate_edge(pool, i, G, u, v, key, wait_ticks)
