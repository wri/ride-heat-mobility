from __future__ import annotations

import logging

import networkx as nx
import numpy as np

from nairobi_heat_abm.model.agent import AgentPool, TravelBehaviorParams

logger = logging.getLogger(__name__)


def route_walk(
    G: nx.MultiDiGraph,
    origin_node: int,
    destination_node: int,
    weight: str = "travel_time",
) -> list[tuple[int, int, int]]:
    """
    Shortest walk path as a list of (u, v, key) edge tuples.
    Raises nx.NetworkXNoPath if no path exists.
    """
    path_nodes = nx.shortest_path(G, origin_node, destination_node, weight=weight)
    edges = []
    for u, v in zip(path_nodes[:-1], path_nodes[1:]):
        key = min(G[u][v], key=lambda k: G[u][v][k].get(weight, float("inf")))
        edges.append((u, v, key))
    return edges


def route_transit(
    G: nx.MultiDiGraph,
    origin_node: int,
    destination_node: int,
    departure_tick: int,
    wait_tolerance_min: float,
    start_hour: int = 6,
) -> list[tuple[int, int, int]]:
    """
    Two-phase routing: walk to stop → valid transit boarding → walk to destination.
    Falls back to full walk route if no valid transit found.
    """
    raise NotImplementedError


def assign_routes(
    pool: AgentPool,
    G: nx.MultiDiGraph,
    origin_nodes: np.ndarray,
    destination_nodes: np.ndarray,
    departure_ticks: np.ndarray,
    params: TravelBehaviorParams,
    rng: np.random.Generator,
) -> None:
    """
    Mutates pool.route_edges and pool.route_index in-place for all agents.
    Agents with no reachable path are marked active=False.
    """
    walk_only_mask = rng.random(pool.n) < params.walk_only_share

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
                )
        except (nx.NetworkXNoPath, nx.NodeNotFound, NotImplementedError) as exc:
            if not isinstance(exc, NotImplementedError):
                logger.warning("No path for agent %d (%d → %d): %s", i, origin, dest, exc)
            pool.active[i] = False
            continue

        pool.route_edges[i] = edges
        if edges:
            u, v, key = edges[0]
            pool.edge_u[i] = u
            pool.edge_v[i] = v
            pool.edge_key[i] = key
            pool.edge_length[i] = G[u][v][key].get("length", 1.0)
