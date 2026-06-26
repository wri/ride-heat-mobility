from __future__ import annotations

import panel as pn
import param

from nairobi_heat_abm.app.state import state


class ResultsPage(param.Parameterized):
    def view(self) -> pn.viewable.Viewable:
        raise NotImplementedError
