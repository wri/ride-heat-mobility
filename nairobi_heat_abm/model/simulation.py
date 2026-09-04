from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import osmnx as ox

from nairobi_heat_abm.data.amenities import load_amenity_index
from nairobi_heat_abm.data.demographics import (
    assign_ses, draw_age_gender, draw_age_gender_spatial, load_informal_settlement_boundaries,
)
from nairobi_heat_abm.data.heat import HeatSurface
from nairobi_heat_abm.data.population import load_population_raster, load_population_rasters, sample_spawn_nodes
from nairobi_heat_abm.model.agent import (
    AgentPool, DemographicParams, MODE_TRANSIT, MODE_WALK, ParamModifier, TravelBehaviorParams,
)
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
    demographics: DemographicParams | None = None  # None = no age/gender/SES segmentation


@dataclass
class ScenarioResult:
    params: SimulationParams
    agent_exposure_degC_min: np.ndarray  # float32, shape (n_agents,)
    agent_modes: np.ndarray              # uint8,   shape (n_agents,)
    agent_purposes: np.ndarray           # uint8,   shape (n_agents,)
    agent_n_trips: np.ndarray            # int32,   shape (n_agents,)
    trip_log: list[dict]
    elapsed_seconds: float
    # uint8, shape (n_agents,) — zero-filled (AGE_CHILD/GENDER_MALE/SES_FORMAL) when
    # params.demographics was None, i.e. demographics weren't modeled for this scenario.
    agent_age_group: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.uint8))
    agent_gender: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.uint8))
    agent_ses: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.uint8))


def _trip_mode(route_edges: list[tuple], G) -> int:
    """
    Summary mode for a (possibly-completed) trip: MODE_TRANSIT if any edge in the
    route is an actual transit ride, else MODE_WALK (including an empty/no-path
    route). This is deliberately NOT pool.mode[i] itself, which reflects only the
    CURRENT edge's mode moment-to-moment — every transit trip ends with a
    walk-to-destination leg, so pool.mode[i] at trip completion is always MODE_WALK
    even for a trip that rode transit most of the way. rdm/analysis.py::compute_outcomes
    relies on this walk-vs-transit split (via ScenarioResult.agent_modes) to compare
    exposure by mode, so it needs to reflect the whole trip, not just its last edge.
    """
    for u, v, key, _ in route_edges:
        if G[u][v][key].get("edge_type") == "transit":
            return MODE_TRANSIT
    return MODE_WALK


def run(params: SimulationParams) -> ScenarioResult:
    """
    Pure function — no global state. Safe to call from ProcessPoolExecutor workers.
    """
    rng = np.random.default_rng(params.seed)
    G = ox.load_graphml(params.graph_cache_path)
    amenities = load_amenity_index(params.amenity_cache_path)

    use_spatial_demographics = (
        params.demographics is not None and params.demographics.population_raster_paths is not None
    )
    if use_spatial_demographics:
        # "total" is both the spawn-density surface and the denominator for the other
        # groups' local shares — supersedes worldpop_tif_path for this run.
        rasters, transform = load_population_rasters(params.demographics.population_raster_paths, params.bbox)
        density = rasters["total"]
    else:
        density, transform = load_population_raster(params.worldpop_tif_path, params.bbox)

    spawn_nodes, spawn_rows, spawn_cols = sample_spawn_nodes(density, transform, G, params.n_agents, rng)

    age_group = np.zeros(params.n_agents, dtype=np.uint8)
    gender = np.zeros(params.n_agents, dtype=np.uint8)
    ses = np.zeros(params.n_agents, dtype=np.uint8)

    if params.demographics is None:
        n_trips = _draw_trip_counts(params.behavior, params.n_agents, rng)
        departure_ticks = _draw_departure_ticks(
            params.behavior, params.n_agents, params.start_hour,
            params.end_hour, params.timestep_s, rng,
        )
        purposes = _draw_purposes(params.behavior, params.n_agents, rng)
    else:
        demo = params.demographics
        if use_spatial_demographics:
            age_group, gender = draw_age_gender_spatial(rasters, spawn_rows, spawn_cols, rng)
        else:
            age_group, gender = draw_age_gender(demo, params.n_agents, rng)
        boundary_gdf = load_informal_settlement_boundaries(demo.informal_settlement_path)
        ses = assign_ses(spawn_nodes, G, boundary_gdf)

        n_trips = np.empty(params.n_agents, dtype=np.int32)
        departure_ticks = np.empty(params.n_agents, dtype=np.int32)
        purposes = np.empty(params.n_agents, dtype=np.uint8)

        segments = sorted(set(zip(age_group.tolist(), gender.tolist(), ses.tolist())))
        for age_code, gender_code, ses_code in segments:
            seg_idx = np.where(
                (age_group == age_code) & (gender == gender_code) & (ses == ses_code)
            )[0]
            effective = _effective_behavior(params.behavior, demo, age_code, gender_code, ses_code)

            n_trips[seg_idx] = _draw_trip_counts(effective, len(seg_idx), rng)
            departure_ticks[seg_idx] = _draw_departure_ticks(
                effective, len(seg_idx), params.start_hour, params.end_hour, params.timestep_s, rng,
            )
            purposes[seg_idx] = _draw_purposes(effective, len(seg_idx), rng)

    dest_nodes = _draw_destinations(amenities, purposes, spawn_nodes, G, rng)

    pool = AgentPool.create(params.n_agents)
    pool.trip_purpose[:] = purposes
    pool.age_group[:] = age_group
    pool.gender[:] = gender
    pool.ses[:] = ses
    pool.speed_mps[:] = rng.normal(
        params.behavior.walk_speed_mean_mps,
        params.behavior.walk_speed_std_mps,
        params.n_agents,
    ).clip(0.3, 3.0).astype(np.float32)

    assign_routes(
        pool, G, spawn_nodes, dest_nodes, departure_ticks, params.behavior, rng,
        params.start_hour, params.timestep_s,
    )

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
                "mode": _trip_mode(pool.route_edges[i], G),
                "heat_degC_min": float(pool.heat_exposure_degC_min[i]),
                "age_group": int(pool.age_group[i]),
                "gender": int(pool.gender[i]),
                "ses": int(pool.ses[i]),
            })

    agent_modes = np.array([_trip_mode(edges, G) for edges in pool.route_edges], dtype=np.uint8)

    return ScenarioResult(
        params=params,
        agent_exposure_degC_min=pool.heat_exposure_degC_min.copy(),
        agent_modes=agent_modes,
        agent_purposes=pool.trip_purpose.copy(),
        agent_n_trips=n_trips,
        trip_log=trip_log,
        elapsed_seconds=time.perf_counter() - t0,
        agent_age_group=pool.age_group.copy(),
        agent_gender=pool.gender.copy(),
        agent_ses=pool.ses.copy(),
    )


def _effective_behavior(
    base: TravelBehaviorParams,
    demo: DemographicParams,
    age_code: int,
    gender_code: int,
    ses_code: int,
) -> TravelBehaviorParams:
    """
    Combines base with the (independent, multiplicative) modifiers for one demographic
    segment. Missing modifiers default to ParamModifier() (no-op). purpose_weights are
    renormalized automatically by TravelBehaviorParams.__post_init__ via dataclasses.replace.
    """
    m_age = demo.age_modifiers.get(age_code, ParamModifier())
    m_gender = demo.gender_modifiers.get(gender_code, ParamModifier())
    m_ses = demo.ses_modifiers.get(ses_code, ParamModifier())

    trip_rate_mean = base.trip_rate_mean * m_age.trip_rate_mean_mult * m_gender.trip_rate_mean_mult * m_ses.trip_rate_mean_mult
    trip_rate_std = base.trip_rate_std * m_age.trip_rate_std_mult * m_gender.trip_rate_std_mult * m_ses.trip_rate_std_mult

    purpose_weights = dict(base.purpose_weights)
    for modifier in (m_age, m_gender, m_ses):
        for purpose, mult in modifier.purpose_weight_mult.items():
            purpose_weights[purpose] = purpose_weights.get(purpose, 0.0) * mult

    return dataclasses.replace(
        base,
        trip_rate_mean=trip_rate_mean,
        trip_rate_std=trip_rate_std,
        purpose_weights=purpose_weights,
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
