from __future__ import annotations

import panel as pn
import param

from nairobi_heat_abm.app.state import state
from nairobi_heat_abm.model.agent import TravelBehaviorParams


class BehaviorForm(param.Parameterized):
    trip_rate_mean = param.Number(default=3.2, bounds=(1.0, 8.0), step=0.1)
    trip_rate_std = param.Number(default=1.1, bounds=(0.1, 2.0), step=0.1)
    walk_only_share = param.Number(default=0.55, bounds=(0.0, 1.0), step=0.01)
    peak1_hour = param.Number(default=7.5, bounds=(5.0, 10.0), step=0.5)
    peak2_hour = param.Number(default=17.0, bounds=(14.0, 20.0), step=0.5)
    walk_speed_mean_mps = param.Number(default=1.2, bounds=(0.6, 2.0), step=0.05)
    transit_wait_tolerance_min = param.Number(default=15.0, bounds=(2.0, 40.0), step=1.0)

    @param.depends(
        "trip_rate_mean", "trip_rate_std", "walk_only_share",
        "peak1_hour", "peak2_hour", "walk_speed_mean_mps",
        "transit_wait_tolerance_min", watch=True,
    )
    def _sync_to_state(self) -> None:
        state.behavior_params = TravelBehaviorParams(
            trip_rate_mean=self.trip_rate_mean,
            trip_rate_std=self.trip_rate_std,
            walk_only_share=self.walk_only_share,
            peak1_hour=self.peak1_hour,
            peak2_hour=self.peak2_hour,
            walk_speed_mean_mps=self.walk_speed_mean_mps,
            transit_wait_tolerance_min=self.transit_wait_tolerance_min,
        )

    def view(self) -> pn.viewable.Viewable:
        return pn.Param(self, widgets={
            "trip_rate_mean": pn.widgets.FloatSlider,
            "trip_rate_std": pn.widgets.FloatSlider,
            "walk_only_share": pn.widgets.FloatSlider,
            "peak1_hour": pn.widgets.FloatSlider,
            "peak2_hour": pn.widgets.FloatSlider,
            "walk_speed_mean_mps": pn.widgets.FloatSlider,
            "transit_wait_tolerance_min": pn.widgets.FloatSlider,
        })
