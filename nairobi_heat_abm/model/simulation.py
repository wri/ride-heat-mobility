from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import osmnx as ox

from nairobi_heat_abm.data.amenities import load_amenity_index
from nairobi_heat_abm.data.heat import HeatSurface
from nairobi_heat_abm.data.population import load_population_raster, sample_spawn_nodes
from nairobi_heat_abm.model.agent import AgentPool, TravelBehaviorParams
from nairobi_heat_abm.model.routing import assign_routes
from nairobi_heat_abm.model.scheduler import tick


@dataclass
class SimulationParams:
    bbox: tuple[float, float, float, float]  # (south, west, north, east)
    n_agents: int
    start_hour: int
    end_hour: int
    timestep_s: float
    seed: int
    behavior: TravelBehaviorParams
    graph_cache_path: Path
    amenity_cache_path: Path
    worldpop_tif_path: Path
    heat_surface: HeatSurface


@dataclass
class ScenarioResult:
    params: SimulationParams
    agent_exposure_degC_min: np.ndarray  # float32, shape (n_agents,)
    agent_modes: np.ndarray              # uint8,   shape (n_agents,)
    agent_purposes: np.ndarray           # uint8,   shape (n_agents,)
    agent_n_trips: np.ndarray            # int32,   shape (n_agents,)
    trip_log: list[dict]
    elapsed_seconds: float


def run(params: SimulationParams) -> ScenarioResult:
    """
    Pure function — no global state. Safe to call from ProcessPoolExecutor workers.
    """
    rng = np.random.default_rng(params.seed)
    G = ox.load_graphml(params.graph_cache_path)
    amenities = load_amenity_index(params.amenity_cache_path)
    density, transform = load_population_raster(params.worldpop_tif_path, params.bbox)

    spawn_nodes = sample_spawn_nodes(density, transform, G, params.n_agents, rng)
    n_trips = _draw_trip_counts(params.behavior, params.n_agents, rng)
    departure_ticks = _draw_departure_ticks(
        params.behavior, params.n_agents, params.start_hour,
        params.end_hour, params.timestep_s, rng,
    )
    purposes = _draw_purposes(params.behavior, params.n_agents, rng)
    dest_nodes = _draw_destinations(amenities, purposes, spawn_nodes, G, rng)

    pool = AgentPool.create(params.n_agents)
    pool.trip_purpose[:] = purposes
    pool.speed_mps[:] = rng.normal(
        params.behavior.walk_speed_mean_mps,
        params.behavior.walk_speed_std_mps,
        params.n_agents,
    ).clip(0.3, 3.0).astype(np.float32)

    assign_routes(pool, G, spawn_nodes, dest_nodes, departure_ticks, params.behavior, rng)

    n_ticks = int((params.end_hour - params.start_hour) * 3600 / params.timestep_s)
    trip_log: list[dict] = []
    t0 = time.perf_counter()

    for tick_i in range(n_ticks):
        departing = (departure_ticks == tick_i) & ~pool.active
        pool.active[departing] = True

        active_before_tick = pool.active.copy()
        tick(pool, G, params.heat_surface, tick_i, params.timestep_s, params.start_hour)

        # Only agents that transitioned active -> inactive *this* tick just finished;
        # otherwise a completed agent (route_index stays > 0) gets re-logged every
        # remaining tick of the simulation.
        just_finished = active_before_tick & ~pool.active
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


def _draw_trip_counts(behavior: TravelBehaviorParams, n: int, rng: np.random.Generator) -> np.ndarray:
    if behavior.trip_rate_distribution == "poisson":
        counts = rng.poisson(behavior.trip_rate_mean, n)
    else:
        counts = np.round(rng.normal(behavior.trip_rate_mean, behavior.trip_rate_std, n))
    return np.clip(counts, 1, None).astype(np.int32)


def _draw_departure_ticks(
    behavior: TravelBehaviorParams,
    n: int,
    start_hour: int,
    end_hour: int,
    timestep_s: float,
    rng: np.random.Generator,
) -> np.ndarray:
    n_ticks = int((end_hour - start_hour) * 3600 / timestep_s)

    if behavior.departure_profile == "uniform":
        return rng.integers(0, n_ticks, n).astype(np.int32)

    # Bimodal: two Gaussian peaks + off-peak uniform
    p1 = behavior.peak1_weight
    p2 = behavior.peak2_weight
    p_off = max(0.0, 1.0 - p1 - p2)
    which = rng.choice(3, size=n, p=[p1, p2, p_off])

    std_ticks = int(0.5 * 3600 / timestep_s)  # 30-min std dev

    def _hour_to_tick(h: float) -> float:
        return (h - start_hour) * 3600 / timestep_s

    raw = np.where(
        which == 0,
        rng.normal(_hour_to_tick(behavior.peak1_hour), std_ticks, n),
        np.where(
            which == 1,
            rng.normal(_hour_to_tick(behavior.peak2_hour), std_ticks, n),
            rng.integers(0, n_ticks, n).astype(float),
        ),
    )
    return np.clip(np.round(raw), 0, n_ticks - 1).astype(np.int32)


# Maps PURPOSE_* codes → amenity category key (None = any graph node)
_PURPOSE_AMENITY: dict[int, str | None] = {
    0: "work",
    1: "school",
    2: "shop",
    3: "other",
}


def _haversine_m(lon1: float, lat1: float, lon2: np.ndarray, lat2: np.ndarray) -> np.ndarray:
    """Great-circle distance in metres from a single point to an array of points."""
    R = 6_371_000.0
    lon1r, lat1r = np.radians(lon1), np.radians(lat1)
    lon2r, lat2r = np.radians(lon2), np.radians(lat2)
    dlon = lon2r - lon1r
    dlat = lat2r - lat1r
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2
    return R * 2.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _draw_destinations(
    amenities: dict[str, list[int]],
    purposes: np.ndarray,
    origin_nodes: np.ndarray,
    G,
    rng: np.random.Generator,
    min_distance_m: float = 25.0,
) -> np.ndarray:
    """
    Draw one destination per agent from the OSM amenity category matching its trip
    purpose ("work" draws from offices/industrial-commercial land plus shop/school/
    health locations, since those also employ workers — see `_add_work_overlap` in
    data/amenities.py). Falls back to any graph node if a category's amenity pool is
    empty (e.g. an OSM fetch failure). Candidates are weighted by inverse distance
    from the agent's origin node, so nearby destinations are preferred over far ones;
    the origin node itself is excluded to avoid zero-length trips.
    """
    all_nodes = np.array(list(G.nodes()), dtype=np.int64)
    all_lons = np.array([G.nodes[int(n)]["x"] for n in all_nodes])
    all_lats = np.array([G.nodes[int(n)]["y"] for n in all_nodes])
    dest_nodes = np.empty(len(purposes), dtype=np.int64)

    for purpose_code, amenity_key in _PURPOSE_AMENITY.items():
        mask = purposes == purpose_code
        agent_idx = np.where(mask)[0]
        if len(agent_idx) == 0:
            continue

        candidates = np.array(amenities.get(amenity_key, []), dtype=np.int64) if amenity_key else np.array([], dtype=np.int64)
        if len(candidates) > 0:
            pool = candidates
            pool_lons = np.array([G.nodes[int(n)]["x"] for n in pool])
            pool_lats = np.array([G.nodes[int(n)]["y"] for n in pool])
        else:
            pool, pool_lons, pool_lats = all_nodes, all_lons, all_lats

        for i in agent_idx:
            origin = int(origin_nodes[i])
            o_lon, o_lat = G.nodes[origin]["x"], G.nodes[origin]["y"]

            dists = _haversine_m(o_lon, o_lat, pool_lons, pool_lats)
            weights = 1.0 / np.maximum(dists, min_distance_m)
            weights[pool == origin] = 0.0  # exclude self: avoid zero-length trips

            total = weights.sum()
            if total <= 0.0:
                # Only candidate is the origin itself (e.g. single-node amenity pool) — allow it.
                weights = np.ones_like(weights)
                total = weights.sum()

            dest_nodes[i] = pool[rng.choice(len(pool), p=weights / total)]

    return dest_nodes


def _draw_purposes(behavior: TravelBehaviorParams, n: int, rng: np.random.Generator) -> np.ndarray:
    keys = ["work", "school", "market", "other"]
    weights = [behavior.purpose_weights.get(k, 0.0) for k in keys]
    return rng.choice(len(keys), size=n, p=weights).astype(np.uint8)
