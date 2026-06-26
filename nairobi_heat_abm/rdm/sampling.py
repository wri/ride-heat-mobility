from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
from scipy.stats import qmc

from nairobi_heat_abm.data.heat import HeatSurface
from nairobi_heat_abm.model.agent import TravelBehaviorParams
from nairobi_heat_abm.model.simulation import SimulationParams


@dataclass
class ParameterRange:
    name: str       # must match a field in TravelBehaviorParams
    min_val: float
    max_val: float
    label: str      # human-readable, for display


STANDARD_RANGES: list[ParameterRange] = [
    ParameterRange("trip_rate_mean",             1.5,  5.0,  "Trip rate mean"),
    ParameterRange("trip_rate_std",              0.3,  2.0,  "Trip rate std dev"),
    ParameterRange("walk_only_share",            0.3,  0.8,  "Walk-only share"),
    ParameterRange("peak1_hour",                 6.0,  9.0,  "Morning peak (hour)"),
    ParameterRange("peak2_hour",                14.0, 19.0,  "Evening peak (hour)"),
    ParameterRange("walk_speed_mean_mps",        0.8,  1.6,  "Walk speed mean (m/s)"),
    ParameterRange("transit_wait_tolerance_min", 5.0, 30.0,  "Transit wait tolerance (min)"),
]


def generate_lhs_scenarios(
    n_scenarios: int,
    ranges: list[ParameterRange],
    heat_surfaces: list[HeatSurface],
    base_params: SimulationParams,
    seed: int = 42,
) -> list[SimulationParams]:
    """
    Generate n_scenarios SimulationParams via Latin Hypercube Sampling.
    Heat surfaces are assigned round-robin. Each scenario gets a unique seed.
    """
    sampler = qmc.LatinHypercube(d=len(ranges), seed=seed)
    unit_sample = sampler.random(n=n_scenarios)
    lower = np.array([r.min_val for r in ranges])
    upper = np.array([r.max_val for r in ranges])
    scaled = qmc.scale(unit_sample, lower, upper)

    scenarios = []
    for i, row in enumerate(scaled):
        behavior = TravelBehaviorParams(**{
            r.name: float(row[j]) for j, r in enumerate(ranges)
        })
        heat_idx = i % len(heat_surfaces)
        scenarios.append(dataclasses.replace(
            base_params,
            behavior=behavior,
            heat_surface=heat_surfaces[heat_idx],
            seed=seed + i,
        ))
    return scenarios
