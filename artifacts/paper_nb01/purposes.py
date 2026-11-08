"""
Reconstruct each agent's trip purpose for the notebook 01 run (seed 42),
which the GeoPackage doesn't store.

model.simulation.run() draws purposes from their own random stream ("purposes"), one
demographic segment at a time in sorted (age, gender, SES) order, with each segment's
purpose weights (TravelBehaviorParams.purpose_weights, adjusted by any demographic
modifiers). Age group and gender are saved in the GeoPackage, SES is formal for every
agent in that run (no informal-settlement layer), and the default modifiers don't change
purpose weights, so the same draws can be replayed without the street graph.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nairobi_heat_abm.model.agent import DemographicParams, TravelBehaviorParams
from nairobi_heat_abm.model.simulation import (
    PURPOSE_KEYS, _RNG_STREAMS, _draw_purposes, _effective_behavior,
)

AGE_CODES = {"child": 0, "youth": 1, "adult": 2, "elderly": 3}
GENDER_CODES = {"male": 0, "female": 1}


def reconstruct_purposes(agents: pd.DataFrame, seed: int = 42,
                         behavior: TravelBehaviorParams | None = None,
                         demographics: DemographicParams | None = None) -> np.ndarray:
    """Purpose names, aligned with agents (ordered by agent_id 0..n-1)."""
    assert (agents["agent_id"].to_numpy() == np.arange(len(agents))).all()
    behavior = behavior or TravelBehaviorParams()
    demographics = demographics or DemographicParams()
    streams = np.random.SeedSequence(seed).spawn(len(_RNG_STREAMS))
    rng = np.random.default_rng(streams[_RNG_STREAMS.index("purposes")])
    age = agents["age_group"].map(AGE_CODES).to_numpy()
    gender = agents["gender"].map(GENDER_CODES).to_numpy()
    ses = np.zeros(len(agents), dtype=int)
    purposes = np.empty(len(agents), dtype=np.uint8)
    for a, g, s in sorted(set(zip(age.tolist(), gender.tolist(), ses.tolist()))):
        idx = np.where((age == a) & (gender == g) & (ses == s))[0]
        effective = _effective_behavior(behavior, demographics, a, g, s)
        purposes[idx] = _draw_purposes(effective, len(idx), rng)
    return np.array(PURPOSE_KEYS)[purposes]
