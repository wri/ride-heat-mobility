"""Phase 2 gate tests — ABM core."""
from __future__ import annotations

import numpy as np
import pytest

from nairobi_heat_abm.model.agent import (
    AgentPool, TravelBehaviorParams, MODE_WALK, MODE_WAIT,
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
