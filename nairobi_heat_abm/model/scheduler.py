from __future__ import annotations

import numpy as np
import networkx as nx

from nairobi_heat_abm.data.heat import HeatSurface, sample_temperature
from nairobi_heat_abm.data.population import lonlat_to_rowcol
from nairobi_heat_abm.model.agent import AgentPool, MODE_WALK, MODE_WAIT, MODE_TRANSIT
from nairobi_heat_abm.model.routing import _activate_edge
from nairobi_heat_abm.model.segment_exposure import SegmentExposure


def tick(
    pool: AgentPool,
    G: nx.MultiDiGraph,
    surface: HeatSurface,
    sim_tick: int,
    timestep_s: float,
    start_hour: int,
    time_density: np.ndarray | None = None,
    time_density_transform=None,
    segment_exposure: SegmentExposure | None = None,
    utci_threshold_c: float = 26.0,
) -> None:
    """Advance all active agents by one timestep. Mutates pool in-place.

    Movement is continuous within a tick: an agent that reaches the end of its edge
    carries the rest of the tick onto the next edge, through as many edges as the time
    allows. It stops early only at the end of its route, or at a transit-boarding edge,
    where it waits at the stop for the rest of the tick (the boarding countdown then
    runs from the next tick). Each tick is split into pieces, one per edge (or stop) the
    agent spent time on, each with its share of the tick.

    Exposure is OUTDOOR only: pieces spent riding a transit edge (MODE_TRANSIT) add
    nothing; walking pieces (including access links) and waiting at a stop do. UTCI is
    sampled once per agent per tick, at its position at the end of the tick, and applied
    to the outdoor share of the tick:
        heat_exposure_degC_min += max(UTCI - utci_threshold_c, 0) × outdoor_share × timestep_minutes
        utci_degC_min          += UTCI × outdoor_share × timestep_minutes
        outdoor_min            += outdoor_share × timestep_minutes

    If `segment_exposure` is given, each walking piece's heat and minutes go to its
    directed edge and each waiting piece's to its stop node (edge_u of the transit edge
    to be boarded), so a 5 m edge crossed in 4 seconds gets 4 seconds, not a minute.

    If `time_density`/`time_density_transform` are given, the agent's outdoor minutes
    this tick are added to the grid cell of its end-of-tick position.
    """
    active = pool.active
    minutes = timestep_s / 60.0

    # Count down transit-boarding wait; once it elapses, switch to the edge's real mode
    # (the agent stays put at edge_u while waiting).
    waiting = active & (pool.mode == MODE_WAIT)
    if waiting.any():
        pool.wait_ticks_remaining[waiting] = np.maximum(pool.wait_ticks_remaining[waiting] - 1, 0)
        done_waiting = waiting & (pool.wait_ticks_remaining == 0)
        for i in np.where(done_waiting)[0]:
            edge_data = G[int(pool.edge_u[i])][int(pool.edge_v[i])][int(pool.edge_key[i])]
            pool.mode[i] = MODE_TRANSIT if edge_data.get("edge_type") == "transit" else MODE_WALK

    present = active.copy()  # agents that take part in this tick (some finish during it)
    outdoor_share = np.zeros(pool.n)

    # Edge pieces (u, v, key, agent, share) and stop pieces (node, agent, share).
    e_u: list[int] = []
    e_v: list[int] = []
    e_k: list[int] = []
    e_a: list[int] = []
    e_s: list[float] = []
    s_n: list[int] = []
    s_a: list[int] = []
    s_s: list[float] = []

    # Waiting the whole tick: a full-tick stop piece.
    still_waiting = active & (pool.mode == MODE_WAIT)
    outdoor_share[still_waiting] = 1.0

    # Moving agents that stay on their edge all tick (vectorised).
    moving = active & (pool.mode != MODE_WAIT)
    step = np.zeros(pool.n, dtype=np.float32)
    step[moving] = pool.edge_speed_mps[moving] * timestep_s / pool.edge_length[moving]
    finishing = moving & (pool.progress + step >= 1.0)
    staying = moving & ~finishing
    pool.progress[staying] += step[staying]
    staying_walk = staying & (pool.mode == MODE_WALK)
    outdoor_share[staying_walk] = 1.0

    # Agents that reach the end of their edge: carry the leftover time forward.
    for i in np.where(finishing)[0]:
        if pool.route_index[i] >= len(pool.route_edges[i]):  # empty route: nothing to walk
            pool.active[i] = False
            continue
        remaining = timestep_s
        while True:
            speed = float(pool.edge_speed_mps[i])
            length = float(pool.edge_length[i])
            needed = max(1.0 - float(pool.progress[i]), 0.0) * length / speed if speed > 0 else np.inf
            on_edge = min(needed, remaining)
            if on_edge > 0 and pool.mode[i] != MODE_TRANSIT:
                share = on_edge / timestep_s
                outdoor_share[i] += share
                e_u.append(int(pool.edge_u[i])); e_v.append(int(pool.edge_v[i])); e_k.append(int(pool.edge_key[i]))
                e_a.append(int(i)); e_s.append(share)
            if needed > remaining:
                pool.progress[i] += remaining * speed / length
                break
            remaining -= needed
            pool.route_index[i] += 1
            if pool.route_index[i] >= len(pool.route_edges[i]):
                pool.progress[i] = 1.0  # at the destination (edge_v)
                pool.active[i] = False
                break
            u, v, key, wait_ticks = pool.route_edges[i][pool.route_index[i]]
            _activate_edge(pool, i, G, u, v, key, wait_ticks)
            pool.progress[i] = 0.0
            if pool.mode[i] == MODE_WAIT:  # wait at the stop for the rest of this tick
                share = remaining / timestep_s
                # The countdown (top of tick()) lets the agent board in the tick its
                # wait_ticks_remaining reaches 0, so it waits share + (wait_ticks - 1)
                # ticks. Arriving in the first half of a tick adds one more tick, which
                # keeps the realised wait within half a tick of wait_ticks on average.
                if share < 0.5:
                    pool.wait_ticks_remaining[i] += 1
                if share > 0:
                    outdoor_share[i] += share
                    s_n.append(int(pool.edge_u[i])); s_a.append(int(i)); s_s.append(share)
                break
            if remaining <= 0:
                break

    outdoor = present & (outdoor_share > 0)
    if not outdoor.any():
        return
    idx = np.flatnonzero(outdoor)

    # Temperature at each outdoor agent's end-of-tick position.
    hour = int(start_hour + sim_tick * timestep_s // 3600)
    u_lons = np.array([G.nodes[u]["x"] for u in pool.edge_u[idx]])
    u_lats = np.array([G.nodes[u]["y"] for u in pool.edge_u[idx]])
    v_lons = np.array([G.nodes[v]["x"] for v in pool.edge_v[idx]])
    v_lats = np.array([G.nodes[v]["y"] for v in pool.edge_v[idx]])
    p = np.where(pool.mode[idx] == MODE_WAIT, 0.0, np.clip(pool.progress[idx], 0.0, 1.0))
    lons = u_lons + p * (v_lons - u_lons)
    lats = u_lats + p * (v_lats - u_lats)
    temps = np.full(pool.n, np.nan)
    temps[idx] = sample_temperature(surface, lons, lats, hour)

    excess = np.maximum(temps - utci_threshold_c, 0.0)  # NaN stays NaN
    out_min = outdoor_share[idx] * minutes
    pool.heat_exposure_degC_min[idx] += (excess[idx] * out_min).astype(np.float32)
    pool.utci_degC_min[idx] += (temps[idx] * out_min).astype(np.float32)
    pool.outdoor_min[idx] += out_min.astype(np.float32)

    if segment_exposure is not None:
        # Whole-tick pieces of agents that never changed edge this tick.
        sw = np.flatnonzero(staying_walk)
        wt = np.flatnonzero(still_waiting)
        eu = np.concatenate([pool.edge_u[sw], np.asarray(e_u, dtype=np.int64)])
        ev = np.concatenate([pool.edge_v[sw], np.asarray(e_v, dtype=np.int64)])
        ek = np.concatenate([pool.edge_key[sw].astype(np.int64), np.asarray(e_k, dtype=np.int64)])
        ea = np.concatenate([sw, np.asarray(e_a, dtype=np.int64)])
        es = np.concatenate([np.ones(len(sw)), np.asarray(e_s, dtype=float)])
        segment_exposure.add_edges(eu, ev, ek, excess[ea] * es * minutes, es * minutes, agents=ea)
        sn = np.concatenate([pool.edge_u[wt], np.asarray(s_n, dtype=np.int64)])
        sa = np.concatenate([wt, np.asarray(s_a, dtype=np.int64)])
        ss = np.concatenate([np.ones(len(wt)), np.asarray(s_s, dtype=float)])
        segment_exposure.add_stops(sn, excess[sa] * ss * minutes, ss * minutes, agents=sa)

    if time_density is not None:
        rows, cols = lonlat_to_rowcol(time_density_transform, lons, lats, time_density.shape)
        np.add.at(time_density, (rows, cols), out_min)
