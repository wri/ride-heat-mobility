from __future__ import annotations

import numpy as np
import networkx as nx

from nairobi_heat_abm.data.heat import HeatSurface, sample_temperature
from nairobi_heat_abm.data.population import lonlat_to_rowcol
from nairobi_heat_abm.model.agent import AgentPool, MODE_WALK, MODE_WAIT, MODE_TRANSIT
from nairobi_heat_abm.model.routing import _activate_edge


def tick(
    pool: AgentPool,
    G: nx.MultiDiGraph,
    surface: HeatSurface,
    sim_tick: int,
    timestep_s: float,
    start_hour: int,
    time_density: np.ndarray | None = None,
    time_density_transform=None,
) -> None:
    """Advance all active agents by one timestep. Mutates pool in-place.

    If `time_density`/`time_density_transform` are given, also accumulates
    person-minutes spent in each grid cell this tick (mutated in-place too) — reuses
    the same interpolated agent positions computed below for heat sampling, so it's
    "where people actually are, weighted by how long they're there," not just spawn
    or destination points.

    Both heat_exposure_degC_min and time_density are OUTDOOR exposure only: an agent
    riding inside a matatu (MODE_TRANSIT) is excluded from both, since they aren't
    exposed to ambient heat the way a pedestrian walking or waiting at a stop is.
    Walking (including the access-link legs to/from a stop) and MODE_WAIT (standing at
    a stop before boarding) both still count — only the in-vehicle segment is skipped.
    """
    active = pool.active

    # Count down transit-boarding wait; once it elapses, switch to the edge's real mode
    # (the agent stays put at edge_u throughout — progress is frozen below since it's
    # excluded from `moving` while mode==MODE_WAIT).
    waiting = active & (pool.mode == MODE_WAIT)
    if waiting.any():
        pool.wait_ticks_remaining[waiting] = np.maximum(pool.wait_ticks_remaining[waiting] - 1, 0)
        done_waiting = waiting & (pool.wait_ticks_remaining == 0)
        for i in np.where(done_waiting)[0]:
            edge_data = G[int(pool.edge_u[i])][int(pool.edge_v[i])][int(pool.edge_key[i])]
            pool.mode[i] = MODE_TRANSIT if edge_data.get("edge_type") == "transit" else MODE_WALK

    # Advance progress for agents that are moving (not waiting)
    moving = active & (pool.mode != MODE_WAIT)
    pool.progress[moving] += pool.edge_speed_mps[moving] * timestep_s / pool.edge_length[moving]

    # Edge transition for agents that finished current edge
    finished_edge = active & (pool.progress >= 1.0)
    for i in np.where(finished_edge)[0]:
        pool.progress[i] = 0.0
        pool.route_index[i] += 1
        if pool.route_index[i] >= len(pool.route_edges[i]):
            pool.active[i] = False
            continue
        u, v, key, wait_ticks = pool.route_edges[i][pool.route_index[i]]
        _activate_edge(pool, i, G, u, v, key, wait_ticks)

    # Heat accumulation (vectorised) — outdoor agents only (see docstring above).
    active = pool.active  # re-read after mutations
    outdoor = active & (pool.mode != MODE_TRANSIT)
    if not outdoor.any():
        return

    hour = int(start_hour + sim_tick * timestep_s // 3600)

    u_lons = np.array([G.nodes[u]["x"] for u in pool.edge_u[outdoor]])
    u_lats = np.array([G.nodes[u]["y"] for u in pool.edge_u[outdoor]])
    v_lons = np.array([G.nodes[v]["x"] for v in pool.edge_v[outdoor]])
    v_lats = np.array([G.nodes[v]["y"] for v in pool.edge_v[outdoor]])

    p = pool.progress[outdoor]
    lons = u_lons + p * (v_lons - u_lons)
    lats = u_lats + p * (v_lats - u_lats)

    temps = sample_temperature(surface, lons, lats, hour)
    pool.heat_exposure_degC_min[outdoor] += temps * (timestep_s / 60.0)

    if time_density is not None:
        rows, cols = lonlat_to_rowcol(time_density_transform, lons, lats, time_density.shape)
        np.add.at(time_density, (rows, cols), timestep_s / 60.0)
