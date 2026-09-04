"""Fast, no-network tests for age/gender/SES demographic sampling (data/demographics.py)."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import box

from nairobi_heat_abm.data.demographics import (
    assign_ses, draw_age_gender, draw_age_gender_spatial, load_informal_settlement_boundaries,
)
from nairobi_heat_abm.model.agent import (
    AGE_ADULT, AGE_CHILD, AGE_ELDERLY, AGE_YOUTH, DemographicParams, GENDER_FEMALE, GENDER_MALE,
    SES_FORMAL, SES_INFORMAL,
)


def test_draw_age_gender_matches_configured_shares():
    demo = DemographicParams(
        age_group_shares={AGE_CHILD: 0.2, AGE_ADULT: 0.8},
        gender_shares={GENDER_MALE: 0.3, GENDER_FEMALE: 0.7},
    )
    rng = np.random.default_rng(0)
    age_group, gender = draw_age_gender(demo, 20_000, rng)

    assert set(np.unique(age_group)) == {AGE_CHILD, AGE_ADULT}
    assert abs((age_group == AGE_CHILD).mean() - 0.2) < 0.02
    assert abs((gender == GENDER_FEMALE).mean() - 0.7) < 0.02


def test_draw_age_gender_spatial_matches_local_pixel_composition():
    # A 1x2 raster grid: col 0 is entirely elderly women, col 1 is entirely male children.
    rasters = {
        "total":    np.array([[100.0, 100.0]]),
        "children": np.array([[0.0, 100.0]]),
        "adult":    np.array([[100.0, 0.0]]),  # 20+, includes elderly
        "elderly":  np.array([[100.0, 0.0]]),
        "female":   np.array([[100.0, 0.0]]),
    }
    n_per_pixel = 500
    rows = np.zeros(2 * n_per_pixel, dtype=np.int64)
    cols = np.array([0] * n_per_pixel + [1] * n_per_pixel, dtype=np.int64)
    rng = np.random.default_rng(0)

    age_group, gender = draw_age_gender_spatial(rasters, rows, cols, rng)

    assert np.all(age_group[:n_per_pixel] == AGE_ELDERLY)
    assert np.all(gender[:n_per_pixel] == GENDER_FEMALE)
    assert np.all(age_group[n_per_pixel:] == AGE_CHILD)
    assert np.all(gender[n_per_pixel:] == GENDER_MALE)


def test_draw_age_gender_spatial_reconstructs_youth_as_residual():
    # total=100: 20 children, 50 aged 20+ (of whom 10 are 60+), so youth (15-19) = 30.
    rasters = {
        "total":    np.array([[100.0]]),
        "children": np.array([[20.0]]),
        "adult":    np.array([[50.0]]),
        "elderly":  np.array([[10.0]]),
        "female":   np.array([[40.0]]),
    }
    n = 20_000
    rows = np.zeros(n, dtype=np.int64)
    cols = np.zeros(n, dtype=np.int64)
    rng = np.random.default_rng(1)

    age_group, gender = draw_age_gender_spatial(rasters, rows, cols, rng)

    assert abs((age_group == AGE_CHILD).mean() - 0.20) < 0.01
    assert abs((age_group == AGE_YOUTH).mean() - 0.30) < 0.01
    assert abs((age_group == AGE_ADULT).mean() - 0.40) < 0.01
    assert abs((age_group == AGE_ELDERLY).mean() - 0.10) < 0.01
    assert abs((gender == GENDER_FEMALE).mean() - 0.40) < 0.01


def test_assign_ses_with_no_boundary_data_defaults_to_formal(tiny_graph):
    nodes = np.array(list(tiny_graph.nodes()))
    ses = assign_ses(nodes, tiny_graph, boundary_gdf=None)
    assert np.all(ses == SES_FORMAL)


def test_assign_ses_classifies_points_inside_boundary(tiny_graph):
    # tiny_graph is a 3x3 grid spanning lon 36.800/36.810/36.820, lat -1.300..-1.280.
    # Cover only the western column (lon 36.800) as "informal".
    boundary = gpd.GeoDataFrame(
        geometry=[box(36.800, -1.301, 36.805, -1.279)], crs="EPSG:4326",
    )
    nodes = np.array(sorted(tiny_graph.nodes()))
    ses = assign_ses(nodes, tiny_graph, boundary_gdf=boundary)

    for nid, code in zip(nodes, ses):
        lon = tiny_graph.nodes[int(nid)]["x"]
        expected = SES_INFORMAL if lon < 36.805 else SES_FORMAL
        assert code == expected


def test_load_informal_settlement_boundaries_none_path_returns_none():
    assert load_informal_settlement_boundaries(None) is None


def test_load_informal_settlement_boundaries_roundtrip(tmp_path):
    boundary = gpd.GeoDataFrame(geometry=[box(36.80, -1.30, 36.81, -1.29)], crs="EPSG:4326")
    path = tmp_path / "boundary.geojson"
    boundary.to_file(path, driver="GeoJSON")

    loaded = load_informal_settlement_boundaries(path)
    assert loaded is not None
    assert loaded.crs.to_string() == "EPSG:4326"
    assert len(loaded) == 1
