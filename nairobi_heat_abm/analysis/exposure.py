from __future__ import annotations

import numpy as np
import pandas as pd

from nairobi_heat_abm.model.simulation import ScenarioResult


def trips_to_dataframe(result: ScenarioResult) -> pd.DataFrame:
    """Convert trip_log to a tidy DataFrame with mode/purpose labels."""
    raise NotImplementedError


def compute_mean_dwell(result: ScenarioResult) -> str:
    raise NotImplementedError
