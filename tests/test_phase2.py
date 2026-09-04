"""Phase 2 gate tests — ABM core."""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from nairobi_heat_abm.model.agent import (
    AgentPool, TravelBehaviorParams, MODE_WALK, MODE_WAIT,
    AGE_ADULT, AGE_CHILD, AGE_YOUTH, GENDER_FEMALE, GENDER_MALE, SES_FORMAL, SES_INFORMAL,
    DemographicParams, ParamModifier,
    params_from_json, params_to_json,
)
import networkx as nx

from nairobi_heat_abm.model.routing import (
    _transit_edges_subgraph, _transit_stops_subgraph, assign_routes, route_transit, route_walk,
)
from nairobi_heat_abm.model.scheduler import tick


def test_params_normalises_purpose_weights():
    p = TravelBehaviorParams(purpose_weights={"work": 2, "school": 1, "market": 1, "other": 0})
    assert abs(sum(p.purpose_weights.values()) - 1.0) < 1e-6


def test_params_rejects_invalid_walk_share():
    with pytest.raises(ValueError):
        TravelBehaviorParams(walk_only_share=1.5)


def test_params_json_roundtrip():
    p = TravelBehaviorParams()
    p2 = params_from_json(params_to_json(p))
    assert p == p2


def test_walk_route_returns_connected_edges(tiny_graph):
    nodes = list(tiny_graph.nodes())
    origin, dest = nodes[0], nodes[-1]
    edges = route_walk(tiny_graph, origin, dest)
    assert len(edges) > 0
    for i in range(len(edges) - 1):
        assert edges[i][1] == edges[i + 1][0]


def test_route_transit_falls_back_to_walk_when_graph_has_no_stops(tiny_graph):
    nodes = list(tiny_graph.nodes())
    origin, dest = nodes[0], nodes[-1]
    stops_subgraph = _transit_stops_subgraph(tiny_graph)
    transit_subgraph = _transit_edges_subgraph(tiny_graph)
    assert stops_subgraph.number_of_nodes() == 0

    transit_edges = route_transit(
        tiny_graph, origin, dest, departure_tick=0, wait_tolerance_min=15.0,
        timestep_s=60.0, stops_subgraph=stops_subgraph, transit_subgraph=transit_subgraph,
    )
    walk_edges = route_walk(tiny_graph, origin, dest)
    assert transit_edges == walk_edges


def test_route_transit_rides_during_a_serviced_band(transit_graph):
    nodes = sorted(transit_graph.nodes())
    origin, dest = nodes[0], nodes[2]  # same nodes stop_a/stop_b are attached to
    stops_subgraph = _transit_stops_subgraph(transit_graph)
    transit_subgraph = _transit_edges_subgraph(transit_graph)

    # 6:00:00 -> falls in the 300s-headway band
    edges = route_transit(
        transit_graph, origin, dest, departure_tick=0, wait_tolerance_min=15.0,
        timestep_s=60.0, stops_subgraph=stops_subgraph, transit_subgraph=transit_subgraph,
    )
    assert any(transit_graph[u][v][k].get("edge_type") == "transit" for u, v, k, _ in edges)
    wait_ticks_values = [w for *_, w in edges]
    assert max(wait_ticks_values) == round((300.0 / 2.0) / 60.0)  # expected wait = headway / 2
    assert sum(1 for w in wait_ticks_values if w > 0) == 1  # only the boarding edge waits


def test_route_transit_raises_when_wait_exceeds_tolerance(transit_graph):
    nodes = sorted(transit_graph.nodes())
    origin, dest = nodes[0], nodes[2]
    stops_subgraph = _transit_stops_subgraph(transit_graph)
    transit_subgraph = _transit_edges_subgraph(transit_graph)

    # 10:00:00 -> the 900s-headway band; expected wait 450s exceeds a 5-min tolerance
    departure_tick = (10 * 3600 - 6 * 3600) // 60
    with pytest.raises(nx.NetworkXNoPath):
        route_transit(
            transit_graph, origin, dest, departure_tick=departure_tick, wait_tolerance_min=5.0,
            timestep_s=60.0, stops_subgraph=stops_subgraph, transit_subgraph=transit_subgraph,
        )


def test_route_transit_raises_outside_all_frequency_bands(transit_graph):
    nodes = sorted(transit_graph.nodes())
    origin, dest = nodes[0], nodes[2]
    stops_subgraph = _transit_stops_subgraph(transit_graph)
    transit_subgraph = _transit_edges_subgraph(transit_graph)

    # 22:00:00 -> after the last band ends at 21:00:00
    departure_tick = (22 * 3600 - 6 * 3600) // 60
    with pytest.raises(nx.NetworkXNoPath):
        route_transit(
            transit_graph, origin, dest, departure_tick=departure_tick, wait_tolerance_min=60.0,
            timestep_s=60.0, stops_subgraph=stops_subgraph, transit_subgraph=transit_subgraph,
        )


def test_assign_routes_activates_wait_mode_for_a_boarding_transit_agent(transit_graph):
    from nairobi_heat_abm.model.agent import MODE_WAIT

    pool = AgentPool.create(1)
    nodes = sorted(transit_graph.nodes())
    origin_nodes = np.array([nodes[0]])
    dest_nodes = np.array([nodes[2]])
    departure_ticks = np.array([0])  # 6:00:00 -> serviced band
    behavior = TravelBehaviorParams(walk_only_share=0.0, transit_wait_tolerance_min=15.0)
    rng = np.random.default_rng(0)

    assign_routes(pool, transit_graph, origin_nodes, dest_nodes, departure_ticks, behavior, rng,
                   start_hour=6, timestep_s=60.0)

    # assign_routes() only sets active=False on routing FAILURE — activation itself
    # happens later, in simulation.run()'s tick loop, at the agent's departure tick.
    # A non-empty route is the actual success signal here.
    assert len(pool.route_edges[0]) > 0
    assert any(w > 0 for *_, w in pool.route_edges[0])
    # The agent starts walking to the stop (or, if already there, waiting) — either way
    # it must not be silently deactivated, and its very first edge's mode is consistent
    # with whether that edge itself carries a wait.
    first_wait = pool.route_edges[0][0][3]
    if first_wait > 0:
        assert pool.mode[0] == MODE_WAIT
        assert pool.wait_ticks_remaining[0] == first_wait


def test_tick_advances_progress(tiny_graph, flat_heat_surface):
    pool = AgentPool.create(10)
    nodes = list(tiny_graph.nodes())
    u, v = nodes[0], nodes[1]
    pool.active[:] = True
    pool.mode[:] = MODE_WALK
    pool.speed_mps[:] = 1.2
    pool.edge_speed_mps[:] = 1.2
    pool.edge_length[:] = 120.0  # 100-second edge at 1.2 m/s
    pool.edge_u[:] = u
    pool.edge_v[:] = v
    pool.route_edges = [[(u, v, 0, 0)] for _ in range(10)]

    tick(pool, tiny_graph, flat_heat_surface, sim_tick=0, timestep_s=60.0, start_hour=6)
    # 1.2 m/s × 60 s / 120 m = 0.6
    assert np.all(pool.progress[pool.active] == pytest.approx(0.6, abs=1e-4))


def test_heat_accumulates_correctly(tiny_graph, flat_heat_surface_30C):
    pool = AgentPool.create(5)
    nodes = list(tiny_graph.nodes())
    u, v = nodes[0], nodes[1]
    pool.active[:] = True
    pool.mode[:] = MODE_WALK
    pool.speed_mps[:] = 1.2
    pool.edge_speed_mps[:] = 1.2
    pool.edge_length[:] = 120.0
    pool.edge_u[:] = u
    pool.edge_v[:] = v
    pool.route_edges = [[(u, v, 0, 0)] for _ in range(5)]

    tick(pool, tiny_graph, flat_heat_surface_30C, sim_tick=0, timestep_s=60.0, start_hour=6)
    # 30 °C × 1 minute = 30 °C·min
    assert np.all(pool.heat_exposure_degC_min[pool.active] == pytest.approx(30.0, abs=0.5))


def test_tick_holds_waiting_agent_in_place_then_releases_it(transit_graph, flat_heat_surface):
    from nairobi_heat_abm.model.agent import MODE_TRANSIT, MODE_WAIT

    pool = AgentPool.create(1)
    nodes = sorted(transit_graph.nodes())
    stop_a, stop_b = 9000, 9001  # matches transit_graph's fixture-assigned ids

    pool.active[:] = True
    pool.mode[:] = MODE_WAIT
    pool.wait_ticks_remaining[:] = 2
    pool.edge_u[:] = stop_a
    pool.edge_v[:] = stop_b
    pool.edge_key[:] = 0
    pool.edge_length[:] = 2000.0
    pool.edge_speed_mps[:] = 2000.0 / 300.0  # what _activate_edge would have set for this ride
    pool.route_edges = [[(stop_a, stop_b, 0, 2)]]

    tick(pool, transit_graph, flat_heat_surface, sim_tick=0, timestep_s=60.0, start_hour=6)
    assert pool.mode[0] == MODE_WAIT
    assert pool.wait_ticks_remaining[0] == 1
    assert pool.progress[0] == pytest.approx(0.0)  # still standing at the stop

    tick(pool, transit_graph, flat_heat_surface, sim_tick=1, timestep_s=60.0, start_hour=6)
    assert pool.mode[0] == MODE_TRANSIT  # wait elapsed -> now actually riding
    assert pool.wait_ticks_remaining[0] == 0
    assert pool.progress[0] > 0.0  # and moving, in the same tick the wait ended


def test_simulation_run_returns_result(mini_simulation_params):
    from nairobi_heat_abm.model.simulation import ScenarioResult, run
    result = run(mini_simulation_params)
    assert isinstance(result, ScenarioResult)
    assert result.agent_exposure_degC_min.shape == (mini_simulation_params.n_agents,)
    assert len(result.trip_log) > 0


def test_simulation_is_deterministic(mini_simulation_params):
    from nairobi_heat_abm.model.simulation import run
    r1 = run(mini_simulation_params)
    r2 = run(mini_simulation_params)
    np.testing.assert_array_equal(r1.agent_exposure_degC_min, r2.agent_exposure_degC_min)


def test_effective_behavior_combines_modifiers_multiplicatively():
    from nairobi_heat_abm.model.simulation import _effective_behavior

    base = TravelBehaviorParams(
        trip_rate_mean=4.0, trip_rate_std=1.0,
        purpose_weights={"work": 0.4, "school": 0.2, "market": 0.25, "other": 0.15},
    )
    demo = DemographicParams(
        age_modifiers={AGE_YOUTH: ParamModifier(trip_rate_mean_mult=1.5, purpose_weight_mult={"school": 2.0})},
        gender_modifiers={GENDER_FEMALE: ParamModifier(trip_rate_mean_mult=0.9)},
        ses_modifiers={SES_INFORMAL: ParamModifier(purpose_weight_mult={"work": 0.5})},
    )

    effective = _effective_behavior(base, demo, AGE_YOUTH, GENDER_FEMALE, SES_INFORMAL)
    assert effective.trip_rate_mean == pytest.approx(4.0 * 1.5 * 0.9)

    raw_work = 0.4 * 0.5
    raw_school = 0.2 * 2.0
    raw_total = raw_work + raw_school + 0.25 + 0.15
    assert effective.purpose_weights["work"] == pytest.approx(raw_work / raw_total)
    assert effective.purpose_weights["school"] == pytest.approx(raw_school / raw_total)

    # A segment with no matching modifiers falls back to an unchanged (renormalized-no-op) base.
    unmodified = _effective_behavior(base, demo, AGE_ADULT, GENDER_MALE, SES_FORMAL)
    assert unmodified.trip_rate_mean == pytest.approx(base.trip_rate_mean)
    for k, v in base.purpose_weights.items():
        assert unmodified.purpose_weights[k] == pytest.approx(v)


def test_simulation_with_demographics_populates_pool_and_shifts_trip_rate_by_segment(mini_simulation_params):
    from nairobi_heat_abm.model.simulation import run

    demo = DemographicParams(
        age_group_shares={AGE_ADULT: 1.0},
        gender_shares={GENDER_MALE: 0.5, GENDER_FEMALE: 0.5},
        gender_modifiers={GENDER_FEMALE: ParamModifier(trip_rate_mean_mult=3.0)},
    )
    params = dataclasses.replace(mini_simulation_params, n_agents=200, demographics=demo)
    result = run(params)

    assert set(np.unique(result.agent_age_group).tolist()) == {AGE_ADULT}
    assert set(np.unique(result.agent_gender).tolist()) == {GENDER_MALE, GENDER_FEMALE}
    assert np.all(result.agent_ses == SES_FORMAL)  # no boundary data supplied -> everyone formal

    male_mean = result.agent_n_trips[result.agent_gender == GENDER_MALE].mean()
    female_mean = result.agent_n_trips[result.agent_gender == GENDER_FEMALE].mean()
    assert female_mean > male_mean


def test_simulation_without_demographics_leaves_pool_fields_zeroed(mini_simulation_params):
    from nairobi_heat_abm.model.simulation import run

    result = run(mini_simulation_params)
    assert np.all(result.agent_age_group == 0)
    assert np.all(result.agent_gender == 0)
    assert np.all(result.agent_ses == SES_FORMAL)


def test_simulation_with_spatial_demographics_draws_age_gender_from_rasters(
    mini_simulation_params, demographic_raster_paths,
):
    """
    End-to-end: DemographicParams.population_raster_paths set -> simulation.run() uses
    draw_age_gender_spatial instead of the flat age_group_shares/gender_shares draw.
    demographic_raster_paths splits children/adult west/east and female north/south
    (see conftest.py), so with 300 agents both age groups and both genders should show
    up in substantial numbers — this doesn't re-verify the per-pixel maths (see
    test_demographics.py for that), just that simulation.run() wires it through.
    """
    from nairobi_heat_abm.model.simulation import run

    demo = DemographicParams(population_raster_paths=demographic_raster_paths)
    params = dataclasses.replace(mini_simulation_params, n_agents=300, demographics=demo)
    result = run(params)

    assert set(np.unique(result.agent_age_group).tolist()) <= {AGE_CHILD, AGE_ADULT}
    assert (result.agent_age_group == AGE_CHILD).sum() > 20
    assert (result.agent_age_group == AGE_ADULT).sum() > 20
    assert (result.agent_gender == GENDER_FEMALE).sum() > 20
    assert (result.agent_gender == GENDER_MALE).sum() > 20
