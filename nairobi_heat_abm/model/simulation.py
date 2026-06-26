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
    departure_ticks = _draw_departure_ticks(params.behavior, params.start_hour,
                                            params.end_hour, params.timestep_s, rng)
    dest_nodes = _draw_destinations(amenities, spawn_nodes, params.behavior, G, rng)

    pool = AgentPool.create(params.n_agents)
    pool.trip_purpose[:] = _draw_purposes(params.behavior, params.n_agents, rng)
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

        tick(pool, G, params.heat_surface, tick_i, params.timestep_s, params.start_hour)

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


def _draw_trip_counts(behavior: TravelBehaviorParams, n: int, rng: np.random.Generator) -> np.ndarray:
    raise NotImplementedError


def _draw_departure_ticks(
    behavior: TravelBehaviorParams,
    start_hour: int,
    end_hour: int,
    timestep_s: float,
    rng: np.random.Generator,
) -> np.ndarray:
    raise NotImplementedError


def _draw_destinations(
    amenities: dict[str, list[int]],
    spawn_nodes: np.ndarray,
    behavior: TravelBehaviorParams,
    G,
    rng: np.random.Generator,
) -> np.ndarray:
    raise NotImplementedError


def _draw_purposes(behavior: TravelBehaviorParams, n: int, rng: np.random.Generator) -> np.ndarray:
    raise NotImplementedError
