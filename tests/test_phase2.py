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
    _distinct_bands, _real_walk_cost, assign_routes, route_transit, route_walk,
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


def test_real_walk_cost_ignores_bogus_travel_time_on_ordinary_edges():
    """
    Regression test for a real bug: osmnx's add_edge_speeds()/add_edge_travel_times()
    (data/graph.py::build_graph()) impute VEHICLE speed for ordinary street edges even
    though the network is fetched as network_type="walk" -- so an edge's own
    "travel_time" can be wildly faster than real walking pace (observed: a 30km stretch
    showing ~33 minutes, i.e. ~54 km/h). _real_walk_cost() must recompute
    length/walk_speed_mps for anything that isn't a transit ride, ignoring that stored
    value entirely -- otherwise a route-choice comparison against a real transit cost
    would always find "walking" absurdly cheap, exactly what happened before this fix.
    """
    bogus_fast_edge = {"length": 1200.0, "travel_time": 1.0}  # travel_time implies ~1200 m/s
    assert _real_walk_cost(bogus_fast_edge, walk_speed_mps=1.2) == pytest.approx(1000.0)

    # A transit edge's travel_time IS trustworthy (real GTFS ride time) and must be used as-is.
    transit_edge = {"length": 1200.0, "travel_time": 500.0, "edge_type": "transit"}
    assert _real_walk_cost(transit_edge, walk_speed_mps=1.2) == pytest.approx(500.0)


def test_walk_route_returns_connected_edges(tiny_graph):
    nodes = list(tiny_graph.nodes())
    origin, dest = nodes[0], nodes[-1]
    edges = route_walk(tiny_graph, origin, dest, walk_speed_mps=1.2)
    assert len(edges) > 0
    for i in range(len(edges) - 1):
        assert edges[i][1] == edges[i + 1][0]


def test_route_transit_falls_back_to_walk_when_graph_has_no_transit(tiny_graph):
    nodes = list(tiny_graph.nodes())
    origin, dest = nodes[0], nodes[-1]
    bands = _distinct_bands(tiny_graph)
    assert bands == []

    transit_edges = route_transit(
        tiny_graph, origin, dest, departure_tick=0, wait_tolerance_min=15.0,
        timestep_s=60.0, bands=bands, rng=np.random.default_rng(0), walk_speed_mps=1.2,
    )
    walk_edges = route_walk(tiny_graph, origin, dest, walk_speed_mps=1.2)
    assert transit_edges == walk_edges


def test_route_transit_rides_during_a_serviced_band(transit_graph):
    nodes = sorted(transit_graph.nodes())
    origin, dest = nodes[0], nodes[2]  # same nodes stop_a/stop_b are attached to
    bands = _distinct_bands(transit_graph)

    # 6:00:00 -> falls in the 300s-headway band; riding is far cheaper than walking
    # the ~2km between these nodes even with the band's expected wait added.
    edges = route_transit(
        transit_graph, origin, dest, departure_tick=0, wait_tolerance_min=60.0,
        timestep_s=60.0, bands=bands, rng=np.random.default_rng(0), walk_speed_mps=1.2,
    )
    assert any(transit_graph[u][v][k].get("edge_type") == "transit" for u, v, k, _ in edges)
    wait_ticks_values = [w for *_, w in edges]
    assert max(wait_ticks_values) >= 0
    assert sum(1 for w in wait_ticks_values if w > 0) == 1  # only the boarding edge waits


def test_route_transit_prefers_walking_when_transit_is_not_worth_it(transit_graph):
    """
    The unified search must be able to choose NOT to use transit when walking is
    genuinely faster -- mode choice should emerge from real comparative time, not be
    forced. A very short walk between two adjacent grid nodes should never detour
    through the stops just to ride.
    """
    nodes = sorted(transit_graph.nodes())
    origin, dest = nodes[0], nodes[1]  # adjacent grid nodes, ~1 km apart -- no stops here
    bands = _distinct_bands(transit_graph)

    edges = route_transit(
        transit_graph, origin, dest, departure_tick=0, wait_tolerance_min=60.0,
        timestep_s=60.0, bands=bands, rng=np.random.default_rng(0), walk_speed_mps=1.2,
    )
    assert not any(transit_graph[u][v][k].get("edge_type") == "transit" for u, v, k, _ in edges)
    assert all(w == 0 for *_, w in edges)


def test_route_transit_wait_time_is_exponential_with_mean_headway(transit_graph):
    """
    The boarding wait is drawn from Exponential(mean=headway) -- a stochastic model of
    matatus as an irregular, memoryless (Poisson) arrival process, not the deterministic
    headway/2 a fixed-interval schedule would give. Verified statistically over many
    draws rather than as a single hardcoded value, since each draw is random.
    """
    nodes = sorted(transit_graph.nodes())
    origin, dest = nodes[0], nodes[2]
    bands = _distinct_bands(transit_graph)
    rng = np.random.default_rng(123)

    headway_s = 300.0
    n_draws = 4000
    waits_s = []
    for _ in range(n_draws):
        edges = route_transit(
            transit_graph, origin, dest, departure_tick=0, wait_tolerance_min=120.0,
            timestep_s=1.0, bands=bands, rng=rng, walk_speed_mps=1.2,
        )
        wait_ticks = max(w for *_, w in edges)
        waits_s.append(wait_ticks * 1.0)  # timestep_s=1.0 -> ticks == seconds

    mean_wait = sum(waits_s) / len(waits_s)
    # Exponential(mean=headway_s) sample mean should land close to headway_s, not
    # headway_s/2 -- generous tolerance since this is a statistical, not exact, check.
    assert headway_s * 0.85 < mean_wait < headway_s * 1.15


class _FixedDrawRNG:
    """Stand-in for np.random.Generator that always returns a fixed exponential draw --
    lets the tolerance-comparison branch be tested deterministically, independent of
    the real distribution's randomness (covered separately, statistically, above)."""

    def __init__(self, wait_s: float):
        self.wait_s = wait_s

    def exponential(self, scale: float) -> float:
        return self.wait_s


def test_route_transit_falls_back_to_walk_when_wait_exceeds_tolerance(transit_graph):
    nodes = sorted(transit_graph.nodes())
    origin, dest = nodes[0], nodes[2]
    bands = _distinct_bands(transit_graph)

    # 10:00:00 -> the 900s-headway band; force a 1000s draw against a 5-min tolerance
    departure_tick = (10 * 3600 - 6 * 3600) // 60
    edges = route_transit(
        transit_graph, origin, dest, departure_tick=departure_tick, wait_tolerance_min=5.0,
        timestep_s=60.0, bands=bands, rng=_FixedDrawRNG(1000.0), walk_speed_mps=1.2,
    )
    walk_edges = route_walk(transit_graph, origin, dest, walk_speed_mps=1.2)
    assert edges == walk_edges


def test_route_transit_falls_back_to_walk_outside_all_frequency_bands(transit_graph):
    nodes = sorted(transit_graph.nodes())
    origin, dest = nodes[0], nodes[2]
    bands = _distinct_bands(transit_graph)

    # 22:00:00 -> after the last band ends at 21:00:00
    departure_tick = (22 * 3600 - 6 * 3600) // 60
    edges = route_transit(
        transit_graph, origin, dest, departure_tick=departure_tick, wait_tolerance_min=60.0,
        timestep_s=60.0, bands=bands, rng=np.random.default_rng(0), walk_speed_mps=1.2,
    )
    walk_edges = route_walk(transit_graph, origin, dest, walk_speed_mps=1.2)
    assert edges == walk_edges


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


def test_assign_routes_no_path_sets_departure_sentinel(tiny_graph):
    """
    A routing failure must set departure_ticks to the -1 "never travels" sentinel
    (matching simulation.py's own use of it for a failed travel-probability gate) so
    simulation.run()'s tick loop never reactivates the agent at its original departure
    tick. Without this, an empty pool.route_edges would immediately satisfy
    route_index >= len(route_edges) on that tick, and the agent would be logged into
    trip_log as a bogus zero-length, zero-exposure "completed" trip.
    """
    G = tiny_graph.copy()
    G.add_node(9999, x=36.900, y=-1.200, node_type="intersection")  # isolated: no edges

    pool = AgentPool.create(1)
    nodes = sorted(tiny_graph.nodes())
    origin_nodes = np.array([nodes[0]])
    dest_nodes = np.array([9999])  # unreachable from origin_nodes[0]
    departure_ticks = np.array([5], dtype=np.int32)
    behavior = TravelBehaviorParams(walk_only_share=1.0)
    rng = np.random.default_rng(0)

    assign_routes(pool, G, origin_nodes, dest_nodes, departure_ticks, behavior, rng,
                   start_hour=6, timestep_s=60.0)

    assert pool.active[0] == False
    assert pool.route_edges[0] == []
    assert departure_ticks[0] == -1


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


def test_transit_riding_excluded_from_heat_and_time_density(tiny_graph, flat_heat_surface_30C):
    """
    MODE_TRANSIT (actually riding, not waiting) must NOT accumulate heat exposure or
    time_density -- a matatu passenger isn't exposed to ambient heat the way a walking
    or waiting pedestrian is. Only outdoor legs (walk, access-link walk, wait) count.
    """
    from nairobi_heat_abm.data.population import grid_transform_for_bbox
    from nairobi_heat_abm.model.agent import MODE_TRANSIT

    pool = AgentPool.create(5)
    nodes = list(tiny_graph.nodes())
    u, v = nodes[0], nodes[1]
    pool.active[:] = True
    pool.mode[:] = MODE_TRANSIT
    pool.speed_mps[:] = 1.2
    pool.edge_speed_mps[:] = 1.2
    pool.edge_length[:] = 120.0
    pool.edge_u[:] = u
    pool.edge_v[:] = v
    pool.route_edges = [[(u, v, 0, 0)] for _ in range(5)]

    bbox = (-1.31, 36.795, -1.27, 36.825)
    transform = grid_transform_for_bbox(bbox, shape=(40, 40))
    time_density = np.zeros((40, 40), dtype=np.float64)

    tick(
        pool, tiny_graph, flat_heat_surface_30C, sim_tick=0, timestep_s=60.0, start_hour=6,
        time_density=time_density, time_density_transform=transform,
    )
    assert np.all(pool.heat_exposure_degC_min[pool.active] == 0.0)
    assert time_density.sum() == 0.0


def test_tick_accumulates_time_density(tiny_graph, flat_heat_surface):
    from nairobi_heat_abm.data.population import grid_transform_for_bbox

    pool = AgentPool.create(4)
    nodes = list(tiny_graph.nodes())
    u, v = nodes[0], nodes[1]
    pool.active[:] = True
    pool.mode[:] = MODE_WALK
    pool.speed_mps[:] = 1.2
    pool.edge_speed_mps[:] = 1.2
    pool.edge_length[:] = 1_000_000.0  # very long edge: progress barely advances this tick
    pool.edge_u[:] = u
    pool.edge_v[:] = v
    pool.route_edges = [[(u, v, 0, 0)] for _ in range(4)]

    bbox = (-1.31, 36.795, -1.27, 36.825)  # covers tiny_graph's full 3x3 extent
    transform = grid_transform_for_bbox(bbox, shape=(40, 40))
    time_density = np.zeros((40, 40), dtype=np.float64)

    tick(
        pool, tiny_graph, flat_heat_surface, sim_tick=0, timestep_s=60.0, start_hour=6,
        time_density=time_density, time_density_transform=transform,
    )
    # 4 agents effectively standing at node u for the full 60s tick = 4 person-minutes,
    # all landing in the one grid cell nearest u (displacement this tick is negligible).
    assert time_density.sum() == pytest.approx(4.0)
    assert time_density.max() == pytest.approx(4.0)


def test_tick_without_time_density_args_is_unaffected(tiny_graph, flat_heat_surface):
    """time_density is fully optional — omitting it must not change tick()'s other effects."""
    pool = AgentPool.create(3)
    nodes = list(tiny_graph.nodes())
    u, v = nodes[0], nodes[1]
    pool.active[:] = True
    pool.mode[:] = MODE_WALK
    pool.speed_mps[:] = 1.2
    pool.edge_speed_mps[:] = 1.2
    pool.edge_length[:] = 120.0
    pool.edge_u[:] = u
    pool.edge_v[:] = v
    pool.route_edges = [[(u, v, 0, 0)] for _ in range(3)]

    tick(pool, tiny_graph, flat_heat_surface, sim_tick=0, timestep_s=60.0, start_hour=6)
    assert np.all(pool.progress[pool.active] == pytest.approx(0.6, abs=1e-4))


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


def test_simulation_populates_time_density_grid(mini_simulation_params):
    from nairobi_heat_abm.model.simulation import run
    result = run(mini_simulation_params)
    assert result.time_density.shape == mini_simulation_params.time_density_grid_shape
    assert result.time_density.sum() > 0.0
    assert result.time_density_transform is not None


def test_simulation_time_density_grid_shape_is_configurable(mini_simulation_params):
    import dataclasses
    from nairobi_heat_abm.model.simulation import run
    params = dataclasses.replace(mini_simulation_params, time_density_grid_shape=(10, 15))
    result = run(params)
    assert result.time_density.shape == (10, 15)


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
