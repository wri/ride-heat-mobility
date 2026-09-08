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
    G.graph["crs"] = "epsg:4326"
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


@pytest.fixture
def small_gtfs_dir(tmp_path):
    """
    A tiny synthetic GTFS feed (3 stops, 1 trip, 2 frequency bands), shaped like the
    real DigitalMatatus feed: stop_times.txt is a single reference run, real service
    frequency lives in frequencies.txt. Stop coordinates sit on tiny_graph's bottom row
    (lat -1.300) so _integrate_gtfs() snaps access-links onto real tiny_graph nodes.
    """
    gtfs_dir = tmp_path / "gtfs"
    gtfs_dir.mkdir()
    (gtfs_dir / "stops.txt").write_text(
        "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
        "S1,Stop A,-1.300,36.800,0,\n"
        "S2,Stop B,-1.300,36.810,0,\n"
        "S3,Stop C,-1.300,36.820,0,\n"
    )
    (gtfs_dir / "trips.txt").write_text(
        "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n"
        "R1,DAILY,T1,Eastbound,0,SH1\n"
    )
    (gtfs_dir / "stop_times.txt").write_text(
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,6:00:00,6:00:00,S1,1\n"
        "T1,6:02:00,6:02:20,S2,2\n"
        "T1,6:05:00,6:05:20,S3,3\n"
    )
    (gtfs_dir / "frequencies.txt").write_text(
        "trip_id,start_time,end_time,headway_secs\n"
        "T1,06:00:00,09:00:00,300\n"
        "T1,09:00:00,15:00:00,900\n"
    )
    return gtfs_dir


@pytest.fixture
def transit_graph(tiny_graph):
    """
    tiny_graph plus 2 hand-built transit stops (stop_a near node (0,0), stop_b near
    node (0,2), the opposite ends of the bottom row) connected by bidirectional
    access-links and a single directed 5-minute transit ride, serviced 6:00-9:00 at a
    300s headway and 9:00-21:00 at a 900s headway. Used to test route_transit()/tick()
    precisely, without going through GTFS parsing.
    """
    G = tiny_graph.copy()
    nodes = sorted(G.nodes())  # tiny_graph builds nodes 1000..1008 in row-major order
    walk_a, walk_b = nodes[0], nodes[2]  # (0,0) and (0,2): lon 36.800 and 36.820, lat -1.300

    stop_a, stop_b = 9000, 9001
    G.add_node(stop_a, x=36.800, y=-1.300, node_type="transit_stop", stop_id="S1", stop_name="Stop A")
    G.add_node(stop_b, x=36.820, y=-1.300, node_type="transit_stop", stop_id="S2", stop_name="Stop B")

    G.add_edge(stop_a, walk_a, length=10.0, travel_time=8.3, edge_type="access_link")
    G.add_edge(walk_a, stop_a, length=10.0, travel_time=8.3, edge_type="access_link")
    G.add_edge(stop_b, walk_b, length=10.0, travel_time=8.3, edge_type="access_link")
    G.add_edge(walk_b, stop_b, length=10.0, travel_time=8.3, edge_type="access_link")

    G.add_edge(
        stop_a, stop_b, length=2000.0, travel_time=300.0, edge_type="transit",
        route_id="R1", trip_id="T1",
        frequencies=[[21600, 32400, 300], [32400, 75600, 900]],  # 6-9am @5min, 9am-9pm @15min
    )
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
    amenity_data = {cat: [nodes[0]] for cat in ["school", "food", "health", "other", "work"]}
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
def demographic_raster_paths(tmp_path):
    """
    5 small aligned rasters (total/children/adult/elderly/female) over the same bbox
    as mini_simulation_params, with a spatial split: the western half is all children,
    the eastern half is all adults (20+, no elderly); the northern half is all female.
    Used to test DemographicParams.population_raster_paths / draw_age_gender_spatial
    end-to-end via simulation.run().
    """
    transform = from_bounds(36.800, -1.320, 36.830, -1.280, 10, 10)

    def _write(name, array):
        path = tmp_path / f"{name}.tif"
        with rasterio.open(
            path, "w", driver="GTiff",
            height=10, width=10, count=1,
            dtype="float32", crs="EPSG:4326", transform=transform,
        ) as dst:
            dst.write(array[np.newaxis, :, :].astype(np.float32))
        return path

    total = np.ones((10, 10), dtype=np.float32)
    children = np.zeros((10, 10), dtype=np.float32)
    children[:, :5] = 1.0  # western half
    adult = 1.0 - children  # eastern half
    elderly = np.zeros((10, 10), dtype=np.float32)
    female = np.zeros((10, 10), dtype=np.float32)
    female[:5, :] = 1.0  # northern half (row 0 = north, per from_bounds convention)

    return {
        "total": _write("total", total),
        "children": _write("children", children),
        "adult": _write("adult", adult),
        "elderly": _write("elderly", elderly),
        "female": _write("female", female),
    }


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
