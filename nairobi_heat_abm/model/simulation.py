from __future__ import annotations

import dataclasses
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from scipy.special import ndtr

from nairobi_heat_abm.data.amenities import load_amenity_index
from nairobi_heat_abm.data.demographics import (
    assign_ses, draw_age_gender, draw_age_gender_spatial, load_informal_settlement_boundaries,
)
from nairobi_heat_abm.data.heat import HeatSurface
from nairobi_heat_abm.data.population import (
    grid_transform_for_bbox, load_population_raster, load_population_rasters, sample_spawn_nodes,
)
from nairobi_heat_abm.model.agent import (
    AgentPool, DemographicParams, MODE_TRANSIT, MODE_WALK, ParamModifier, TravelBehaviorParams,
    return_departure_hour,
)
from nairobi_heat_abm.model.routing import FastRouter, assign_routes, plan_route, start_route
from nairobi_heat_abm.model.scheduler import tick
from nairobi_heat_abm.model.segment_exposure import SegmentExposure

logger = logging.getLogger(__name__)


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
    # Shape (rows, cols) of the person-minutes-spent grid returned as
    # ScenarioResult.time_density. Purely a visualization resolution knob — has no
    # effect on simulation behavior/results, unlike every other field here.
    time_density_grid_shape: tuple[int, int] = (200, 200)
    # Heat exposure counts UTCI degrees above this value: each outdoor minute adds
    # max(UTCI - utci_threshold_c, 0) °C·min. 26 °C is where the UTCI assessment
    # scale's "moderate heat stress" category begins.
    utci_threshold_c: float = 26.0


@dataclass
class ScenarioResult:
    params: SimulationParams
    agent_exposure_degC_min: np.ndarray  # float32, shape (n_agents,) — °C·min of UTCI above
                                         #   params.utci_threshold_c, whole day, both legs
    agent_modes: np.ndarray              # uint8,   shape (n_agents,) — OUTBOUND trip's mode
    agent_purposes: np.ndarray           # uint8,   shape (n_agents,)
    agent_n_trips: np.ndarray            # int32,   shape (n_agents,)
    trip_log: list[dict]
    elapsed_seconds: float
    # uint8, shape (n_agents,) — zero-filled (AGE_CHILD/GENDER_MALE/SES_FORMAL) when
    # params.demographics was None, i.e. demographics weren't modeled for this scenario.
    agent_age_group: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.uint8))
    agent_gender: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.uint8))
    agent_ses: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.uint8))
    # Person-minutes accumulated per grid cell over the whole run — "where the most
    # people spent the most time," not just where they started or ended up. OUTDOOR
    # only: excludes in-vehicle transit riding (MODE_TRANSIT), so this reflects walking
    # (including access-link legs to/from a stop) and waiting at a stop, not time spent
    # inside a matatu. Shape (rows, cols) per params.time_density_grid_shape;
    # zero-filled (empty) when a hand-built ScenarioResult doesn't set it (e.g. older
    # test/notebook fixtures).
    time_density: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    # rasterio.Affine mapping time_density's (row, col) to lon/lat — from
    # data/population.py::grid_transform_for_bbox. None when time_density is empty.
    time_density_transform: object = None
    # Each agent's home (spawn) graph node and its lon/lat — the agent's actual origin in
    # this run, for joining exposure to neighbourhood/SES layers. Empty when a
    # hand-built ScenarioResult doesn't set it.
    agent_home_node: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    agent_home_lon: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    agent_home_lat: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    # Outdoor exposure attributed to where it happened (see model/segment_exposure.py):
    # segment_exposure = one row per directed graph edge walked (u, v, key,
    # heat_degC_min, person_min); stop_exposure = one row per stop waited at (node,
    # heat_degC_min, person_min). data/export.py turns these into GIS layers.
    segment_exposure: pd.DataFrame = field(default_factory=pd.DataFrame)
    stop_exposure: pd.DataFrame = field(default_factory=pd.DataFrame)
    # float32, shape (n_agents,) — minutes each agent spent outdoors (walking or waiting),
    # i.e. the time over which agent_exposure_degC_min accumulated.
    agent_outdoor_min: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    # float32, shape (n_agents,) — planned walking time from home to the first boarding
    # stop (street + access-link edges before the first transit ride, at the agent's own
    # speed), NaN for trips that don't ride transit. The model's counterpart of the WRI
    # rider survey's Q8 access time; see calibration.py.
    agent_access_walk_min: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    # float32, shape (n_agents,) — door-to-door trip duration (departure to arrival), NaN
    # for agents that never departed or hadn't arrived by end_hour.
    agent_trip_min: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    # float32, shape (n_agents,) — planned minutes from boarding the first vehicle to
    # leaving the last (rides + transfer walks), NaN if no transit. Compared with the
    # survey's Q11 trip duration in calibration.py.
    agent_ride_min: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    # Return trips (TravelBehaviorParams.return_trips). Per agent:
    # - agent_outbound_exposure_degC_min: exposure on the trip out (the rest of
    #   agent_exposure_degC_min was picked up on the way home);
    # - agent_return_departure_hour: clock hour the trip home was due to leave (NaN if
    #   the agent never arrived, or return trips are off); it may be past end_hour, in
    #   which case the trip home isn't simulated;
    # - agent_return_modes: the trip home's mode (MODE_WALK/MODE_TRANSIT), NO_RETURN
    #   (255) if it never started;
    # - agent_returned: True once the agent is home again;
    # - agent_return_trip_min: door-to-door minutes of the trip home (NaN if unfinished).
    agent_outbound_exposure_degC_min: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    agent_return_departure_hour: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    agent_return_modes: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.uint8))
    agent_returned: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    agent_return_trip_min: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    # float32, shape (n_agents,) — raw UTCI x outdoor minutes (no threshold); divided by
    # agent_outdoor_min it gives the mean UTCI the agent experienced outdoors.
    agent_utci_degC_min: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))


NO_RETURN = 255  # agent_return_modes value for agents whose trip home never started


@dataclass
class SimulationContext:
    """
    The inputs of run() that no behavioural parameter changes — graph, router, amenity
    index, population rasters — loaded once and shared across runs (load_context()), so
    a batch of runs doesn't reload a ~3 GB graph each time. Only valid for runs with the
    same graph_cache_path, amenity_cache_path, population rasters and bbox as the params
    it was loaded with.
    """
    G: object
    amenities: dict
    density: np.ndarray
    transform: object
    rasters: dict | None  # per-group rasters when spatial demographics are used
    router: FastRouter


def _uses_spatial_demographics(params: SimulationParams) -> bool:
    return params.demographics is not None and params.demographics.population_raster_paths is not None


def load_context(params: SimulationParams, G=None) -> SimulationContext:
    """Load everything run() needs besides params. Pass an already-loaded graph as G
    (e.g. the notebook's) to avoid holding two ~3 GB copies in memory."""
    if G is None:
        G = ox.load_graphml(params.graph_cache_path)
    amenities = load_amenity_index(params.amenity_cache_path)
    if _uses_spatial_demographics(params):
        # "total" is both the spawn-density surface and the denominator for the other
        # groups' local shares — supersedes worldpop_tif_path for this run.
        rasters, transform = load_population_rasters(params.demographics.population_raster_paths, params.bbox)
        density = rasters["total"]
    else:
        rasters = None
        density, transform = load_population_raster(params.worldpop_tif_path, params.bbox)
    return SimulationContext(G=G, amenities=amenities, density=density, transform=transform,
                             rasters=rasters, router=FastRouter.for_graph(G))


# Independent random streams, one per model component, spawned from params.seed. Runs
# that share a seed but differ in one behavioural parameter then share every draw that
# parameter doesn't touch (same homes, same speeds' z-scores, same wait draws, ...) —
# common random numbers, which keeps sensitivity-analysis differences from being
# swamped by reshuffled randomness.
# New streams go at the END: SeedSequence.spawn(n)[i] doesn't depend on n, so the
# existing streams keep their draws.
_RNG_STREAMS = ("spawn", "demographics", "trips", "purposes", "departures", "gate", "destinations", "speed", "routes",
                "returns")


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


def run(params: SimulationParams, context: SimulationContext | None = None) -> ScenarioResult:
    """
    Pure function — no global state. Safe to call from ProcessPoolExecutor workers.
    `context` (from load_context()) skips reloading the graph, amenities and rasters;
    without it they are loaded here.
    """
    ctx = context or load_context(params)
    G, amenities, rasters, density, transform = ctx.G, ctx.amenities, ctx.rasters, ctx.density, ctx.transform
    use_spatial_demographics = _uses_spatial_demographics(params)
    rngs = dict(zip(_RNG_STREAMS, (np.random.default_rng(s) for s in np.random.SeedSequence(params.seed).spawn(len(_RNG_STREAMS)))))

    spawn_nodes, spawn_rows, spawn_cols = sample_spawn_nodes(density, transform, G, params.n_agents, rngs["spawn"])

    age_group = np.zeros(params.n_agents, dtype=np.uint8)
    gender = np.zeros(params.n_agents, dtype=np.uint8)
    ses = np.zeros(params.n_agents, dtype=np.uint8)

    if params.demographics is None:
        n_trips = _draw_trip_counts(params.behavior, params.n_agents, rngs["trips"])
        purposes = _draw_purposes(params.behavior, params.n_agents, rngs["purposes"])
        departure_ticks = _draw_departure_ticks(
            params.behavior, purposes, params.start_hour,
            params.end_hour, params.timestep_s, rngs["departures"],
        )

        travels = _draw_travel_gate(params.behavior, purposes, rngs["gate"])
        departure_ticks[~travels] = -1  # sentinel: never matches a tick_i, agent stays inactive
        n_trips[~travels] = 0
    else:
        demo = params.demographics
        if use_spatial_demographics:
            age_group, gender = draw_age_gender_spatial(rasters, spawn_rows, spawn_cols, rngs["demographics"])
        else:
            age_group, gender = draw_age_gender(demo, params.n_agents, rngs["demographics"])
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

            n_trips[seg_idx] = _draw_trip_counts(effective, len(seg_idx), rngs["trips"])
            purposes[seg_idx] = _draw_purposes(effective, len(seg_idx), rngs["purposes"])
            departure_ticks[seg_idx] = _draw_departure_ticks(
                effective, purposes[seg_idx], params.start_hour, params.end_hour, params.timestep_s,
                rngs["departures"],
            )

            travels = _draw_travel_gate(effective, purposes[seg_idx], rngs["gate"])
            seg_departure_ticks = departure_ticks[seg_idx]
            seg_departure_ticks[~travels] = -1
            departure_ticks[seg_idx] = seg_departure_ticks
            seg_n_trips = n_trips[seg_idx]
            seg_n_trips[~travels] = 0
            n_trips[seg_idx] = seg_n_trips

    dest_nodes = _draw_destinations(
        amenities, purposes, spawn_nodes, G, rngs["destinations"],
        distance_decay=params.behavior.destination_distance_decay,
    )

    pool = AgentPool.create(params.n_agents)
    pool.trip_purpose[:] = purposes
    pool.age_group[:] = age_group
    pool.gender[:] = gender
    pool.ses[:] = ses
    speed_z = rngs["speed"].standard_normal(params.n_agents)
    pool.speed_mps[:] = (
        params.behavior.walk_speed_mean_mps + params.behavior.walk_speed_std_mps * speed_z
    ).clip(0.3, 3.0).astype(np.float32)

    draws = assign_routes(
        pool, G, spawn_nodes, dest_nodes, departure_ticks, params.behavior, rngs["routes"],
        params.start_hour, params.timestep_s, router=ctx.router,
    )
    return_z = rngs["returns"].standard_normal(params.n_agents)

    # Outbound statistics come from the planned outbound routes, before the trips home
    # replace them in pool.route_edges.
    access_walk_min, ride_min = _transit_trip_parts(pool, G)
    agent_modes = np.array([_trip_mode(edges, G) for edges in pool.route_edges], dtype=np.uint8)
    trip_min = np.full(params.n_agents, np.nan, dtype=np.float32)

    on_return_leg = np.zeros(params.n_agents, dtype=bool)
    return_ticks = np.full(params.n_agents, -1, dtype=np.int64)
    return_hour = np.full(params.n_agents, np.nan, dtype=np.float32)
    return_modes = np.full(params.n_agents, NO_RETURN, dtype=np.uint8)
    returned = np.zeros(params.n_agents, dtype=bool)
    return_trip_min = np.full(params.n_agents, np.nan, dtype=np.float32)
    outbound_exposure = np.zeros(params.n_agents, dtype=np.float32)

    n_ticks = int((params.end_hour - params.start_hour) * 3600 / params.timestep_s)
    trip_log: list[dict] = []
    t0 = time.perf_counter()

    time_density = np.zeros(params.time_density_grid_shape, dtype=np.float64)
    time_density_transform = grid_transform_for_bbox(params.bbox, params.time_density_grid_shape)
    segment_exposure = SegmentExposure()

    for tick_i in range(n_ticks):
        departing = (departure_ticks == tick_i) & ~pool.active
        pool.active[departing] = True
        for i in np.flatnonzero(return_ticks == tick_i):
            on_return_leg[i] = True
            started = _start_return_trip(
                pool, i, G, ctx.router, int(dest_nodes[i]), int(spawn_nodes[i]), tick_i, params, draws,
            )
            if started:
                return_modes[i] = _trip_mode(pool.route_edges[i], G)
            elif started is None:  # destination is home: nothing to travel
                returned[i] = True

        active_before_tick = pool.active.copy()
        tick(
            pool, G, params.heat_surface, tick_i, params.timestep_s, params.start_hour,
            time_density=time_density, time_density_transform=time_density_transform,
            segment_exposure=segment_exposure, utci_threshold_c=params.utci_threshold_c,
        )

        # Only agents that transitioned active -> inactive *this* tick just finished;
        # otherwise a completed agent (route_index stays > 0) gets re-logged every
        # remaining tick of the simulation.
        just_finished = active_before_tick & ~pool.active
        out_done = just_finished & ~on_return_leg
        home_done = just_finished & on_return_leg
        trip_min[out_done] = (tick_i + 1 - departure_ticks[out_done]) * params.timestep_s / 60.0
        outbound_exposure[out_done] = pool.heat_exposure_degC_min[out_done]
        return_trip_min[home_done] = (tick_i + 1 - return_ticks[home_done]) * params.timestep_s / 60.0
        returned[home_done] = True
        if params.behavior.return_trips:
            arrival_hour = params.start_hour + (tick_i + 1) * params.timestep_s / 3600.0
            for i in np.flatnonzero(out_done):
                h = return_departure_hour(
                    params.behavior, PURPOSE_KEYS[int(pool.trip_purpose[i])], arrival_hour, float(return_z[i]),
                )
                return_hour[i] = h
                t = int(np.ceil((h - params.start_hour) * 3600.0 / params.timestep_s - 1e-9))
                if t < n_ticks:
                    return_ticks[i] = max(t, tick_i + 1)
        for i in np.where(just_finished)[0]:
            leg_heat = pool.heat_exposure_degC_min[i] - (outbound_exposure[i] if on_return_leg[i] else 0.0)
            trip_log.append({
                "agent_id": int(i),
                "leg": "return" if on_return_leg[i] else "outbound",
                "purpose": int(pool.trip_purpose[i]),
                "mode": _trip_mode(pool.route_edges[i], G),
                "heat_degC_min": float(leg_heat),
                "age_group": int(pool.age_group[i]),
                "gender": int(pool.gender[i]),
                "ses": int(pool.ses[i]),
            })

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
        time_density=time_density,
        time_density_transform=time_density_transform,
        agent_home_node=np.asarray(spawn_nodes, dtype=np.int64),
        agent_home_lon=np.array([G.nodes[n]["x"] for n in spawn_nodes], dtype=np.float64),
        agent_home_lat=np.array([G.nodes[n]["y"] for n in spawn_nodes], dtype=np.float64),
        segment_exposure=segment_exposure.edges_frame(),
        stop_exposure=segment_exposure.stops_frame(),
        agent_outdoor_min=pool.outdoor_min.copy(),
        agent_access_walk_min=access_walk_min,
        agent_ride_min=ride_min,
        agent_trip_min=trip_min,
        agent_outbound_exposure_degC_min=np.where(on_return_leg, outbound_exposure,
                                                  pool.heat_exposure_degC_min).astype(np.float32),
        agent_return_departure_hour=return_hour,
        agent_return_modes=return_modes,
        agent_returned=returned,
        agent_return_trip_min=return_trip_min,
        agent_utci_degC_min=pool.utci_degC_min.copy(),
    )


def _start_return_trip(pool: AgentPool, i: int, G, router: FastRouter, origin: int, home: int,
                       tick_i: int, params: SimulationParams, draws) -> bool | None:
    """Plan agent i's trip home, leaving at tick_i, and set it moving. Returns True if
    it set off, None if the destination is home (nothing to travel), False if there is
    no path home (the agent's day ends at its destination)."""
    try:
        edges = plan_route(
            router, origin, home, int(pool.trip_purpose[i]), tick_i, params.behavior,
            float(draws.walk[i]), float(draws.return_wait[i]), float(pool.speed_mps[i]),
            params.start_hour, params.timestep_s,
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
        logger.warning("No path home for agent %d (%d -> %d): %s", i, origin, home, exc)
        return False
    if not edges:
        return None
    start_route(pool, i, G, edges)
    pool.active[i] = True
    return True


def _transit_trip_parts(pool: AgentPool, G) -> tuple[np.ndarray, np.ndarray]:
    """
    Per agent, from its planned route (NaN if the route never rides transit):
    - access: minutes walked before the first transit edge;
    - ride: minutes from boarding the first vehicle to leaving the last one — the transit
      edges' travel_time plus any walking between them (transfers). Excludes the access
      walk, the boarding wait and the walk from the last stop.
    """
    access = np.full(pool.n, np.nan, dtype=np.float32)
    ride = np.full(pool.n, np.nan, dtype=np.float32)
    for i, edges in enumerate(pool.route_edges):
        speed = float(pool.speed_mps[i])
        is_transit = [G[u][v][k].get("edge_type") == "transit" for u, v, k, _ in edges]
        if not any(is_transit):
            continue
        first = is_transit.index(True)
        last = len(is_transit) - 1 - is_transit[::-1].index(True)
        access[i] = sum(float(G[u][v][k].get("length", 1.0)) for u, v, k, _ in edges[:first]) / speed / 60.0
        seconds = 0.0
        for (u, v, k, _), t in zip(edges[first:last + 1], is_transit[first:last + 1]):
            d = G[u][v][k]
            seconds += float(d.get("travel_time", 1.0)) if t else float(d.get("length", 1.0)) / speed
        ride[i] = seconds / 60.0
    return access, ride


def _access_walk_minutes(pool: AgentPool, G) -> np.ndarray:
    return _transit_trip_parts(pool, G)[0]


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
    Ratio-like fields (walk_only_share, peak weights, travel_probability) are clipped to
    [0, 1] here rather than left to __post_init__ to raise, so slider-driven exploration
    degrades gracefully instead of crashing a run.
    """
    m_age = demo.age_modifiers.get(age_code, ParamModifier())
    m_gender = demo.gender_modifiers.get(gender_code, ParamModifier())
    m_ses = demo.ses_modifiers.get(ses_code, ParamModifier())
    modifiers = (m_age, m_gender, m_ses)

    def _mult(field_name: str) -> float:
        product = 1.0
        for m in modifiers:
            product *= getattr(m, field_name)
        return product

    trip_rate_mean = base.trip_rate_mean * _mult("trip_rate_mean_mult")
    trip_rate_std = base.trip_rate_std * _mult("trip_rate_std_mult")
    peak1_hour = base.peak1_hour * _mult("peak1_hour_mult")
    peak2_hour = base.peak2_hour * _mult("peak2_hour_mult")
    peak1_weight = np.clip(base.peak1_weight * _mult("peak1_weight_mult"), 0.0, 1.0)
    peak2_weight = np.clip(base.peak2_weight * _mult("peak2_weight_mult"), 0.0, 1.0)
    walk_only_share = np.clip(base.walk_only_share * _mult("walk_only_share_mult"), 0.0, 1.0)
    walk_speed_mean_mps = base.walk_speed_mean_mps * _mult("walk_speed_mean_mps_mult")
    walk_speed_std_mps = base.walk_speed_std_mps * _mult("walk_speed_std_mps_mult")
    transit_wait_tolerance_min = base.transit_wait_tolerance_min * _mult("transit_wait_tolerance_min_mult")
    transit_wait_tolerance_std = base.transit_wait_tolerance_std * _mult("transit_wait_tolerance_std_mult")

    purpose_weights = dict(base.purpose_weights)
    for modifier in modifiers:
        for purpose, mult in modifier.purpose_weight_mult.items():
            purpose_weights[purpose] = purpose_weights.get(purpose, 0.0) * mult

    travel_probability = dict(base.travel_probability)
    for modifier in modifiers:
        for purpose, mult in modifier.travel_probability_mult.items():
            travel_probability[purpose] = travel_probability.get(purpose, 1.0) * mult
    travel_probability = {k: float(np.clip(v, 0.0, 1.0)) for k, v in travel_probability.items()}

    # Departure windows intersect: a trip must satisfy every window that applies to it.
    # An empty intersection is dropped with a warning rather than raising, matching the
    # graceful-degradation stance above.
    departure_window_h = {k: list(v) for k, v in base.departure_window_h.items()}
    for modifier in modifiers:
        for purpose, (lo, hi) in modifier.departure_window_h.items():
            if purpose in departure_window_h:
                lo = max(lo, departure_window_h[purpose][0])
                hi = min(hi, departure_window_h[purpose][1])
            if lo < hi:
                departure_window_h[purpose] = [lo, hi]
            else:
                logger.warning("Departure windows for %r don't overlap; ignoring them for this segment", purpose)
                departure_window_h.pop(purpose, None)

    return dataclasses.replace(
        base,
        trip_rate_mean=trip_rate_mean,
        trip_rate_std=trip_rate_std,
        peak1_hour=peak1_hour,
        peak2_hour=peak2_hour,
        peak1_weight=float(peak1_weight),
        peak2_weight=float(peak2_weight),
        walk_only_share=float(walk_only_share),
        walk_speed_mean_mps=walk_speed_mean_mps,
        walk_speed_std_mps=walk_speed_std_mps,
        transit_wait_tolerance_min=transit_wait_tolerance_min,
        transit_wait_tolerance_std=transit_wait_tolerance_std,
        purpose_weights=purpose_weights,
        travel_probability=travel_probability,
        departure_window_h=departure_window_h,
    )


def _draw_trip_counts(behavior: TravelBehaviorParams, n: int, rng: np.random.Generator) -> np.ndarray:
    if behavior.trip_rate_distribution == "poisson":
        counts = rng.poisson(behavior.trip_rate_mean, n)
    else:
        counts = np.round(rng.normal(behavior.trip_rate_mean, behavior.trip_rate_std, n))
    return np.clip(counts, 1, None).astype(np.int32)


def _departure_profile_pmf(
    behavior: TravelBehaviorParams,
    n_ticks: int,
    start_hour: int,
    timestep_s: float,
) -> np.ndarray:
    """
    Probability of departing at each tick under the purpose-independent profile.

    "bimodal" = two Gaussian peaks (30-min std dev) + an off-peak uniform share. Each
    peak's mass is integrated over a tick's rounding interval [k - 0.5, k + 0.5), and
    tails beyond the simulated window pile onto its first/last tick — the same
    distribution as drawing a normal, rounding it, and clipping it to the window.
    """
    if behavior.departure_profile == "uniform":
        return np.full(n_ticks, 1.0 / n_ticks)

    p1 = behavior.peak1_weight
    p2 = behavior.peak2_weight
    p_off = max(0.0, 1.0 - p1 - p2)
    std_ticks = int(0.5 * 3600 / timestep_s)  # 30-min std dev

    # Rounding boundaries between ticks; the outermost are open so clipped tails land
    # on tick 0 and tick n_ticks - 1.
    bounds = np.arange(n_ticks + 1) - 0.5
    bounds[0], bounds[-1] = -np.inf, np.inf

    def _peak(hour: float) -> np.ndarray:
        mu = (hour - start_hour) * 3600 / timestep_s
        return np.diff(ndtr((bounds - mu) / std_ticks))

    pmf = p1 * _peak(behavior.peak1_hour) + p2 * _peak(behavior.peak2_hour) + p_off / n_ticks
    return pmf / pmf.sum()


def _purpose_tilt_by_tick(
    behavior: TravelBehaviorParams,
    purpose: str,
    n_ticks: int,
    start_hour: int,
    timestep_s: float,
) -> np.ndarray:
    """departure_purpose_tilt[purpose] expanded to one multiplier per tick (1.0 outside
    every band, or when the purpose has no tilt)."""
    tilt = behavior.departure_purpose_tilt.get(purpose)
    if tilt is None:
        return np.ones(n_ticks)
    edges = np.asarray(behavior.departure_tilt_band_edges_h, dtype=float)
    hours = start_hour + np.arange(n_ticks) * timestep_s / 3600.0
    band = np.searchsorted(edges, hours, side="right") - 1
    in_band = (band >= 0) & (band < len(tilt))
    out = np.ones(n_ticks)
    out[in_band] = np.asarray(tilt, dtype=float)[band[in_band]]
    return out


def _draw_departure_ticks(
    behavior: TravelBehaviorParams,
    purposes: np.ndarray,
    start_hour: int,
    end_hour: int,
    timestep_s: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    One departure tick per agent, conditioned on its already-drawn purpose:
    P(tick | purpose) ∝ P_profile(tick) × departure_purpose_tilt[purpose] at that tick,
    set to zero outside departure_window_h[purpose] if the purpose has a window.
    """
    n_ticks = int((end_hour - start_hour) * 3600 / timestep_s)
    base = _departure_profile_pmf(behavior, n_ticks, start_hour, timestep_s)
    ticks = np.empty(len(purposes), dtype=np.int32)
    # One uniform per agent, mapped through its purpose's CDF: a shifted profile moves
    # each agent's departure rather than redrawing it (common random numbers).
    u = rng.random(len(purposes))
    for code in np.unique(purposes):
        idx = np.flatnonzero(purposes == code)
        purpose = PURPOSE_KEYS[code]
        pmf = base * _purpose_tilt_by_tick(behavior, purpose, n_ticks, start_hour, timestep_s)
        window = behavior.departure_window_h.get(purpose)
        if window is not None:
            hours = start_hour + np.arange(n_ticks) * timestep_s / 3600.0
            pmf = pmf * ((hours >= window[0]) & (hours < window[1]))
        total = pmf.sum()
        if total > 0:
            pmf = pmf / total
        else:  # an all-zero tilt, or a window outside the simulated day, can't zero out a purpose's trips
            logger.warning("No departure probability left for %r trips; using the unweighted profile", purpose)
            pmf = base
        cdf = np.cumsum(pmf)
        ticks[idx] = np.minimum(np.searchsorted(cdf / cdf[-1], u[idx], side="right"), n_ticks - 1)
    return ticks


# PURPOSE_* codes (0-3), in order, as the string keys used by purpose_weights and
# travel_probability on TravelBehaviorParams.
PURPOSE_KEYS: tuple[str, ...] = ("work", "school", "market", "other")

# Maps PURPOSE_* codes → amenity category key (None = any graph node)
_PURPOSE_AMENITY: dict[int, str | None] = {
    0: "work",
    1: "school",
    2: "food",
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
    distance_decay: float = 1.0,
) -> np.ndarray:
    """
    Draw one destination per agent from the OSM amenity category matching its trip
    purpose ("work" draws from offices/industrial-commercial land plus shop/school/
    health locations, since those also employ workers — see `_add_work_overlap` in
    data/amenities.py). Falls back to any graph node if a category's amenity pool is
    empty (e.g. an OSM fetch failure). Candidates are weighted by
    distance ** -distance_decay from the agent's origin node (distance floored at
    min_distance_m), so nearby destinations are preferred over far ones; the origin
    node itself is excluded to avoid zero-length trips. Each agent's choice uses one
    uniform draw, taken in agent order.
    """
    u = rng.random(len(purposes))
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
            weights = np.maximum(dists, min_distance_m) ** -distance_decay
            weights[pool == origin] = 0.0  # exclude self: avoid zero-length trips

            total = weights.sum()
            if total <= 0.0:
                # Only candidate is the origin itself (e.g. single-node amenity pool) — allow it.
                weights = np.ones_like(weights)
                total = weights.sum()

            cdf = np.cumsum(weights)
            dest_nodes[i] = pool[min(int(np.searchsorted(cdf, u[i] * cdf[-1], side="right")), len(pool) - 1)]

    return dest_nodes


def _draw_purposes(behavior: TravelBehaviorParams, n: int, rng: np.random.Generator) -> np.ndarray:
    weights = [behavior.purpose_weights.get(k, 0.0) for k in PURPOSE_KEYS]
    return rng.choice(len(PURPOSE_KEYS), size=n, p=weights).astype(np.uint8)


def _draw_travel_gate(behavior: TravelBehaviorParams, purposes: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """
    Per-agent Bernoulli draw on behavior.travel_probability[purpose], keyed by each
    agent's already-drawn purpose. True = the agent's single simulated trip happens.
    """
    p = np.array([behavior.travel_probability.get(PURPOSE_KEYS[code], 1.0) for code in purposes])
    return rng.random(len(purposes)) < p
