"""Phase 4 gate tests — RDM batch analysis."""
from __future__ import annotations

import numpy as np
import pytest

from nairobi_heat_abm.model.simulation import ScenarioResult
from nairobi_heat_abm.rdm.analysis import (
    RDMResultSet, build_result_set, compute_outcomes, sensitivity_analysis,
)
from nairobi_heat_abm.rdm.batch import run_batch
from nairobi_heat_abm.rdm.sampling import STANDARD_RANGES, generate_lhs_scenarios


def test_lhs_generates_correct_n_scenarios(mini_simulation_params, flat_heat_surface):
    scenarios = generate_lhs_scenarios(
        50, STANDARD_RANGES, [flat_heat_surface], mini_simulation_params
    )
    assert len(scenarios) == 50


def test_lhs_respects_bounds(mini_simulation_params, flat_heat_surface):
    scenarios = generate_lhs_scenarios(
        100, STANDARD_RANGES, [flat_heat_surface], mini_simulation_params
    )
    for s in scenarios:
        assert 1.5 <= s.behavior.trip_rate_mean <= 5.0
        assert 0.3 <= s.behavior.walk_only_share <= 0.8


def test_batch_runner_returns_all_results(mini_scenarios):
    results = run_batch(mini_scenarios, max_workers=1)
    assert len(results) == len(mini_scenarios)
    assert all(isinstance(r, ScenarioResult) for r in results)


def test_batch_is_deterministic(mini_scenarios):
    r1 = run_batch(mini_scenarios, max_workers=1)
    r2 = run_batch(mini_scenarios, max_workers=1)
    for a, b in zip(r1, r2):
        np.testing.assert_array_equal(
            a.agent_exposure_degC_min, b.agent_exposure_degC_min
        )


def test_compute_outcomes_returns_expected_keys(mock_scenario_result):
    out = compute_outcomes(mock_scenario_result)
    for key in ["mean_exposure", "p90_exposure", "pct_above_threshold", "mode_exposure_gap"]:
        assert key in out


def test_sensitivity_analysis_runs_on_full_result_set(mini_result_set):
    sens = sensitivity_analysis(mini_result_set)
    assert "correlation" in sens.columns
    assert len(sens) > 0


def test_progress_callback_is_called(mini_scenarios):
    calls = []
    run_batch(mini_scenarios, max_workers=1,
              progress_callback=lambda c, t: calls.append(c))
    assert len(calls) == len(mini_scenarios)
    assert calls[-1] == len(mini_scenarios)
