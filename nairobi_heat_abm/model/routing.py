from __future__ import annotations

import logging
import weakref
from dataclasses import dataclass

import networkx as nx
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from nairobi_heat_abm.model.agent import (
    AgentPool, MODE_TRANSIT, MODE_WAIT, MODE_WALK, TravelBehaviorParams, walk_probability,
)

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


def _band_edge_weight(band_mid_s: float, walk_speed_mps: float, mean_wait_s: float, walk_time_weight: float = 1.0):
    """
    Weight-function factory for a single frequency band: a transit edge's weight is
    its own (real GTFS) travel_time PLUS the expected boarding wait mean_wait_s
    (matching route_transit()'s Exponential(mean=mean_wait_s) draw) — a transit edge
    with no coverage for this band is excluded (infinite weight). The band's headway
    decides only WHETHER an edge is in service, not how long the wait is: the feed's
    headways are a uniform placeholder schedule (5/15/5 min on every trip), so the
    wait mean comes from the rider survey instead (see TravelBehaviorParams.
    transit_mean_wait_min).
    Every other edge uses this agent's real walking pace (see _real_walk_cost), not
    the graph's own travel_time (vehicle-calibrated for ordinary street edges).

    band_mid_s is a representative instant used only to look up which of an edge's
    OWN frequency bands applies (via _headway_at) — i.e. whether it is in service
    then. Since every edge in this feed
    shares the same band boundaries, this reduces to an exact lookup in practice.
    """
    def weight_fn(u, v, d):
        best = float("inf")
        for attr in d.values():
            if attr.get("edge_type") == "transit":
                if _headway_at(attr.get("frequencies", []), band_mid_s) is None:
                    continue  # no service in this band on this parallel edge
                cost = attr.get("travel_time", 1.0) + mean_wait_s
            else:
                cost = walk_time_weight * _real_walk_cost(attr, walk_speed_mps)
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
    mean_wait_min: float,
    timestep_s: float,
    bands: list[tuple[int, int]],
    rng: np.random.Generator,
    walk_speed_mps: float,
    start_hour: int = 6,
    walk_time_weight: float = 1.0,
) -> list[tuple[int, int, int, int]]:
    """
    Single unified shortest path over the WHOLE graph (walk + access-link + transit
    edges together), weighted so that mode choice and route choice both emerge from
    real comparative time instead of being decided separately: a transit edge's
    planning weight is its own travel_time plus the EXPECTED wait for that edge's
    boarding wait (mean_wait_min) — see _band_edge_weight(). Dijkstra then picks
    whichever combination of walking and riding minimizes total planning-weight,
    including picking pure walking when that's genuinely faster; there's no separate
    nearest-stop snapping step, since the graph's own access_link edges already let
    the search reach and leave stops as part of the same path.

    Once a path is chosen, if it boards a matatu at all, the ACTUAL wait for that
    FIRST boarding is drawn from Exponential(mean=mean_wait_min) — plan on the
    expectation, experience the randomness. mean_wait_min is calibrated from the WRI
    rider survey (TravelBehaviorParams.transit_mean_wait_min), not from GTFS headway;
    the GTFS frequency bands only decide whether a route is in service at the agent's
    departure time. Transfers to another route at a shared
    stop are free wherever the path crosses one (only the first boarding's wait is
    charged; transfer wait time isn't modeled — a deliberate simplification, not an
    oversight). If the drawn wait exceeds wait_tolerance_min, the agent walks the whole
    way instead only when walking would get it there no later than waiting and riding
    (see _gives_up_waiting); otherwise it waits and boards. If the boarding edge has no
    coverage at the agent's exact departure time, the trip falls back to a plain
    route_walk() instead of failing outright.

    Falls back to route_walk() immediately if G has no transit edges at all, or if the
    agent's departure time falls outside every known frequency band.
    """
    if not bands:
        return route_walk(G, origin_node, destination_node, walk_speed_mps)

    time_of_day_s = (start_hour * 3600 + departure_tick * timestep_s) % 86400
    band = next((b for b in bands if b[0] <= time_of_day_s < b[1]), None)
    if band is None:
        return route_walk(G, origin_node, destination_node, walk_speed_mps)

    mean_wait_s = mean_wait_min * 60.0
    weight_fn = _band_edge_weight((band[0] + band[1]) / 2.0, walk_speed_mps, mean_wait_s, walk_time_weight)
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
    if _headway_at(G[u][v][key].get("frequencies", []), time_of_day_s) is None:
        return route_walk(G, origin_node, destination_node, walk_speed_mps)  # not in service right now

    wait_s = float(rng.exponential(scale=mean_wait_s))
    if wait_s > wait_tolerance_min * 60.0:
        route_s = sum(_edge_travel_s(G[u][v][k], walk_speed_mps) for u, v, k, _ in edges)
        try:
            walk_route = route_walk(G, origin_node, destination_node, walk_speed_mps)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            walk_route = None
        walk_m = (sum(float(G[u][v][k].get("length", 0.0)) for u, v, k, _ in walk_route)
                  if walk_route is not None else None)
        if _gives_up_waiting(wait_s, wait_tolerance_min, walk_m, walk_speed_mps, route_s):
            return walk_route

    edges[first_transit_idx][3] = int(round(wait_s / timestep_s))
    return [tuple(e) for e in edges]


def _edge_travel_s(data: dict, walk_speed_mps: float) -> float:
    """Unweighted seconds to traverse one edge: a ride's travel_time, else walking."""
    if data.get("edge_type") == "transit":
        return float(data.get("travel_time", data.get("length", 0.0)))
    return float(data.get("length", 0.0)) / walk_speed_mps


def _gives_up_waiting(wait_s: float, wait_tolerance_min: float, walk_m: float | None,
                      walk_speed_mps: float, route_s: float) -> bool:
    """
    Whether an agent facing a boarding wait of wait_s walks the whole way instead.

    Only a wait longer than the agent's tolerance makes it consider walking, and it
    then walks only if walking would get it there no later than waiting and riding:
    walk time <= wait + the transit route's own travel time (unweighted seconds; the
    walking-time weight shapes route choice, not this comparison). Otherwise it waits
    and boards. Before 2026-11-08 every wait over tolerance meant walking, however far,
    which sent riders on forced walks of up to ~40 km.
    """
    if wait_s <= wait_tolerance_min * 60.0 or walk_m is None:
        return False
    return walk_m / walk_speed_mps <= wait_s + route_s


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


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2.0) ** 2
    return float(6_371_000.0 * 2.0 * np.arcsin(np.sqrt(min(max(a, 0.0), 1.0))))


class FastRouter:
    """
    G compiled once into CSR arrays so route search runs in scipy's C Dijkstra instead
    of networkx with a Python weight callback per edge relaxation (~0.25 s per agent
    on the Nairobi graph, ~90% of a run). Gives the same routes as route_walk() /
    route_transit() — same weights, same fallbacks, same parallel-edge choice — up to
    ties between equal-cost paths.

    Parallel edges between a node pair collapse to two numbers per pair: the shortest
    walkable (non-"transit") edge, and, per frequency band, the fastest transit edge in
    service. An agent's cost for the pair is then
    min(walk_len / walk_speed, transit_travel_time + mean_wait), which is what
    _band_edge_weight() / _non_transit_weight() minimise over d.values().

    Searches are bounded: a walk search first explores up to 1.4x the straight-line
    distance + 300 m, widening (to the whole graph at most) until the destination is
    reached — a bounded search that reaches it has found the true shortest path — and
    a transit search never needs to look past the agent's pure-walking time, which is
    always feasible in the combined graph.
    """

    _EPS = 1e-9  # keep zero-length edges as edges (csgraph drops explicit zeros)
    _cache: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()

    def __init__(self, G: nx.MultiDiGraph):
        nodes = list(G.nodes())
        self.nodes = np.asarray(nodes, dtype=np.int64)
        self.index = {n: i for i, n in enumerate(nodes)}
        self.lon = np.array([G.nodes[n]["x"] for n in nodes], dtype=np.float64)
        self.lat = np.array([G.nodes[n]["y"] for n in nodes], dtype=np.float64)
        self.bands = _distinct_bands(G)
        mids = [(a + b) / 2.0 for a, b in self.bands]

        walk: dict[tuple[int, int], tuple[float, int]] = {}
        transit: dict[tuple[int, int], list[tuple[float, int, list]]] = {}
        for u, v, k, d in G.edges(keys=True, data=True):
            pair = (self.index[u], self.index[v])
            if d.get("edge_type") == "transit":
                transit.setdefault(pair, []).append((float(d.get("travel_time", 1.0)), k, d.get("frequencies", [])))
            else:
                length = float(d.get("length", 1.0))
                if pair not in walk or length < walk[pair][0]:
                    walk[pair] = (length, k)

        pairs = sorted(set(walk) | set(transit))  # (row, col) order = CSR order
        n_pairs, n_nodes = len(pairs), len(nodes)
        rows = np.fromiter((p[0] for p in pairs), dtype=np.int64, count=n_pairs)
        cols = np.fromiter((p[1] for p in pairs), dtype=np.int64, count=n_pairs)
        self.pair_index = {p: j for j, p in enumerate(pairs)}

        self.walk_len = np.full(n_pairs, np.inf)
        self.walk_key = np.zeros(n_pairs, dtype=np.int64)
        for p, (length, k) in walk.items():
            j = self.pair_index[p]
            self.walk_len[j] = max(length, self._EPS)
            self.walk_key[j] = k

        # Per band: the fastest transit edge in service at the band's midpoint (inf = none).
        self.transit_tt = np.full((len(self.bands), n_pairs), np.inf)
        self.transit_key = np.zeros((len(self.bands), n_pairs), dtype=np.int64)
        self.transit_freqs: dict[tuple[int, int, int], list] = {}
        for p, options in transit.items():
            j = self.pair_index[p]
            for b, mid in enumerate(mids):
                for tt, k, freqs in options:
                    if _headway_at(freqs, mid) is not None and tt < self.transit_tt[b, j]:
                        self.transit_tt[b, j] = max(tt, self._EPS)
                        self.transit_key[b, j] = k
            for _tt, k, freqs in options:
                self.transit_freqs[(p[0], p[1], k)] = freqs

        def _indptr(r: np.ndarray) -> np.ndarray:
            return np.concatenate([[0], np.cumsum(np.bincount(r, minlength=n_nodes))]).astype(np.int32)

        self._shape = (n_nodes, n_nodes)
        self._indices = cols.astype(np.int32)
        self._indptr = _indptr(rows)
        walk_ok = np.isfinite(self.walk_len)
        self._walk_csr = csr_matrix(
            (self.walk_len[walk_ok], cols[walk_ok].astype(np.int32), _indptr(rows[walk_ok])), shape=self._shape,
        )

    @classmethod
    def for_graph(cls, G: nx.MultiDiGraph) -> "FastRouter":
        """One router per graph object, built on first use and reused while G lives."""
        router = cls._cache.get(G)
        if router is None:
            router = cls(G)
            cls._cache[G] = router
        return router

    def _search(self, csr, origin: int, dest: int, limit: float) -> tuple[float, list[int]] | None:
        dist, pred = dijkstra(csr, directed=True, indices=origin, return_predecessors=True, limit=limit)
        if not np.isfinite(dist[dest]):
            return None
        path = [dest]
        while path[-1] != origin:
            path.append(int(pred[path[-1]]))
        return float(dist[dest]), path[::-1]

    def _indices_of(self, origin_node: int, destination_node: int) -> tuple[int, int]:
        try:
            return self.index[origin_node], self.index[destination_node]
        except KeyError as exc:
            raise nx.NodeNotFound(f"Node {exc.args[0]} not in graph") from exc

    def _walk_path(self, o: int, d: int) -> tuple[float, list[int]]:
        """Shortest walkable path by length — speed-independent, since every walk
        edge's time is length / the agent's one speed. Raises nx.NetworkXNoPath."""
        if o == d:
            return 0.0, [o]
        crow = _haversine_m(self.lon[o], self.lat[o], self.lon[d], self.lat[d])
        found = None
        for limit in (1.4 * crow + 300.0, 2.5 * crow + 1000.0, np.inf):  # widen until reached
            found = self._search(self._walk_csr, o, d, limit=limit)
            if found is not None:
                break
        if found is None:
            raise nx.NetworkXNoPath(f"No walkable path {self.nodes[o]} -> {self.nodes[d]}")
        return found

    def _walk_edges(self, path: list[int]) -> list[tuple[int, int, int, int]]:
        return [
            (int(self.nodes[a]), int(self.nodes[b]), int(self.walk_key[self.pair_index[(a, b)]]), 0)
            for a, b in zip(path[:-1], path[1:])
        ]

    def walk_distance(self, origin_node: int, destination_node: int) -> tuple[float, list[int] | None]:
        """(metres, node-index path) of the shortest walkable route; (inf, None) if none."""
        o, d = self._indices_of(origin_node, destination_node)
        try:
            return self._walk_path(o, d)
        except nx.NetworkXNoPath:
            return np.inf, None

    def walk_edges(self, walk: tuple[float, list[int] | None], origin_node: int, destination_node: int):
        if walk[1] is None:
            raise nx.NetworkXNoPath(f"No walkable path {origin_node} -> {destination_node}")
        return self._walk_edges(walk[1])

    def route_walk(self, origin_node: int, destination_node: int) -> list[tuple[int, int, int, int]]:
        """Same as module-level route_walk() (whose path also doesn't depend on speed)."""
        o, d = self._indices_of(origin_node, destination_node)
        return self._walk_edges(self._walk_path(o, d)[1])

    def route_transit(
        self,
        origin_node: int,
        destination_node: int,
        departure_tick: int,
        wait_tolerance_min: float,
        mean_wait_min: float,
        timestep_s: float,
        std_exp_draw: float,
        walk_speed_mps: float,
        start_hour: int = 6,
        walk_time_weight: float = 1.0,
        walk: tuple[float, list[int] | None] | None = None,
    ) -> list[tuple[int, int, int, int]]:
        """
        Same decision sequence as module-level route_transit(). `walk` = (metres, node
        index path or None) from walk_distance(), if already computed. The boarding wait is
        std_exp_draw x mean_wait_min, where std_exp_draw is a standard-exponential draw
        made up front per agent — i.e. Exponential(mean=mean_wait_min), as before.
        """
        o, d = self._indices_of(origin_node, destination_node)
        walk_m, walk_path = walk if walk is not None else self.walk_distance(origin_node, destination_node)

        def _walk_fallback():
            if walk_path is None:
                raise nx.NetworkXNoPath(f"No walkable path {origin_node} -> {destination_node}")
            return self._walk_edges(walk_path)

        if not self.bands:
            return _walk_fallback()
        time_of_day_s = (start_hour * 3600 + departure_tick * timestep_s) % 86400
        b = next((i for i, (lo, hi) in enumerate(self.bands) if lo <= time_of_day_s < hi), None)
        if b is None:
            return _walk_fallback()

        mean_wait_s = mean_wait_min * 60.0
        if walk_path is not None and walk_time_weight * walk_m / walk_speed_mps <= mean_wait_s:
            return _walk_fallback()  # any route that boards costs > mean_wait_s: walking wins
        walk_cost = self.walk_len * (walk_time_weight / walk_speed_mps)
        transit_cost = self.transit_tt[b] + mean_wait_s
        csr = csr_matrix((np.minimum(walk_cost, transit_cost), self._indices, self._indptr), shape=self._shape)
        # The pure-walk route is feasible here too, so the best route costs no more than it.
        limit = walk_time_weight * walk_m / walk_speed_mps * (1.0 + 1e-9) + 1e-6 if walk_path is not None else np.inf
        found = self._search(csr, o, d, limit=limit)
        if found is None:
            return _walk_fallback()

        edges, first_transit, boarding = [], None, None
        route_s = 0.0  # unweighted travel time of the chosen route, excluding the wait
        for a, c in zip(found[1][:-1], found[1][1:]):
            j = self.pair_index[(a, c)]
            if transit_cost[j] < walk_cost[j]:
                key = int(self.transit_key[b, j])
                route_s += float(self.transit_tt[b, j])
                if first_transit is None:
                    first_transit, boarding = len(edges), (a, c, key)
            else:
                key = int(self.walk_key[j])
                route_s += float(self.walk_len[j]) / walk_speed_mps
            edges.append([int(self.nodes[a]), int(self.nodes[c]), key, 0])

        if first_transit is None:
            return [tuple(e) for e in edges]  # walking alone was the cheapest option this band
        if _headway_at(self.transit_freqs.get(boarding, []), time_of_day_s) is None:
            return _walk_fallback()  # boarding edge not in service at the exact departure time
        wait_s = float(std_exp_draw) * mean_wait_s
        if _gives_up_waiting(wait_s, wait_tolerance_min, walk_m if walk_path is not None else None,
                             walk_speed_mps, route_s):
            return _walk_fallback()
        edges[first_transit][3] = int(round(wait_s / timestep_s))
        return [tuple(e) for e in edges]


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
    router: "FastRouter | None" = None,
) -> "RouteDraws":
    """
    Mutates pool.route_edges and pool.route_index in-place for all agents, and returns
    the per-agent draws needed to plan the trips home (RouteDraws).
    Agents with no reachable path are marked active=False and their departure_ticks
    entry is set to -1 (the same "never travels" sentinel simulation.py uses for a
    failed travel-probability gate) so run()'s tick loop never reactivates them at
    their original departure tick -- without this, a departure tick still in the
    future would flip pool.active back to True, and the agent would then close out
    as a bogus zero-length, zero-exposure "completed" trip on that very tick (empty
    route_edges immediately satisfies route_index >= len(route_edges)), polluting
    trip_log/agent_modes with phantom entries even though no route was ever assigned.

    Routes are searched with FastRouter (built once per graph and cached, or passed in
    as `router`), which gives the same routes as route_walk()/route_transit().

    Walk or ride: under params.walk_choice == "distance", agent i walks the whole way
    when walk_draws[i] < walk_probability(purpose, shortest walking distance) — the JICA
    Nairobi diversion curves; under "fixed_share", when walk_draws[i] < walk_only_share.
    Everyone else plans a route that may ride transit. walk_draws and the boarding-wait
    draws are made up front, one per agent, so changing one behavioural parameter
    doesn't reshuffle the random draws of agents it doesn't affect (common random
    numbers across sensitivity runs).
    """
    router = router or FastRouter.for_graph(G)
    walk_draws = rng.random(pool.n)
    wait_draws = rng.standard_exponential(pool.n)
    # Drawn after the outbound draws, so adding them left those unchanged.
    return_wait_draws = rng.standard_exponential(pool.n)

    for i in range(pool.n):
        origin = int(origin_nodes[i])
        dest = int(destination_nodes[i])
        try:
            edges = plan_route(
                router, origin, dest, int(pool.trip_purpose[i]), int(departure_ticks[i]), params,
                float(walk_draws[i]), float(wait_draws[i]), float(pool.speed_mps[i]), start_hour, timestep_s,
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
            logger.warning("No path for agent %d (%d → %d): %s", i, origin, dest, exc)
            pool.active[i] = False
            departure_ticks[i] = -1
            continue
        start_route(pool, i, G, edges)
    return RouteDraws(walk=walk_draws, return_wait=return_wait_draws)


@dataclass
class RouteDraws:
    """Per-agent draws made by assign_routes() and reused to plan the trip home:
    the same walk draw (so the walk/ride choice is consistent with the outbound one,
    up to the small difference in distance) and a fresh boarding-wait draw."""
    walk: np.ndarray
    return_wait: np.ndarray


def start_route(pool: AgentPool, i: int, G: nx.MultiDiGraph, edges: list[tuple]) -> None:
    """Put agent i at the start of `edges` (does not set it active)."""
    pool.route_edges[i] = edges
    pool.route_index[i] = 0
    pool.progress[i] = 0.0
    if edges:
        u, v, key, wait_ticks = edges[0]
        _activate_edge(pool, i, G, u, v, key, wait_ticks)


def plan_route(
    router: "FastRouter",
    origin: int,
    dest: int,
    purpose_code: int,
    departure_tick: int,
    params: TravelBehaviorParams,
    walk_draw: float,
    std_exp_wait_draw: float,
    walk_speed_mps: float,
    start_hour: int,
    timestep_s: float,
) -> list[tuple]:
    """One trip's route: walk the whole way if walk_draw < P_walk (see assign_routes),
    otherwise the cheapest route that may ride transit at departure_tick."""
    from nairobi_heat_abm.model.simulation import PURPOSE_KEYS

    walk = router.walk_distance(origin, dest)
    if params.walk_choice == "distance":
        p_walk = walk_probability(params, PURPOSE_KEYS[purpose_code], walk[0])
    else:
        p_walk = params.walk_only_share
    if walk_draw < p_walk:
        return router.walk_edges(walk, origin, dest)
    return router.route_transit(
        origin, dest,
        departure_tick=departure_tick,
        wait_tolerance_min=params.transit_wait_tolerance_min,
        mean_wait_min=params.transit_mean_wait_min,
        timestep_s=timestep_s,
        std_exp_draw=std_exp_wait_draw,
        walk_speed_mps=walk_speed_mps,
        start_hour=start_hour,
        walk_time_weight=params.walk_time_weight,
        walk=walk,
    )
