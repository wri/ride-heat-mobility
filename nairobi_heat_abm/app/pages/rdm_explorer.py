from __future__ import annotations

import panel as pn
import param

from nairobi_heat_abm.app.pages.setup import SetupPage
from nairobi_heat_abm.app.state import state
from nairobi_heat_abm.rdm.sampling import STANDARD_RANGES


class RDMExplorerPage(param.Parameterized):
    n_scenarios = param.Integer(default=200, bounds=(10, 1000), step=10)

    def __init__(self, setup: SetupPage, **params):
        super().__init__(**params)
        self.setup = setup

    def view(self) -> pn.viewable.Viewable:
        raise NotImplementedError
