from __future__ import annotations

from nairobi_heat_abm.model.agent import AgentPool
from nairobi_heat_abm.model.simulation import ScenarioResult


def agent_positions_to_coords(pool: AgentPool, G, indices):
    """Return (lons, lats) arrays for the given agent indices."""
    raise NotImplementedError


def build_live_map(pool: AgentPool, G):
    raise NotImplementedError


def build_exposure_histogram(pool: AgentPool):
    raise NotImplementedError
