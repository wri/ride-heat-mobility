from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from shapely.geometry import LineString

from nairobi_heat_abm.data.heat import HeatSurface
from nairobi_heat_abm.model.agent import TravelBehaviorParams


# ---------------------------------------------------------------------------
# Geographic fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def small_bbox():
    """~2km² patch around Westlands, Nairobi — used for real OSM tests."""
    return (-1.275, 36.800, -1.255, 36.820)  # (south, west, north, east)


@pytest.fixture
def tiny_graph():
    """
    3×3 grid of 9 nodes within the Nairobi bbox.
    All edges carry length, travel_time, weight, geometry.
    No OSM download needed.
    """
    G = nx.MultiDiGraph()
    base_lon, base_lat = 36.800, -1.300
    step = 0.010  # ~1 km

    node_ids: dict[tuple[int, int], int] = {}
    nid = 1000
    for row in range(3):
        for col in range(3):
            lon = base_lon + col * step
            lat = base_lat + row * step
            G.add_node(nid, x=lon, y=lat, node_type="intersection")
            node_ids[(row, col)] = nid
            nid += 1

    def _add_edge(u, v):
        ux, uy = G.nodes[u]["x"], G.nodes[u]["y"]
        vx, vy = G.nodes[v]["x"], G.nodes[v]["y"]
        length = 1000.0
        travel_time = length / 1.2
        attrs = dict(length=length, travel_time=travel_time, weight=travel_time,
                     geometry=LineString([(ux, uy), (vx, vy)]))
        G.add_edge(u, v, **attrs)
        attrs_rev = dict(length=length, travel_time=travel_time, weight=travel_time,
                         geometry=LineString([(vx, vy), (ux, uy)]))
        G.add_edge(v, u, **attrs_rev)

    for row in range(3):
        for col in range(3):
            if col < 2:
                _add_edge(node_ids[(row, col)], node_ids[(row, col + 1)])
            if row < 2:
                _add_edge(node_ids[(row, col)], node_ids[(row + 1, col)])

    return G


# ---------------------------------------------------------------------------
# Heat surface fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flat_heat_surface():
    """Uniform 25 °C across Nairobi bbox, 24 hourly bands."""
    array = np.full((24, 50, 50), 25.0, dtype=np.float32)
    transform = from_bounds(36.649, -1.444, 37.104, -1.163, 50, 50)
    return HeatSurface(array=array, transform=transform,
                       hours=list(range(24)), crs="EPSG:4326", name="flat_test")


@pytest.fixture
def flat_heat_surface_30C():
    """Uniform 30 °C — used for exact accumulation maths."""
    array = np.full((24, 50, 50), 30.0, dtype=np.float32)
    transform = from_bounds(36.649, -1.444, 37.104, -1.163, 50, 50)
    return HeatSurface(array=array, transform=transform,
                       hours=list(range(24)), crs="EPSG:4326", name="flat_30C")


@pytest.fixture
def sample_tif(tmp_path):
    """Minimal single-band synthetic GeoTIFF at 30 °C for load_heat_surface tests."""
    tif_path = tmp_path / "heat_test.tif"
    array = np.full((1, 50, 50), 30.0, dtype=np.float32)
    transform = from_bounds(36.649, -1.444, 37.104, -1.163, 50, 50)
    with rasterio.open(
        tif_path, "w", driver="GTiff",
        height=50, width=50, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(array)
    return tif_path


# ---------------------------------------------------------------------------
# Simulation fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mini_simulation_params(tiny_graph, flat_heat_surface, tmp_path):
    """SimulationParams for 20 agents, 2-hour run. No real external data files."""
    import osmnx as ox

    graph_path = tmp_path / "tiny_graph.graphml"
    ox.save_graphml(tiny_graph, filepath=graph_path)

    worldpop_path = tmp_path / "worldpop.tif"
    wp_array = np.ones((1, 10, 10), dtype=np.float32)
    wp_transform = from_bounds(36.800, -1.320, 36.830, -1.280, 10, 10)
    with rasterio.open(
        worldpop_path, "w", driver="GTiff",
        height=10, width=10, count=1,
        dtype="float32", crs="EPSG:4326", transform=wp_transform,
    ) as dst:
        dst.write(wp_array)

    amenity_path = tmp_path / "amenities.json"
    nodes = list(tiny_graph.nodes())
    amenity_data = {cat: [nodes[0]] for cat in ["school", "shop", "health", "other"]}
    amenity_path.write_text(json.dumps(amenity_data))

    from nairobi_heat_abm.model.simulation import SimulationParams

    return SimulationParams(
        bbox=(-1.320, 36.800, -1.280, 36.830),
        n_agents=20,
        start_hour=6,
        end_hour=8,
        timestep_s=60.0,
        seed=42,
        behavior=TravelBehaviorParams(),
        graph_cache_path=graph_path,
        amenity_cache_path=amenity_path,
        worldpop_tif_path=worldpop_path,
        heat_surface=flat_heat_surface,
    )


@pytest.fixture
def mock_scenario_result(flat_heat_surface):
    """ScenarioResult with 100 agents and plausible mock values. No real simulation."""
    from nairobi_heat_abm.model.simulation import SimulationParams, ScenarioResult

    params = SimulationParams(
        bbox=(-1.320, 36.800, -1.280, 36.830),
        n_agents=100,
        start_hour=6,
        end_hour=8,
        timestep_s=60.0,
        seed=0,
        behavior=TravelBehaviorParams(),
        graph_cache_path=Path("data/raw/graph.graphml"),
        amenity_cache_path=Path("data/raw/amenities.json"),
        worldpop_tif_path=Path("data/raw/worldpop_nairobi.tif"),
        heat_surface=flat_heat_surface,
    )
    rng = np.random.default_rng(0)
    n = 100
    return ScenarioResult(
        params=params,
        agent_exposure_degC_min=rng.uniform(10, 80, n).astype(np.float32),
        agent_modes=rng.choice([0, 2], n).astype(np.uint8),
        agent_purposes=rng.choice([0, 1, 2, 3], n).astype(np.uint8),
        agent_n_trips=rng.integers(1, 5, n).astype(np.int32),
        trip_log=[
            {"agent_id": i, "purpose": int(rng.integers(4)),
             "mode": int(rng.choice([0, 2])),
             "heat_degC_min": float(rng.uniform(10, 80))}
            for i in range(n)
        ],
        elapsed_seconds=1.0,
    )


@pytest.fixture
def mini_scenarios(mini_simulation_params):
    """5 SimulationParams with different seeds."""
    import dataclasses
    return [dataclasses.replace(mini_simulation_params, seed=i) for i in range(5)]


@pytest.fixture
def mini_result_set(flat_heat_surface):
    """RDMResultSet built from 20 mock ScenarioResults with varying exposures."""
    from nairobi_heat_abm.model.simulation import SimulationParams, ScenarioResult
    from nairobi_heat_abm.rdm.analysis import build_result_set

    params = SimulationParams(
        bbox=(-1.320, 36.800, -1.280, 36.830),
        n_agents=50,
        start_hour=6,
        end_hour=8,
        timestep_s=60.0,
        seed=0,
        behavior=TravelBehaviorParams(),
        graph_cache_path=Path("data/raw/graph.graphml"),
        amenity_cache_path=Path("data/raw/amenities.json"),
        worldpop_tif_path=Path("data/raw/worldpop_nairobi.tif"),
        heat_surface=flat_heat_surface,
    )

    results = []
    for seed in range(20):
        import dataclasses
        rng = np.random.default_rng(seed)
        behavior = dataclasses.replace(
            params.behavior,
            trip_rate_mean=rng.uniform(1.5, 5.0),
            walk_only_share=rng.uniform(0.3, 0.8),
        )
        p = dataclasses.replace(params, behavior=behavior, seed=seed)
        results.append(ScenarioResult(
            params=p,
            agent_exposure_degC_min=rng.uniform(10, 80, 50).astype(np.float32),
            agent_modes=rng.choice([0, 2], 50).astype(np.uint8),
            agent_purposes=rng.choice([0, 1, 2, 3], 50).astype(np.uint8),
            agent_n_trips=rng.integers(1, 5, 50).astype(np.int32),
            trip_log=[],
            elapsed_seconds=0.1,
        ))

    return build_result_set(results)
