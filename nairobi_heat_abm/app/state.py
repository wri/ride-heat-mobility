from __future__ import annotations

import param

from nairobi_heat_abm.model.agent import TravelBehaviorParams


class AppState(param.Parameterized):
    """Single source of truth shared between all pages."""
    graph = param.Parameter(default=None)
    amenities = param.Parameter(default=None)
    heat_surfaces = param.List(default=[])
    active_heat_surface = param.Parameter(default=None)
    behavior_params = param.Parameter(default=TravelBehaviorParams())
    last_result = param.Parameter(default=None)   # ScenarioResult
    rdm_results = param.List(default=[])           # list[ScenarioResult]


# Module-level singleton — import this everywhere in app/
state = AppState()
