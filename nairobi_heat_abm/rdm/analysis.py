from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import scipy.stats

from nairobi_heat_abm.model.agent import MODE_WALK, MODE_TRANSIT
from nairobi_heat_abm.model.simulation import ScenarioResult

THRESHOLD_DEFAULT_DEGC_MIN = 60.0


def compute_outcomes(
    result: ScenarioResult,
    threshold: float = THRESHOLD_DEFAULT_DEGC_MIN,
) -> dict:
    """Return a flat dict of scalar metrics for one scenario."""
    exp = result.agent_exposure_degC_min
    walk_mask = result.agent_modes == MODE_WALK
    transit_mask = result.agent_modes == MODE_TRANSIT

    walk_mean = float(np.mean(exp[walk_mask])) if walk_mask.any() else float("nan")
    transit_mean = float(np.mean(exp[transit_mask])) if transit_mask.any() else float("nan")
    mode_gap = (walk_mean - transit_mean) if (walk_mask.any() and transit_mask.any()) else float("nan")

    return {
        "mean_exposure":          float(np.mean(exp)),
        "p90_exposure":           float(np.percentile(exp, 90)),
        "pct_above_threshold":    float((exp > threshold).mean() * 100),
        "mean_dwell_min":         _mean_dwell_from_log(result.trip_log),
        "walk_mean_exposure":     walk_mean,
        "transit_mean_exposure":  transit_mean,
        "mode_exposure_gap":      mode_gap,
        "param_trip_rate_mean":   result.params.behavior.trip_rate_mean,
        "param_walk_only_share":  result.params.behavior.walk_only_share,
        "param_walk_speed":       result.params.behavior.walk_speed_mean_mps,
        "param_peak1_hour":       result.params.behavior.peak1_hour,
        "param_wait_tolerance":   result.params.behavior.transit_wait_tolerance_min,
        "heat_surface_name":      result.params.heat_surface.name,
    }


def _mean_dwell_from_log(trip_log: list[dict]) -> float:
    if not trip_log:
        return float("nan")
    return float(np.mean([t.get("heat_degC_min", 0.0) for t in trip_log]))


@dataclass
class RDMResultSet:
    results: list[ScenarioResult]
    outcomes_df: pd.DataFrame  # one row per scenario, columns = metrics + params


def build_result_set(
    results: list[ScenarioResult],
    threshold: float = THRESHOLD_DEFAULT_DEGC_MIN,
) -> RDMResultSet:
    rows = [compute_outcomes(r, threshold) for r in results]
    df = pd.DataFrame(rows)
    df.insert(0, "scenario_id", range(len(rows)))
    return RDMResultSet(results=results, outcomes_df=df)


def sensitivity_analysis(result_set: RDMResultSet) -> pd.DataFrame:
    """
    Spearman rank correlation between input parameters and outcome metrics.
    Returns DataFrame sorted by abs_correlation descending.
    """
    param_cols = [c for c in result_set.outcomes_df.columns if c.startswith("param_")]
    metric_cols = ["mean_exposure", "p90_exposure", "pct_above_threshold"]
    df = result_set.outcomes_df

    rows = []
    for param in param_cols:
        for metric in metric_cols:
            valid = df[[param, metric]].dropna()
            if len(valid) < 3:
                continue
            corr, _ = scipy.stats.spearmanr(valid[param], valid[metric])
            rows.append({
                "parameter": param,
                "metric": metric,
                "correlation": corr,
                "abs_correlation": abs(corr),
            })

    return pd.DataFrame(rows).sort_values("abs_correlation", ascending=False).reset_index(drop=True)
