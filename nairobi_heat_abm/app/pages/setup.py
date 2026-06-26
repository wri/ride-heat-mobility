from __future__ import annotations

import panel as pn
import param

from nairobi_heat_abm.app.state import state


class SetupPage(param.Parameterized):
    n_agents = param.Integer(default=5000, bounds=(100, 10000), step=100)
    start_hour = param.Integer(default=6, bounds=(0, 12))
    end_hour = param.Integer(default=20, bounds=(12, 24))
    seed = param.Integer(default=42)

    def view(self) -> pn.viewable.Viewable:
        raise NotImplementedError
