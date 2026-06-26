from __future__ import annotations

import panel as pn

from nairobi_heat_abm.app.pages.setup import SetupPage
from nairobi_heat_abm.app.pages.run import RunPage
from nairobi_heat_abm.app.pages.results import ResultsPage
from nairobi_heat_abm.app.pages.rdm_explorer import RDMExplorerPage

pn.extension("tabulator", "plotly", sizing_mode="stretch_width")


def create_app():
    setup = SetupPage()
    run = RunPage(setup)
    results = ResultsPage()
    rdm = RDMExplorerPage(setup)

    tabs = pn.Tabs(
        ("⚙ Setup", setup.view()),
        ("▶ Run", run.view()),
        ("\U0001f4ca Results", results.view()),
        ("\U0001f300 RDM Explorer", rdm.view()),
        dynamic=True,
    )
    return pn.template.FastListTemplate(
        title="Nairobi Heat Exposure ABM",
        main=[tabs],
        sidebar_width=0,
    )


if __name__ == "__main__":
    app = create_app()
    app.servable()
    pn.serve(app, port=5006, show=True)
