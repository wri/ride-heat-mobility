"""
Global sensitivity of heat exposure to the BEHAVIOURAL parameters of the model — how
people choose destinations, when they leave, whether and how they use transit, how
fast they walk — holding geography (graph, heat surface, population, amenities) and
the transit service fixed.

Method: Morris elementary effects (Morris 1991; mu* of Campolongo et al. 2007), the
standard screening design for ranking many factors of an expensive model. Each
trajectory starts at a random point of a 4-level grid over the factor ranges and moves
one factor at a time by Delta = 2/3 of its range, so k factors cost k + 1 runs per
trajectory. All runs in a trajectory share one seed: model.simulation.run() draws each
component from its own random stream, so a step changes only what that factor touches
(common random numbers) and the difference isolates the factor's effect. Trajectories
use different seeds, so the agent sample varies across them.

Elementary effects are reported per full factor range: EE = (y(x + Delta e_i) - y(x)) /
Delta in outcome units, i.e. roughly the change in the outcome from moving the factor
from the low to the high end of its range. mu* = mean |EE| ranks importance; sigma =
SD of EE flags non-linearity or interaction with other factors.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from nairobi_heat_abm.model.agent import MODE_TRANSIT, TravelBehaviorParams
from nairobi_heat_abm.model.simulation import ScenarioResult

N_LEVELS = 4
DELTA = N_LEVELS / (2.0 * (N_LEVELS - 1))  # 2/3


def _set(field_name: str) -> Callable[[TravelBehaviorParams, float], dict]:
    return lambda base, x: {field_name: float(x)}


def _tilt_strength(base: TravelBehaviorParams, s: float) -> dict:
    # tilt ** s: 0 = departure time independent of purpose, 1 = survey tilt, >1 = sharper.
    return {"departure_purpose_tilt": {k: [float(v) ** s for v in tilt] for k, tilt in base.departure_purpose_tilt.items()}}


def _work_share(base: TravelBehaviorParams, w: float) -> dict:
    # Work trips' share of all trips; the other purposes keep their relative shares.
    others = {k: v for k, v in base.purpose_weights.items() if k != "work"}
    total = sum(others.values())
    return {"purpose_weights": {"work": float(w), **{k: (1.0 - w) * v / total for k, v in others.items()}}}


@dataclass(frozen=True)
class BehaviouralFactor:
    name: str
    label: str
    low: float
    high: float
    baseline: float
    source: str
    apply: Callable[[TravelBehaviorParams, float], dict]


# Ranges: survey-calibrated factors span the spread of the survey's own sub-fits;
# assumed factors span a plausible range around the model default. Edit via config.yaml
# (sensitivity.ranges) rather than here to keep runs reproducible from the config.
BEHAVIOURAL_FACTORS: list[BehaviouralFactor] = [
    BehaviouralFactor("destination_distance_decay", "Destination distance decay (exponent)", 1.1, 1.9, 1.5,
                      "WRI rider survey Q11 median ride time (calibration.py)",
                      _set("destination_distance_decay")),
    BehaviouralFactor("walk_time_weight", "Walking-time weight in route choice (x riding)", 2.0, 6.0, 5.0,
                      "WRI rider survey Q8 access times (calibration.py); literature 1.5-2.5", _set("walk_time_weight")),
    BehaviouralFactor("walk_share_shift_pp", "Walk share vs. JICA distance curves (+- pct points)", -15.0, 15.0, 0.0,
                      "JICA 2014 Nairobi walk-split curves (2013 person-trip survey)", _set("walk_share_shift_pp")),
    BehaviouralFactor("walk_speed_mean_mps", "Walking speed, mean (m/s)", 1.0, 1.4, 1.2,
                      "literature default", _set("walk_speed_mean_mps")),
    BehaviouralFactor("walk_speed_std_mps", "Walking speed, SD between people (m/s)", 0.05, 0.30, 0.15,
                      "assumption", _set("walk_speed_std_mps")),
    BehaviouralFactor("transit_mean_wait_min", "Mean boarding wait (min)", 4.5, 7.0, 5.65,
                      "WRI rider survey Q15; bus 5.1, matatu 6.7, 06-09 4.8, 15-21 6.4", _set("transit_mean_wait_min")),
    BehaviouralFactor("transit_wait_tolerance_min", "Wait tolerance before walking instead (min)", 5.0, 30.0, 15.0,
                      "assumption", _set("transit_wait_tolerance_min")),
    BehaviouralFactor("peak1_hour", "Morning outbound departure peak (hour)", 6.5, 8.5, 7.4,
                      "assumption; refit for round trips (departure_fit.py)", _set("peak1_hour")),
    BehaviouralFactor("peak1_weight", "Share of outbound trips in morning peak", 0.50, 0.80, 0.66,
                      "assumption; refit for round trips (departure_fit.py)", _set("peak1_weight")),
    BehaviouralFactor("peak2_hour", "Evening outbound departure peak (hour)", 15.75, 18.0, 16.75,
                      "assumption; refit for round trips (departure_fit.py)", _set("peak2_hour")),
    BehaviouralFactor("peak2_weight", "Share of outbound trips in evening peak", 0.0, 0.30, 0.14,
                      "assumption; refit for round trips (departure_fit.py)", _set("peak2_weight")),
    BehaviouralFactor("departure_tilt_strength", "Purpose-specific departure timing (x survey tilt)", 0.0, 1.5, 1.0,
                      "WRI rider survey Q9 (tilt = 1)", _tilt_strength),
    BehaviouralFactor("work_share", "Work share of trip purposes", 0.25, 0.55, 0.40,
                      "assumption", _work_share),
    BehaviouralFactor("work_end_hour_mean", "Work end time, mean (hour)", 16.0, 18.5, 17.0,
                      "assumption; Kenya public-service hours 08:00-17:00", _set("work_end_hour_mean")),
    BehaviouralFactor("school_end_hour_mean", "School end time, mean (hour)", 15.0, 16.5, 15.5,
                      "assumption; Nairobi school day 08:00-15:30", _set("school_end_hour_mean")),
    BehaviouralFactor("market_dwell_median_min", "Shopping/market dwell time, median (min)", 20.0, 120.0, 45.0,
                      "assumption", _set("market_dwell_median_min")),
    BehaviouralFactor("other_dwell_median_min", "Other-purpose dwell time, median (min)", 20.0, 180.0, 60.0,
                      "assumption (places of worship, community centres, libraries)", _set("other_dwell_median_min")),
]


def _check_baselines() -> None:
    """Factors that set a TravelBehaviorParams field directly must use its default as
    their baseline, so a recalibrated default can't silently drift from the analysis."""
    defaults = TravelBehaviorParams()
    for f in BEHAVIOURAL_FACTORS:
        if hasattr(defaults, f.name) and not np.isclose(getattr(defaults, f.name), f.baseline):
            raise AssertionError(f"{f.name}: baseline {f.baseline} != TravelBehaviorParams default {getattr(defaults, f.name)}")


_check_baselines()


def factors_with_ranges(overrides: dict[str, list[float]] | None = None,
                        only: list[str] | None = None) -> list[BehaviouralFactor]:
    """BEHAVIOURAL_FACTORS with optional {name: [low, high]} range overrides, optionally
    restricted to the names in `only`."""
    overrides = overrides or {}
    unknown = set(overrides) - {f.name for f in BEHAVIOURAL_FACTORS}
    if unknown:
        raise ValueError(f"Unknown behavioural factors in ranges: {sorted(unknown)}")
    out = []
    for f in BEHAVIOURAL_FACTORS:
        if only is not None and f.name not in only:
            continue
        if f.name in overrides:
            low, high = overrides[f.name]
            f = dataclasses.replace(f, low=float(low), high=float(high))
        if not f.low < f.high:
            raise ValueError(f"{f.name}: low must be < high")
        out.append(f)
    return out


def apply_factors(base: TravelBehaviorParams, factors: list[BehaviouralFactor], values) -> TravelBehaviorParams:
    """base with each factor set to its value (natural units)."""
    changes: dict = {}
    for f, x in zip(factors, values):
        changes.update(f.apply(base, float(x)))
    return dataclasses.replace(base, **changes)


def to_natural(factors: list[BehaviouralFactor], unit: np.ndarray) -> np.ndarray:
    lo = np.array([f.low for f in factors])
    hi = np.array([f.high for f in factors])
    return lo + np.asarray(unit) * (hi - lo)


def morris_design(k: int, r: int, seed: int = 0) -> pd.DataFrame:
    """
    r Morris trajectories over k factors in the unit cube: rows = r * (k + 1) points,
    columns trajectory, step (0 = start), factor_changed (-1 at the start) and x0..x{k-1}.
    """
    rng = np.random.default_rng(seed)
    grid = np.arange(N_LEVELS) / (N_LEVELS - 1)
    rows = []
    for t in range(r):
        x = rng.choice(grid, size=k)
        rows.append({"trajectory": t, "step": 0, "factor_changed": -1, **{f"x{j}": x[j] for j in range(k)}})
        for step, j in enumerate(rng.permutation(k), start=1):
            x = x.copy()
            x[j] = x[j] + DELTA if x[j] + DELTA <= 1.0 + 1e-12 else x[j] - DELTA
            x[j] = float(np.clip(np.round(x[j], 12), 0.0, 1.0))
            rows.append({"trajectory": t, "step": step, "factor_changed": int(j), **{f"x{i}": x[i] for i in range(k)}})
    return pd.DataFrame(rows)


def elementary_effects(design: pd.DataFrame, y: pd.Series, k: int) -> pd.DataFrame:
    """One row per (trajectory, factor): ee = dy / dx with dx in unit-range terms (+-Delta)."""
    out = []
    df = design.assign(y=y.to_numpy())
    for t, traj in df.sort_values(["trajectory", "step"]).groupby("trajectory"):
        xs = traj[[f"x{j}" for j in range(k)]].to_numpy()
        ys = traj["y"].to_numpy()
        for s in range(1, len(traj)):
            j = int(traj["factor_changed"].iloc[s])
            dx = xs[s, j] - xs[s - 1, j]
            if np.isfinite(ys[s]) and np.isfinite(ys[s - 1]) and dx != 0:
                out.append({"trajectory": t, "factor": j, "ee": (ys[s] - ys[s - 1]) / dx})
    return pd.DataFrame(out, columns=["trajectory", "factor", "ee"])


def morris_indices(design: pd.DataFrame, y: pd.Series, factors: list[BehaviouralFactor],
                   n_boot: int = 1000, seed: int = 0) -> pd.DataFrame:
    """mu, mu* (with 95% bootstrap CI over trajectories), sigma and n per factor,
    sorted by mu* descending. Units: outcome change per full factor range."""
    ee = elementary_effects(design, y, len(factors))
    rng = np.random.default_rng(seed)
    rows = []
    for j, f in enumerate(factors):
        e = ee.loc[ee["factor"] == j, "ee"].to_numpy()
        if len(e) == 0:
            continue
        boots = np.abs(e[rng.integers(0, len(e), (n_boot, len(e)))]).mean(axis=1)
        rows.append({
            "factor": f.name, "label": f.label, "n": len(e),
            "mu": e.mean(), "mu_star": np.abs(e).mean(),
            "mu_star_lo": np.quantile(boots, 0.025), "mu_star_hi": np.quantile(boots, 0.975),
            "sigma": e.std(ddof=1) if len(e) > 1 else np.nan,
        })
    out = pd.DataFrame(rows).sort_values("mu_star", ascending=False).reset_index(drop=True)
    out["rank"] = np.arange(1, len(out) + 1)
    return out


# -- outcomes -------------------------------------------------------------------------

OUTCOMES: dict[str, str] = {
    "mean_exposure": "Mean exposure per traveller (°C·min)",
    "median_exposure": "Median exposure per traveller (°C·min)",
    "p90_exposure": "90th-percentile exposure (°C·min)",
    "mean_outdoor_min": "Mean minutes outdoors per traveller",
    "mean_temp_experienced": "Mean UTCI while outdoors (°C)",
    "transit_trip_share": "Share of trips using transit",
    "walk_trip_mean_exposure": "Mean exposure, walk-only trips (°C·min)",
    "transit_trip_mean_exposure": "Mean exposure, transit trips (°C·min)",
    "rwi_gap": "Exposure gap, poorest − richest RWI quintile (°C·min)",
    "informality_gap": "Exposure gap, medium/high − low informality (°C·min)",
    "returned_share": "Share of travellers home again by end of day",
    "return_exposure_share": "Share of exposure picked up on the trip home",
}


def _mean_utci(result: ScenarioResult, trav: np.ndarray, exp: np.ndarray, mins: np.ndarray) -> float:
    """Mean raw UTCI over all travellers' outdoor minutes."""
    if not trav.any() or mins[trav].sum() <= 0:
        return float("nan")
    if len(result.agent_utci_degC_min) == len(exp):
        return float(result.agent_utci_degC_min[trav].sum() / mins[trav].sum())
    return float(exp[trav].sum() / mins[trav].sum())  # results made before the threshold


def scenario_outcomes(result: ScenarioResult, home_tags: pd.DataFrame | None = None) -> dict[str, float]:
    """
    Scalar outcomes for one run, over travellers (agents who spent any time outdoors).
    home_tags (from data/ses.py::tag_homes, aligned with the agents) adds the SES gaps:
    mean exposure of travellers in the poorest minus the richest Relative Wealth Index
    quintile (quintiles of all tagged agents), and in medium/high minus low
    morphological informality.
    """
    exp = result.agent_exposure_degC_min.astype(np.float64)
    mins = result.agent_outdoor_min.astype(np.float64)
    trav = mins > 0
    transit = result.agent_modes == MODE_TRANSIT

    def _mean(mask):
        return float(exp[mask].mean()) if mask.any() else float("nan")

    out = {
        "n_travellers": int(trav.sum()),
        "mean_exposure": _mean(trav),
        "median_exposure": float(np.median(exp[trav])) if trav.any() else float("nan"),
        "p90_exposure": float(np.percentile(exp[trav], 90)) if trav.any() else float("nan"),
        "mean_outdoor_min": float(mins[trav].mean()) if trav.any() else float("nan"),
        "mean_temp_experienced": _mean_utci(result, trav, exp, mins),
        "transit_trip_share": float(transit[trav].mean()) if trav.any() else float("nan"),
        "walk_trip_mean_exposure": _mean(trav & ~transit),
        "transit_trip_mean_exposure": _mean(trav & transit),
        "rwi_gap": float("nan"),
        "informality_gap": float("nan"),
        "returned_share": float("nan"),
        "return_exposure_share": float("nan"),
    }
    if len(result.agent_returned) == len(exp) and trav.any():
        out["returned_share"] = float(result.agent_returned[trav].mean())
        outbound = result.agent_outbound_exposure_degC_min.astype(np.float64)
        total = exp[trav].sum()
        out["return_exposure_share"] = float((exp[trav] - outbound[trav]).sum() / total) if total > 0 else float("nan")
    if home_tags is not None:
        rwi = home_tags["rwi"].to_numpy(dtype=float)
        ok = np.isfinite(rwi)
        if ok.sum() >= 50:
            q20, q80 = np.quantile(rwi[ok], [0.2, 0.8])
            out["rwi_gap"] = _mean(trav & ok & (rwi <= q20)) - _mean(trav & ok & (rwi >= q80))
        inf = home_tags["informality"].to_numpy(dtype=float)
        out["informality_gap"] = _mean(trav & (inf >= 1)) - _mean(trav & (inf == 0))
    return out
