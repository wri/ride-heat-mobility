"""Phase 1 gate tests — data infrastructure."""
from __future__ import annotations

import numpy as np
import osmnx as ox
import pytest
import rasterio
import rasterio.transform

from nairobi_heat_abm.data.amenities import AMENITY_TAGS, _add_work_overlap, build_amenity_index
from nairobi_heat_abm.data.graph import _integrate_gtfs, build_graph
from nairobi_heat_abm.data.heat import load_heat_surface, sample_temperature
from nairobi_heat_abm.data.population import load_population_raster, load_population_rasters, sample_spawn_nodes


@pytest.mark.slow
def test_graph_builds_and_has_required_edge_attributes(small_bbox, tmp_path):
    G = build_graph(small_bbox, cache_path=tmp_path / "graph.graphml", force_rebuild=True)
    for u, v, data in G.edges(data=True):
        assert "length" in data
        assert "travel_time" in data


@pytest.mark.slow
def test_graph_caches_and_reloads(small_bbox, tmp_path):
    cache = tmp_path / "graph.graphml"
    G1 = build_graph(small_bbox, cache_path=cache)
    G2 = build_graph(small_bbox, cache_path=cache)
    assert G1.number_of_nodes() == G2.number_of_nodes()


@pytest.mark.slow
def test_amenity_index_returns_expected_categories(small_bbox, tiny_graph, tmp_path):
    index = build_amenity_index(
        small_bbox, tiny_graph, cache_path=tmp_path / "amenities.json", force_rebuild=True,
    )
    assert set(index.keys()) == {"school", "food", "health", "other", "work"}


def test_work_includes_all_shops_not_just_food():
    # "food" (the destination category) is narrowed to supermarkets/markets only, but
    # "work" must still see every shop as a potential employer, not just food shops.
    assert {"shop": True} in AMENITY_TAGS["work"]
    assert AMENITY_TAGS["food"] != [{"shop": True}]


def test_work_overlap_merges_food_school_health_without_duplicates():
    result = {
        "work": [1, 2],
        "school": [2, 3],
        "food": [4],
        "health": [5, 5],
        "other": [6],
    }
    _add_work_overlap(result)
    assert result["work"] == [1, 2, 3, 4, 5]
    assert result["school"] == [2, 3]  # other categories left untouched
    assert result["other"] == [6]      # not merged into "work"


def test_spawn_sampling_returns_valid_node_ids(tiny_graph):
    density = np.ones((10, 10))
    transform = rasterio.transform.from_bounds(36.800, -1.320, 36.830, -1.280, 10, 10)
    rng = np.random.default_rng(42)
    nodes, rows, cols = sample_spawn_nodes(density, transform, tiny_graph, n_agents=50, rng=rng)
    assert len(nodes) == 50
    assert all(n in tiny_graph.nodes for n in nodes)
    assert rows.shape == (50,) and cols.shape == (50,)
    assert np.all((rows >= 0) & (rows < density.shape[0]))
    assert np.all((cols >= 0) & (cols < density.shape[1]))


def test_load_population_raster_handles_south_up_source(tmp_path):
    """Regression test: some WorldPop exports are south-up (transform.e > 0, row 0 is
    the southern edge) rather than the usual north-up convention; rasterio's
    windows.from_bounds() requires bound args ordered to match the transform's own
    axis direction or it raises WindowError."""
    south, west, north, east = -1.0, 36.0, -0.9, 36.1
    rows, cols = 4, 4
    transform = rasterio.transform.Affine(
        (east - west) / cols, 0.0, west,
        0.0, (north - south) / rows, south,  # positive e -> south-up
    )
    array = np.arange(rows * cols, dtype=np.float32).reshape(rows, cols)  # increases south -> north
    tif_path = tmp_path / "south_up.tif"
    with rasterio.open(
        tif_path, "w", driver="GTiff",
        height=rows, width=cols, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(array[np.newaxis, :, :])

    density, _ = load_population_raster(tif_path, (south, west, north, east))
    assert density.size > 0
    assert np.isfinite(density).any()
    # The reprojected output is always north-up, so its first (northernmost) row should
    # carry the source's higher values, matching the south-up source's south->north increase.
    assert np.nanmean(density[0]) > np.nanmean(density[-1])


def test_load_population_rasters_aligns_all_to_total_grid(tmp_path):
    south, west, north, east = -1.0, 36.0, -0.9, 36.1
    bbox = (south, west, north, east)

    def _write(path, rows, cols, value):
        transform = rasterio.transform.from_bounds(west, south, east, north, cols, rows)
        array = np.full((rows, cols), value, dtype=np.float32)
        with rasterio.open(
            path, "w", driver="GTiff",
            height=rows, width=cols, count=1,
            dtype="float32", crs="EPSG:4326", transform=transform,
        ) as dst:
            dst.write(array[np.newaxis, :, :])

    total_path = tmp_path / "total.tif"
    children_path = tmp_path / "children.tif"
    _write(total_path, rows=20, cols=20, value=100.0)
    _write(children_path, rows=8, cols=8, value=30.0)  # different native resolution

    rasters, transform = load_population_rasters(
        {"total": total_path, "children": children_path}, bbox,
    )
    assert rasters["total"].shape == rasters["children"].shape
    assert np.allclose(rasters["total"], 100.0)
    assert np.allclose(rasters["children"], 30.0, atol=1.0)  # bilinear edge smoothing tolerance


def test_heat_surface_loads_and_interpolates(sample_tif):
    surface = load_heat_surface(sample_tif)
    lons = np.array([36.82, 36.85])
    lats = np.array([-1.28, -1.30])
    temps = sample_temperature(surface, lons, lats, hour=12)
    assert temps.shape == (2,)
    assert np.all(np.isfinite(temps))


def test_integrate_gtfs_creates_stops_and_transit_edges(tiny_graph, small_gtfs_dir):
    G = tiny_graph.copy()
    n_nodes_before = G.number_of_nodes()

    _integrate_gtfs(G, small_gtfs_dir)

    stop_nodes = {d["stop_id"]: n for n, d in G.nodes(data=True) if d.get("node_type") == "transit_stop"}
    assert set(stop_nodes) == {"S1", "S2", "S3"}
    assert G.number_of_nodes() == n_nodes_before + 3

    access_edges = [d for _, _, d in G.edges(data=True) if d.get("edge_type") == "access_link"]
    assert len(access_edges) == 3 * 2  # bidirectional, one pair per stop
    assert all(d["length"] > 0 for d in access_edges)

    s1, s2, s3 = stop_nodes["S1"], stop_nodes["S2"], stop_nodes["S3"]
    edge_12 = G[s1][s2][0]
    edge_23 = G[s2][s3][0]
    # ride time = arrival at the next stop minus departure from this one (excludes dwell)
    assert edge_12["travel_time"] == pytest.approx(120.0)   # 6:02:00 - 6:00:00
    assert edge_23["travel_time"] == pytest.approx(160.0)   # 6:05:00 - 6:02:20
    assert edge_12["edge_type"] == "transit"
    assert edge_12["route_id"] == "R1"
    assert edge_12["length"] > 0
    # 6:00-9:00 @300s, 9:00-15:00 @900s, in seconds-since-midnight
    assert edge_12["frequencies"] == [[21600, 32400, 300], [32400, 54000, 900]]


def test_integrate_gtfs_skips_trips_with_no_frequencies(tiny_graph, small_gtfs_dir):
    # Add a second trip with stop_times but no matching frequencies.txt row.
    stop_times_path = small_gtfs_dir / "stop_times.txt"
    stop_times_path.write_text(
        stop_times_path.read_text()
        + "T2,6:00:00,6:00:00,S3,1\n"
        + "T2,6:03:00,6:03:20,S1,2\n"
    )
    trips_path = small_gtfs_dir / "trips.txt"
    trips_path.write_text(trips_path.read_text() + "R2,DAILY,T2,Westbound,1,SH2\n")

    G = tiny_graph.copy()
    _integrate_gtfs(G, small_gtfs_dir)

    stop_nodes = {d["stop_id"]: n for n, d in G.nodes(data=True) if d.get("node_type") == "transit_stop"}
    s1, s3 = stop_nodes["S1"], stop_nodes["S3"]
    assert not G.has_edge(s3, s1)  # T2's stop-pair never got a transit edge: no frequencies for T2


def test_integrate_gtfs_frequencies_survive_graphml_roundtrip(tiny_graph, small_gtfs_dir, tmp_path):
    G = tiny_graph.copy()
    _integrate_gtfs(G, small_gtfs_dir)

    graph_path = tmp_path / "with_transit.graphml"
    ox.save_graphml(G, filepath=graph_path)
    G2 = ox.load_graphml(graph_path)

    stop_nodes = {d["stop_id"]: n for n, d in G2.nodes(data=True) if d.get("node_type") == "transit_stop"}
    s1, s2 = stop_nodes["S1"], stop_nodes["S2"]
    edge_data = G2[s1][s2][0]
    assert edge_data["frequencies"] == [[21600, 32400, 300], [32400, 54000, 900]]
    assert isinstance(edge_data["frequencies"][0][0], int)
    assert isinstance(edge_data["travel_time"], float)


def test_integrate_gtfs_accepts_zipped_feed(tiny_graph, small_gtfs_dir, tmp_path):
    import zipfile

    zip_path = tmp_path / "feed.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in small_gtfs_dir.iterdir():
            zf.write(f, arcname=f.name)

    G = tiny_graph.copy()
    _integrate_gtfs(G, zip_path)

    stop_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "transit_stop"]
    assert len(stop_nodes) == 3
