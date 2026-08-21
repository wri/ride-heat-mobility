"""Phase 2 gate tests — ABM core."""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from nairobi_heat_abm.model.agent import (
    AgentPool, TravelBehaviorParams, MODE_WALK, MODE_WAIT,
    AGE_ADULT, AGE_YOUTH, GENDER_FEMALE, GENDER_MALE, SES_FORMAL, SES_INFORMAL,
    DemographicParams, ParamModifier,
    params_from_json, params_to_json,
)
from nairobi_heat_abm.model.routing import route_walk
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


def test_tick_advances_progress(tiny_graph, flat_heat_surface):
    pool = AgentPool.create(10)
    nodes = list(tiny_graph.nodes())
    u, v = nodes[0], nodes[1]
    pool.active[:] = True
    pool.mode[:] = MODE_WALK
    pool.speed_mps[:] = 1.2
    pool.edge_length[:] = 120.0  # 100-second edge at 1.2 m/s
    pool.edge_u[:] = u
    pool.edge_v[:] = v
    pool.route_edges = [[(u, v, 0)] for _ in range(10)]

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
    pool.edge_length[:] = 120.0
    pool.edge_u[:] = u
    pool.edge_v[:] = v
    pool.route_edges = [[(u, v, 0)] for _ in range(5)]

    tick(pool, tiny_graph, flat_heat_surface_30C, sim_tick=0, timestep_s=60.0, start_hour=6)
    # 30 °C × 1 minute = 30 °C·min
    assert np.all(pool.heat_exposure_degC_min[pool.active] == pytest.approx(30.0, abs=0.5))


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
