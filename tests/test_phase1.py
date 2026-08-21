"""Phase 1 gate tests — data infrastructure."""
from __future__ import annotations

import numpy as np
import pytest
import rasterio.transform

from nairobi_heat_abm.data.amenities import _add_work_overlap, build_amenity_index
from nairobi_heat_abm.data.graph import build_graph
from nairobi_heat_abm.data.heat import load_heat_surface, sample_temperature
from nairobi_heat_abm.data.population import sample_spawn_nodes


@pytest.mark.slow
def test_graph_builds_and_has_required_edge_attributes(small_bbox):
    G = build_graph(small_bbox, force_rebuild=True)
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
def test_amenity_index_returns_expected_categories(small_bbox, tiny_graph):
    index = build_amenity_index(small_bbox, tiny_graph, force_rebuild=True)
    assert set(index.keys()) == {"school", "shop", "health", "other", "work"}


def test_work_overlap_merges_shop_school_health_without_duplicates():
    result = {
        "work": [1, 2],
        "school": [2, 3],
        "shop": [4],
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
    nodes = sample_spawn_nodes(density, transform, tiny_graph, n_agents=50, rng=rng)
    assert len(nodes) == 50
    assert all(n in tiny_graph.nodes for n in nodes)


def test_heat_surface_loads_and_interpolates(sample_tif):
    surface = load_heat_surface(sample_tif)
    lons = np.array([36.82, 36.85])
    lats = np.array([-1.28, -1.30])
    temps = sample_temperature(surface, lons, lats, hour=12)
    assert temps.shape == (2,)
    assert np.all(np.isfinite(temps))
