"""Per-segment exposure accounting, GIS export, and home-location SES tagging."""
from __future__ import annotations

import sqlite3

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from nairobi_heat_abm.data.export import segment_layer, stop_layer, write_exposure_gpkg
from nairobi_heat_abm.data.ses import tag_homes, ward_exposure_layer
from nairobi_heat_abm.model.agent import MODE_WAIT, MODE_WALK, AgentPool
from nairobi_heat_abm.model.scheduler import tick
from nairobi_heat_abm.model.segment_exposure import SegmentExposure


def _walkers(G, n, u, v):
    pool = AgentPool.create(n)
    pool.active[:] = True
    pool.mode[:] = MODE_WALK
    pool.speed_mps[:] = 1.2
    pool.edge_speed_mps[:] = 1.2
    pool.edge_length[:] = 1000.0
    pool.edge_u[:] = u
    pool.edge_v[:] = v
    pool.route_edges = [[(u, v, 0, 0)] for _ in range(n)]
    return pool


def test_tick_attributes_walking_heat_to_the_edge(tiny_graph, flat_heat_surface_30C):
    nodes = sorted(tiny_graph.nodes())
    pool = _walkers(tiny_graph, 3, nodes[0], nodes[1])
    seg = SegmentExposure()

    tick(pool, tiny_graph, flat_heat_surface_30C, sim_tick=0, timestep_s=60.0, start_hour=6,
         segment_exposure=seg)
    tick(pool, tiny_graph, flat_heat_surface_30C, sim_tick=1, timestep_s=60.0, start_hour=6,
         segment_exposure=seg)

    edges = seg.edges_frame()
    assert len(edges) == 1
    row = edges.iloc[0]
    assert (row.u, row.v, row.key) == (nodes[0], nodes[1], 0)
    assert row.person_min == pytest.approx(6.0)        # 3 agents × 2 one-minute ticks
    assert row.heat_degC_min == pytest.approx(24.0, abs=0.5)  # × (30 - 26 °C)
    assert row.heat_degC_min == pytest.approx(pool.heat_exposure_degC_min.sum(), rel=1e-5)
    assert seg.stops_frame().empty


def test_tick_attributes_waiting_heat_to_the_stop_not_the_ride(transit_graph, flat_heat_surface_30C):
    pool = AgentPool.create(1)
    pool.active[:] = True
    pool.mode[:] = MODE_WAIT
    pool.wait_ticks_remaining[:] = 5
    pool.edge_u[:] = 9000
    pool.edge_v[:] = 9001
    pool.edge_length[:] = 2000.0
    pool.edge_speed_mps[:] = 2000.0 / 300.0
    pool.route_edges = [[(9000, 9001, 0, 5)]]
    seg = SegmentExposure()

    tick(pool, transit_graph, flat_heat_surface_30C, sim_tick=0, timestep_s=60.0, start_hour=6,
         segment_exposure=seg)

    assert seg.edges_frame().empty  # nothing on the transit edge itself
    stops = seg.stops_frame()
    assert stops["node"].tolist() == [9000]
    assert stops["person_min"].iloc[0] == pytest.approx(1.0)
    assert stops["heat_degC_min"].iloc[0] == pytest.approx(4.0, abs=0.1)  # 1 min × (30 - 26 °C)


def test_simulation_segment_and_stop_totals_match_agent_exposure(mini_simulation_params):
    from nairobi_heat_abm.model.simulation import run
    result = run(mini_simulation_params)
    n = mini_simulation_params.n_agents

    assert result.agent_home_node.shape == (n,)
    assert result.agent_home_lon.shape == (n,) and np.isfinite(result.agent_home_lon).all()
    assert not result.segment_exposure.empty

    attributed = result.segment_exposure["heat_degC_min"].sum()
    if not result.stop_exposure.empty:
        attributed += result.stop_exposure["heat_degC_min"].sum()
    assert attributed == pytest.approx(float(result.agent_exposure_degC_min.astype(np.float64).sum()), rel=1e-4)


def test_segment_layer_merges_directions_and_keeps_geometry(tiny_graph):
    a, b, c = sorted(tiny_graph.nodes())[:3]
    df = pd.DataFrame({
        "u": [a, b, b], "v": [b, a, c], "key": [0, 0, 0],
        "heat_degC_min": [100.0, 50.0, 30.0], "person_min": [4.0, 2.0, 1.0],
    })
    gdf = segment_layer(tiny_graph, df)

    assert len(gdf) == 2  # a<->b merged, b->c alone
    ab = gdf[gdf[["u", "v"]].isin([a, b]).all(axis=1)].iloc[0]
    assert ab.heat_degC_min == pytest.approx(150.0)
    assert ab.person_min == pytest.approx(6.0)
    assert ab.mean_heat_degC == pytest.approx(25.0)
    assert ab.heat_degC_min_per_100m == pytest.approx(15.0)  # tiny_graph edges are 1000 m
    assert ab.geometry.geom_type == "LineString"
    assert gdf.crs.to_epsg() == 4326


def test_write_exposure_gpkg_embeds_default_qgis_styles(tmp_path, transit_graph):
    a, b = sorted(transit_graph.nodes())[:2]
    seg = segment_layer(transit_graph, pd.DataFrame({  # one segment: a single-class style
        "u": [a], "v": [b], "key": [0], "heat_degC_min": [500.0], "person_min": [10.0],
    }))
    stops = stop_layer(transit_graph, pd.DataFrame({
        "node": [9000, 9001], "heat_degC_min": [60.0, 600.0], "person_min": [2.0, 20.0],
    }))
    path = write_exposure_gpkg(tmp_path / "out.gpkg", {"segments": seg, "stops": stops})

    assert set(gpd.list_layers(path)["name"]) >= {"segments", "stops"}
    assert gpd.read_file(path, layer="stops")["stop_name"].tolist() == ["Stop A", "Stop B"]
    with sqlite3.connect(path) as con:
        styled = dict(con.execute("SELECT f_table_name, styleQML FROM layer_styles WHERE useAsDefault = 1"))
    assert set(styled) == {"segments", "stops"}
    assert 'type="graduatedSymbol"' in styled["stops"] and 'attr="heat_degC_min"' in styled["stops"]


def test_tag_homes_joins_ward_rwi_and_informality():
    wards = gpd.GeoDataFrame(
        {"ward_id": ["W1", "W2"], "ward": ["West", "East"]},
        geometry=[box(36.80, -1.30, 36.85, -1.25), box(36.85, -1.30, 36.90, -1.25)], crs="EPSG:4326",
    )
    rwi = pd.DataFrame({"latitude": [-1.27, -1.27], "longitude": [36.82, 36.88],
                        "rwi": [0.9, -0.4], "error": [0.3, 0.4]})
    informality = pd.DataFrame({
        "result": [2], "latitude": [-1.2705], "longitude": [36.8205],
        "lon_min": [36.820], "lat_min": [-1.271], "lon_max": [36.821], "lat_max": [-1.270],
    })
    lons = np.array([36.8203, 36.8800, 37.5000])  # in W1 + informal cell, in W2, far outside everything
    lats = np.array([-1.2703, -1.2700, -1.0000])

    tags = tag_homes(lons, lats, wards=wards, rwi=rwi, informality=informality)

    assert tags["ward"].tolist()[:2] == ["West", "East"] and pd.isna(tags["ward"].iloc[2])
    assert tags["rwi"].iloc[0] == pytest.approx(0.9) and tags["rwi"].iloc[1] == pytest.approx(-0.4)
    assert np.isnan(tags["rwi"].iloc[2])
    assert tags["informality"].iloc[0] == 2 and tags["informality_label"].iloc[0] == "high"
    assert np.isnan(tags["informality"].iloc[1])

    agents = tags.assign(exposure_degC_min=[100.0, 0.0, 50.0], travelled=[True, False, True])
    layer = ward_exposure_layer(agents, wards)
    west = layer.set_index("ward").loc["West"]
    east = layer.set_index("ward").loc["East"]
    assert west.n_agents == 1 and west.mean_heat_degC_min == pytest.approx(100.0)
    assert east.n_agents == 1 and east.n_travelled == 0 and np.isnan(east.mean_heat_degC_min)
