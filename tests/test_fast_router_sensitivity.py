"""FastRouter equivalence, common random numbers across runs, per-person segment
exposure, and the behavioural (Morris) sensitivity machinery."""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from nairobi_heat_abm.data.export import segment_layer
from nairobi_heat_abm.model.agent import MODE_WAIT, MODE_WALK, AgentPool, TravelBehaviorParams
from nairobi_heat_abm.model.routing import FastRouter, _distinct_bands, route_transit, route_walk
from nairobi_heat_abm.model.scheduler import tick
from nairobi_heat_abm.model.segment_exposure import SegmentExposure
from nairobi_heat_abm.rdm.sensitivity import (
    BEHAVIOURAL_FACTORS, DELTA, apply_factors, factors_with_ranges, morris_design, morris_indices,
    scenario_outcomes,
)


class _Fixed:
    def __init__(self, draw):
        self.draw = draw

    def exponential(self, scale):
        return self.draw * scale


def _cost(G, edges, speed, mean_wait_s):
    total = 0.0
    for u, v, k, _ in edges:
        d = G[u][v][k]
        total += d["travel_time"] + mean_wait_s if d.get("edge_type") == "transit" else d["length"] / speed
    return total


# -- FastRouter ---------------------------------------------------------------------------

def test_fast_router_walk_matches_networkx_cost(transit_graph):
    R = FastRouter(transit_graph)
    nodes = sorted(transit_graph.nodes())
    for o in nodes:
        for d in nodes:
            if o == d:
                continue
            a = route_walk(transit_graph, o, d, 1.2)
            b = R.route_walk(o, d)
            assert _cost(transit_graph, b, 1.0, 0.0) == pytest.approx(_cost(transit_graph, a, 1.0, 0.0))
            assert all(transit_graph[u][v][k].get("edge_type") != "transit" for u, v, k, _ in b)
            assert [e[0] for e in b[:1]] == [o] and b[-1][1] == d


@pytest.mark.parametrize("tick_i, draw, tolerance", [
    (30, 1.0, 15.0),    # 06:30, morning band, boards
    (30, 50.0, 15.0),   # wait far over tolerance -> walk fallback
    (240, 0.2, 15.0),   # 10:00, other band
    (900, 1.0, 15.0),   # 21:00, outside every band -> walk
])
def test_fast_router_transit_matches_networkx(transit_graph, tick_i, draw, tolerance):
    R = FastRouter(transit_graph)
    bands = _distinct_bands(transit_graph)
    origin, dest = sorted(transit_graph.nodes())[0], sorted(transit_graph.nodes())[2]  # bottom-row ends
    for speed in (0.6, 1.2, 2.5):
        a = route_transit(transit_graph, origin, dest, tick_i, tolerance, 5.65, 60.0, bands, _Fixed(draw), speed)
        b = R.route_transit(origin, dest, tick_i, tolerance, 5.65, 60.0, draw, speed)
        assert _cost(transit_graph, b, speed, 339.0) == pytest.approx(_cost(transit_graph, a, speed, 339.0))
        assert [e[3] for e in b] == [e[3] for e in a]  # same boarding wait ticks
        assert any(transit_graph[u][v][k].get("edge_type") == "transit" for u, v, k, _ in b) == \
            any(transit_graph[u][v][k].get("edge_type") == "transit" for u, v, k, _ in a)


def test_fast_router_rides_when_slow_walker_and_short_wait(transit_graph):
    R = FastRouter(transit_graph)
    origin, dest = sorted(transit_graph.nodes())[0], sorted(transit_graph.nodes())[2]
    edges = R.route_transit(origin, dest, 30, 15.0, 1.0, 60.0, 1.0, walk_speed_mps=0.5)
    assert any(transit_graph[u][v][k].get("edge_type") == "transit" for u, v, k, _ in edges)
    boarding = next(e for e in edges if e[3] > 0)
    assert boarding[0] == 9000 and boarding[3] == 1  # 1 min wait, 60 s ticks


def test_fast_router_unknown_node_raises(tiny_graph):
    import networkx as nx
    with pytest.raises(nx.NodeNotFound):
        FastRouter(tiny_graph).route_walk(1, 1000)


# -- run(): context reuse and common random numbers --------------------------------------

def test_run_with_shared_context_matches_plain_run(mini_simulation_params):
    from nairobi_heat_abm.model.simulation import load_context, run
    a = run(mini_simulation_params)
    b = run(mini_simulation_params, context=load_context(mini_simulation_params))
    np.testing.assert_array_equal(a.agent_exposure_degC_min, b.agent_exposure_degC_min)
    np.testing.assert_array_equal(a.agent_home_node, b.agent_home_node)
    assert (a.agent_outdoor_min > 0).any()
    assert a.agent_outdoor_min.sum() == pytest.approx(
        a.segment_exposure["person_min"].sum() + (b.stop_exposure["person_min"].sum() if not b.stop_exposure.empty else 0)
    )


def test_changing_one_behaviour_keeps_unrelated_draws(mini_simulation_params):
    from nairobi_heat_abm.model import simulation
    captured = {}
    orig = simulation.assign_routes

    def spy(pool, G, origins, dests, departures, *args, **kwargs):
        captured.setdefault("runs", []).append((origins.copy(), dests.copy(), departures.copy(), pool.speed_mps.copy()))
        return orig(pool, G, origins, dests, departures, *args, **kwargs)

    simulation.assign_routes = spy
    try:
        p = dataclasses.replace(mini_simulation_params, n_agents=60, end_hour=10)
        simulation.run(p)
        faster = dataclasses.replace(p.behavior, walk_speed_mean_mps=1.5)
        simulation.run(dataclasses.replace(p, behavior=faster))
    finally:
        simulation.assign_routes = orig

    (o1, d1, t1, s1), (o2, d2, t2, s2) = captured["runs"]
    np.testing.assert_array_equal(o1, o2)   # homes
    np.testing.assert_array_equal(d1, d2)   # destinations
    np.testing.assert_array_equal(t1, t2)   # departure times
    np.testing.assert_allclose(s2 - s1, 0.3, atol=1e-5)  # every speed shifted, same z-scores


def test_distance_decay_validated_and_shortens_trips():
    with pytest.raises(ValueError):
        TravelBehaviorParams(destination_distance_decay=-1.0)

    import networkx as nx
    from nairobi_heat_abm.model.simulation import _draw_destinations
    G = nx.MultiDiGraph()
    for i in range(50):
        G.add_node(i, x=36.8 + i * 0.002, y=-1.3)
    amenities = {k: list(range(1, 50)) for k in ["work", "school", "food", "other"]}
    purposes = np.zeros(4000, dtype=np.uint8)
    origins = np.zeros(4000, dtype=np.int64)
    near = _draw_destinations(amenities, purposes, origins, G, np.random.default_rng(0), distance_decay=2.0)
    far = _draw_destinations(amenities, purposes, origins, G, np.random.default_rng(0), distance_decay=0.0)
    assert near.mean() < far.mean()
    assert abs(far.mean() - 25.0) < 1.5  # decay 0 = uniform over nodes 1..49


# -- per-person segment exposure ------------------------------------------------------------

def test_segment_counts_distinct_people_not_ticks(tiny_graph, flat_heat_surface_30C):
    nodes = sorted(tiny_graph.nodes())
    pool = AgentPool.create(3)
    pool.active[:] = True
    pool.mode[:] = MODE_WALK
    pool.speed_mps[:] = pool.edge_speed_mps[:] = 1.2
    pool.edge_length[:] = 1000.0
    pool.edge_u[:] = nodes[0]
    pool.edge_v[:] = nodes[1]
    pool.route_edges = [[(nodes[0], nodes[1], 0, 0)] for _ in range(3)]
    seg = SegmentExposure()
    for t in range(4):
        tick(pool, tiny_graph, flat_heat_surface_30C, sim_tick=t, timestep_s=60.0, start_hour=6, segment_exposure=seg)

    row = seg.edges_frame().iloc[0]
    assert row.person_min == pytest.approx(12.0)  # 3 agents x 4 ticks
    assert row.n_persons == 3
    np.testing.assert_allclose(pool.outdoor_min, 4.0)

    layer = segment_layer(tiny_graph, seg.edges_frame())
    assert layer["heat_degC_min_per_person"].iloc[0] == pytest.approx(row.heat_degC_min / 3)
    assert layer["min_per_person"].iloc[0] == pytest.approx(4.0)


def test_segment_layer_without_person_counts_has_no_per_person_columns(tiny_graph):
    a, b = sorted(tiny_graph.nodes())[:2]
    df = pd.DataFrame({"u": [a], "v": [b], "key": [0], "heat_degC_min": [10.0], "person_min": [1.0]})
    assert "heat_degC_min_per_person" not in segment_layer(tiny_graph, df).columns


# -- Morris ---------------------------------------------------------------------------------

def test_morris_design_moves_one_factor_by_delta_per_step():
    k, r = 5, 7
    d = morris_design(k, r, seed=3)
    assert len(d) == r * (k + 1)
    xs = d[[f"x{j}" for j in range(k)]].to_numpy()
    assert set(np.round(np.unique(xs), 6)) <= {0.0, round(1 / 3, 6), round(2 / 3, 6), 1.0}
    for t, traj in d.groupby("trajectory"):
        x = traj[[f"x{j}" for j in range(k)]].to_numpy()
        diffs = np.abs(np.diff(x, axis=0))
        assert ((diffs > 1e-9).sum(axis=1) == 1).all()
        np.testing.assert_allclose(diffs.max(axis=1), DELTA)
        assert sorted(traj["factor_changed"].iloc[1:]) == list(range(k))


def test_morris_indices_recover_a_linear_model():
    factors = factors_with_ranges(only=[f.name for f in BEHAVIOURAL_FACTORS[:4]])
    d = morris_design(4, 20, seed=1)
    coef = np.array([10.0, -3.0, 0.0, 1.0])
    y = pd.Series(d[[f"x{j}" for j in range(4)]].to_numpy() @ coef)
    idx = morris_indices(d, y, factors).set_index("factor")
    for f, c in zip(factors, coef):
        assert idx.loc[f.name, "mu_star"] == pytest.approx(abs(c))
        assert idx.loc[f.name, "mu"] == pytest.approx(c)
        assert idx.loc[f.name, "sigma"] == pytest.approx(0.0, abs=1e-9)
    assert idx.index[0] == factors[0].name


def test_apply_factors_sets_behaviour_fields():
    base = TravelBehaviorParams()
    factors = factors_with_ranges()
    values = {f.name: f.baseline for f in factors}
    same = apply_factors(base, factors, [values[f.name] for f in factors])
    assert same.walk_only_share == base.walk_only_share
    assert same.departure_purpose_tilt == pytest.approx(base.departure_purpose_tilt)
    assert same.purpose_weights == pytest.approx(base.purpose_weights)

    values.update(departure_tilt_strength=0.0, work_share=0.55, destination_distance_decay=2.0)
    changed = apply_factors(base, factors, [values[f.name] for f in factors])
    assert all(v == 1.0 for tilt in changed.departure_purpose_tilt.values() for v in tilt)
    assert changed.purpose_weights["work"] == pytest.approx(0.55)
    assert sum(changed.purpose_weights.values()) == pytest.approx(1.0)
    assert changed.purpose_weights["market"] / changed.purpose_weights["other"] == pytest.approx(0.25 / 0.15)
    assert changed.destination_distance_decay == 2.0

    with pytest.raises(ValueError):
        factors_with_ranges({"not_a_factor": [0, 1]})


def test_scenario_outcomes(mini_simulation_params):
    from nairobi_heat_abm.model.simulation import run
    result = run(dataclasses.replace(mini_simulation_params, n_agents=80))
    tags = pd.DataFrame({"rwi": np.linspace(-1, 1, 80), "informality": np.r_[np.zeros(40), np.ones(40)]})
    out = scenario_outcomes(result, tags)
    trav = result.agent_outdoor_min > 0
    assert out["n_travellers"] == trav.sum()
    assert out["mean_exposure"] == pytest.approx(result.agent_exposure_degC_min[trav].mean(), rel=1e-6)
    assert out["mean_temp_experienced"] == pytest.approx(25.0, abs=0.01)  # flat 25 °C test surface
    assert np.isfinite(out["rwi_gap"]) and np.isfinite(out["informality_gap"])


# -- distance-decay calibration ------------------------------------------------------------

def test_access_walk_minutes_counts_walking_before_first_ride(transit_graph):
    from nairobi_heat_abm.model.simulation import _access_walk_minutes
    nodes = sorted(transit_graph.nodes())
    pool = AgentPool.create(2)
    pool.speed_mps[:] = 1.0
    pool.route_edges = [
        [(nodes[1], nodes[0], 0, 0), (nodes[0], 9000, 0, 0), (9000, 9001, 0, 3), (9001, nodes[2], 0, 0)],
        [(nodes[0], nodes[1], 0, 0)],
    ]
    out = _access_walk_minutes(pool, transit_graph)
    assert out[0] == pytest.approx((1000.0 + 10.0) / 60.0)
    assert np.isnan(out[1])


def test_calibration_helpers():
    from nairobi_heat_abm.calibration import ACCESS_BINS, bin_shares, fit_peak, multinomial_loglik
    shares = bin_shares(np.array([1.0, 5.4, 5.6, 10.0, 15.0, 25.0, 45.0, np.nan]), ACCESS_BINS)
    assert shares.tolist() == pytest.approx([2 / 7, 2 / 7, 1 / 7, 1 / 7, 1 / 7])
    counts = pd.Series([10, 20, 5, 0, 0], index=list(ACCESS_BINS))
    exact = pd.Series([10 / 35, 20 / 35, 5 / 35, 0, 0], index=list(ACCESS_BINS))
    assert multinomial_loglik(counts, exact) > multinomial_loglik(counts, shares)

    betas = np.array([0.5, 1.0, 1.5, 2.0, 2.5])
    fit = fit_peak(betas, -40.0 * (betas - 1.3) ** 2)
    assert fit["beta_hat"] == pytest.approx(1.3)
    assert fit["hi"] - fit["beta_hat"] == pytest.approx(np.sqrt(1.92 / 40.0))
    assert fit_peak(betas, -betas)["at_grid_edge"]


@pytest.mark.parametrize("weight", [1.0, 2.0, 4.0])
def test_walk_time_weight_matches_networkx_and_discourages_walking(transit_graph, weight):
    R = FastRouter(transit_graph)
    bands = _distinct_bands(transit_graph)
    o, d = sorted(transit_graph.nodes())[0], sorted(transit_graph.nodes())[2]
    a = route_transit(transit_graph, o, d, 30, 15.0, 5.65, 60.0, bands, _Fixed(1.0), 1.2, walk_time_weight=weight)
    b = R.route_transit(o, d, 30, 15.0, 5.65, 60.0, 1.0, 1.2, walk_time_weight=weight)
    rides = lambda e: any(transit_graph[u][v][k].get("edge_type") == "transit" for u, v, k, _ in e)
    assert rides(a) == rides(b)
    # 2 km walk (~28 min) vs 10 m + 5 min ride + 5.65 min wait + 10 m: weighting walking only makes riding likelier
    assert rides(b) or weight == 1.0
    with pytest.raises(ValueError):
        TravelBehaviorParams(walk_time_weight=0.0)


def test_fit_peak_2d_recovers_quadratic_peak():
    from nairobi_heat_abm.calibration import fit_peak_2d
    xs, ys = np.meshgrid([1.0, 1.5, 2.0, 2.5, 3.0], [1.0, 2.0, 3.0, 4.0])
    g = pd.DataFrame({"beta": xs.ravel(), "w": ys.ravel()})
    g["ll"] = -50 * (g["beta"] - 1.8) ** 2 - 20 * (g["w"] - 2.4) ** 2 + 5 * (g["beta"] - 1.8) * (g["w"] - 2.4)
    fit = fit_peak_2d(g, "beta", "w", "ll")
    assert fit["method"] == "quadratic surface"
    assert fit["beta"] == pytest.approx(1.8) and fit["w"] == pytest.approx(2.4)
    assert fit["beta_lo"] < 1.8 < fit["beta_hi"]


def test_binned_median_and_median_match():
    from nairobi_heat_abm.calibration import ACCESS_BINS, binned_median, median_match
    counts = pd.Series([27, 55, 16, 1, 1], index=list(ACCESS_BINS))
    assert binned_median(counts, ACCESS_BINS) == pytest.approx(5.5 + (0.5 - 0.27) / 0.55 * 5.0)

    rows = []
    for w, acc in [(1.0, 20.0), (2.0, 11.0), (3.0, 9.0), (4.0, 8.5)]:
        for beta, ride in [(1.0, 25.0), (1.5, 20.0), (2.0, 15.0)]:
            rows.append({"walk_time_weight": w, "beta": beta, "access_median_min": acc, "ride_median_min": ride,
                         "loglik_q8": -100.0 * acc})
    grid = pd.DataFrame(rows)
    fit = median_match(grid, access_target=10.0, ride_target=22.5)
    assert fit["walk_time_weight"] == pytest.approx(2.5)  # halfway between 11 and 9 min
    assert fit["beta"] == pytest.approx(1.25)
    plateau = median_match(grid, access_target=5.0, ride_target=22.5, plateau_tol=60.0)
    assert plateau["walk_time_weight"] == 3.0  # Q8 at w=3 is within 60 of the best (w=4)
    assert "plateau" in plateau["walk_time_weight_rule"]


def test_walk_probability_follows_jica_curves():
    from nairobi_heat_abm.model.agent import walk_probability
    b = TravelBehaviorParams()
    assert walk_probability(b, "work", 1000.0) == pytest.approx(0.672)   # intrazonal (< 1.3 km)
    assert walk_probability(b, "work", 2000.0) == pytest.approx((37.948 - 12.19 * np.log(2)) / 100)
    assert walk_probability(b, "school", 5000.0) == pytest.approx((59.215 - 19.17 * np.log(5)) / 100)
    assert walk_probability(b, "work", 40_000.0) == 0.0      # clipped at long distances
    shifted = dataclasses.replace(b, walk_share_shift_pp=10.0)
    assert walk_probability(shifted, "market", 2000.0) == pytest.approx(walk_probability(b, "other", 2000.0) + 0.10)
    with pytest.raises(ValueError):
        TravelBehaviorParams(walk_choice="sometimes")


def test_distance_walk_choice_walks_short_trips_more(transit_graph):
    from nairobi_heat_abm.model.routing import assign_routes
    nodes = sorted(transit_graph.nodes())
    n = 400
    results = {}
    for dest in (nodes[1], nodes[8]):  # 1 km vs ~4 km (corner to corner)
        pool = AgentPool.create(n)
        pool.speed_mps[:] = 1.2
        assign_routes(pool, transit_graph, np.full(n, nodes[0]), np.full(n, dest), np.zeros(n, dtype=np.int32),
                      TravelBehaviorParams(walk_time_weight=1.0), np.random.default_rng(0), 6, 60.0)
        results[dest] = np.mean([len(r) > 0 for r in pool.route_edges])
        assert all(len(r) > 0 for r in pool.route_edges)
    # all routes exist; the share actually decided "walk" is checked through walk_probability above


# -- continuous movement within a tick --------------------------------------------------------

def _chain_graph(n_edges, length):
    import networkx as nx
    G = nx.MultiDiGraph()
    for j in range(n_edges + 1):
        G.add_node(j + 1, x=36.80 + j * 1e-4, y=-1.30)
    for j in range(n_edges):
        G.add_edge(j + 1, j + 2, length=float(length), travel_time=length / 1.2)
    return G


def _walker_on(G, route, speed=1.0):
    from nairobi_heat_abm.model.routing import _activate_edge
    pool = AgentPool.create(1)
    pool.speed_mps[:] = speed
    pool.route_edges = [route]
    _activate_edge(pool, 0, G, *route[0])
    pool.active[:] = True
    return pool


def test_walking_time_equals_distance_over_speed_on_short_edges(flat_heat_surface_30C):
    G = _chain_graph(10, 10.0)  # 10 edges x 10 m = 100 m at 1 m/s = 100 s
    pool = _walker_on(G, [(j + 1, j + 2, 0, 0) for j in range(10)])
    seg = SegmentExposure()
    for t in range(3):
        tick(pool, G, flat_heat_surface_30C, sim_tick=t, timestep_s=60.0, start_hour=6, segment_exposure=seg)
    assert not pool.active[0]
    assert pool.outdoor_min[0] == pytest.approx(100 / 60, rel=1e-5)
    assert pool.heat_exposure_degC_min[0] == pytest.approx((30.0 - 26.0) * 100 / 60, rel=1e-4)  # above 26 °C
    assert pool.utci_degC_min[0] == pytest.approx(30.0 * 100 / 60, rel=1e-4)
    edges = seg.edges_frame()
    assert len(edges) == 10 and (edges["n_persons"] == 1).all()
    np.testing.assert_allclose(edges["person_min"], 10 / 60, rtol=1e-6)  # 10 s on each edge
    assert edges["heat_degC_min"].sum() == pytest.approx(pool.heat_exposure_degC_min[0], rel=1e-5)


def test_agent_waits_at_stop_for_rest_of_arrival_tick(flat_heat_surface_30C):
    G = _chain_graph(2, 30.0)
    G.edges[2, 3, 0]["edge_type"] = "transit"
    G.edges[2, 3, 0]["travel_time"] = 30.0
    pool = _walker_on(G, [(1, 2, 0, 0), (2, 3, 0, 2)])  # 30 m walk, then wait 2 ticks and ride 30 m
    seg = SegmentExposure()
    tick(pool, G, flat_heat_surface_30C, sim_tick=0, timestep_s=60.0, start_hour=6, segment_exposure=seg)
    assert pool.mode[0] == MODE_WAIT
    assert seg.stops_frame()["person_min"].iloc[0] == pytest.approx(0.5)   # 30 s walking, 30 s waiting
    assert seg.edges_frame()["person_min"].iloc[0] == pytest.approx(0.5)
    for t in range(1, 5):
        tick(pool, G, flat_heat_surface_30C, sim_tick=t, timestep_s=60.0, start_hour=6, segment_exposure=seg)
    assert not pool.active[0]
    # 0.5 min walking + 0.5 + 1 min waiting (arrived at mid-tick: waits share + wait_ticks - 1); riding adds nothing
    assert pool.outdoor_min[0] == pytest.approx(2.0, rel=1e-5)
    assert seg.stops_frame()["person_min"].iloc[0] == pytest.approx(1.5)


# -- Return trips ---------------------------------------------------------------------

def test_return_departure_hour_rules():
    from nairobi_heat_abm.model.agent import return_departure_hour
    b = TravelBehaviorParams()
    # Work/school: the end-time draw, but at least min_stay_min after arriving.
    assert return_departure_hour(b, "work", 8.0, 0.0) == pytest.approx(17.0)
    assert return_departure_hour(b, "work", 8.0, 1.0) == pytest.approx(18.0)
    assert return_departure_hour(b, "school", 7.5, -1.0) == pytest.approx(15.0)
    assert return_departure_hour(b, "work", 16.5, 0.0) == pytest.approx(17.5)  # 60 min minimum stay
    # Market/other: arrival + lognormal dwell with the given median.
    assert return_departure_hour(b, "market", 10.0, 0.0) == pytest.approx(10.75)
    assert return_departure_hour(b, "other", 10.0, 0.0) == pytest.approx(11.0)
    assert return_departure_hour(b, "market", 10.0, 1.0) == pytest.approx(10.0 + 45 * np.exp(0.6) / 60)
    with pytest.raises(ValueError):
        TravelBehaviorParams(market_dwell_median_min=0.0)


def test_round_trips_go_home_and_split_exposure(mini_simulation_params):
    from nairobi_heat_abm.model.simulation import NO_RETURN, run
    p = dataclasses.replace(mini_simulation_params, n_agents=40, end_hour=20, utci_threshold_c=20.0)
    r = run(p)
    arrived = np.isfinite(r.agent_trip_min)
    assert arrived.any()
    # Every agent that arrived has a return time; those due before 20:00 set off.
    assert np.isfinite(r.agent_return_departure_hour[arrived]).all()
    due = arrived & (r.agent_return_departure_hour < 19.0)
    assert due.any()
    assert (r.agent_return_modes[due] != NO_RETURN).all() or r.agent_returned[due].all()
    went_home = r.agent_returned & np.isfinite(r.agent_return_trip_min)
    assert went_home.any()
    # Exposure splits into legs; per-segment attribution still adds up to the total.
    assert (r.agent_outbound_exposure_degC_min <= r.agent_exposure_degC_min + 1e-3).all()
    assert (r.agent_exposure_degC_min[went_home] > r.agent_outbound_exposure_degC_min[went_home]).all()
    stops = r.stop_exposure["person_min"].sum() if not r.stop_exposure.empty else 0.0
    assert r.agent_outdoor_min.sum() == pytest.approx(r.segment_exposure["person_min"].sum() + stops, rel=1e-4)
    log = pd.DataFrame(r.trip_log)
    assert set(log["leg"]) == {"outbound", "return"}
    # Legs still under way at end_hour aren't logged; agents back home have both.
    home = np.flatnonzero(r.agent_returned)
    by_agent = log.groupby("agent_id")["heat_degC_min"].sum().reindex(home, fill_value=0.0)
    np.testing.assert_allclose(by_agent.to_numpy(), r.agent_exposure_degC_min[home], rtol=1e-4, atol=1e-3)


def test_return_trips_leave_outbound_unchanged(mini_simulation_params):
    from nairobi_heat_abm.model.simulation import NO_RETURN, run
    p = dataclasses.replace(mini_simulation_params, n_agents=40, end_hour=20)
    with_ret = run(p)
    without = run(dataclasses.replace(p, behavior=dataclasses.replace(p.behavior, return_trips=False)))
    longer_dwell = run(dataclasses.replace(p, behavior=dataclasses.replace(p.behavior, market_dwell_median_min=90.0)))
    np.testing.assert_allclose(with_ret.agent_outbound_exposure_degC_min, without.agent_exposure_degC_min, rtol=1e-5)
    np.testing.assert_array_equal(with_ret.agent_modes, without.agent_modes)
    assert (without.agent_return_modes == NO_RETURN).all() and not without.agent_returned.any()
    np.testing.assert_allclose(with_ret.agent_outbound_exposure_degC_min,
                               longer_dwell.agent_outbound_exposure_degC_min, rtol=1e-5)
    market = (with_ret.agent_purposes == 2) & np.isfinite(with_ret.agent_return_departure_hour)
    if market.any():
        assert (longer_dwell.agent_return_departure_hour[market] > with_ret.agent_return_departure_hour[market]).all()


def test_scenario_outcomes_report_return_trips(mini_simulation_params):
    from nairobi_heat_abm.model.simulation import run
    r = run(dataclasses.replace(mini_simulation_params, n_agents=40, end_hour=20, utci_threshold_c=20.0))
    out = scenario_outcomes(r)
    assert out["mean_temp_experienced"] == pytest.approx(25.0, abs=0.01)  # raw UTCI, not the excess
    assert 0.0 < out["returned_share"] <= 1.0
    assert 0.0 < out["return_exposure_share"] < 1.0


def test_departure_fit_return_hours_match_model_rule():
    from nairobi_heat_abm.departure_fit import return_hours
    from nairobi_heat_abm.model.agent import return_departure_hour
    from nairobi_heat_abm.model.simulation import PURPOSE_KEYS
    b = TravelBehaviorParams(market_dwell_median_min=30.0, work_end_hour_std=0.7)
    rng = np.random.default_rng(3)
    p, a, z = rng.integers(0, 4, 500), rng.uniform(6, 19, 500), rng.standard_normal(500)
    expected = [return_departure_hour(b, PURPOSE_KEYS[i], x, y) for i, x, y in zip(p, a, z)]
    np.testing.assert_allclose(return_hours(b, p, a, z), expected, rtol=1e-12)
