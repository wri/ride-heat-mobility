from __future__ import annotations

import panel as pn
import param

from nairobi_heat_abm.app.pages.setup import SetupPage
from nairobi_heat_abm.app.state import state


class RunPage(param.Parameterized):
    def __init__(self, setup: SetupPage, **params):
        super().__init__(**params)
        self.setup = setup

    def view(self) -> pn.viewable.Viewable:
        raise NotImplementedError
