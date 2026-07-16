# Phase 3 — Panel web application

Build the four-tab Panel app. The ABM core (Phase 2) must be complete before starting this phase.

**Completion gate:** `pytest tests/test_phase3.py -x` passes. `python -m nairobi_heat_abm.app` launches without error and all four tabs render with mock data.

---

## 3.1 Entry point

File: `app/main.py`

```python
import panel as pn
from app.pages.setup import SetupPage
from app.pages.run import RunPage
from app.pages.results import ResultsPage
from app.pages.rdm_explorer import RDMExplorerPage

pn.extension("tabulator", "plotly", sizing_mode="stretch_width")

def create_app():
    setup = SetupPage()
    run = RunPage(setup)
    results = ResultsPage()
    rdm = RDMExplorerPage(setup)

    tabs = pn.Tabs(
        ("⚙ Setup", setup.view()),
        ("▶ Run", run.view()),
        ("📊 Results", results.view()),
        ("🌀 RDM Explorer", rdm.view()),
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
```

---

## 3.2 Shared application state

File: `app/state.py`

```python
import param

class AppState(param.Parameterized):
    """Single source of truth shared between pages."""
    graph = param.Parameter(default=None)
    amenities = param.Parameter(default=None)
    heat_surfaces = param.List(default=[])        # list of HeatSurface
    active_heat_surface = param.Parameter(default=None)
    behavior_params = param.Parameter(default=TravelBehaviorParams())
    last_result = param.Parameter(default=None)   # ScenarioResult
    rdm_results = param.List(default=[])           # list of ScenarioResult

# Module-level singleton — import this everywhere
state = AppState()
```

---

## 3.3 Setup tab

File: `app/pages/setup.py`

### Heat surface section

```python
raster_input = pn.widgets.FileInput(accept=".tif,.tiff", multiple=True, name="")
preview_hour = pn.widgets.IntSlider(name="Preview hour", start=0, end=23, value=12)
raster_list = pn.widgets.Select(name="Active raster", options=[])
```

On file upload:
1. Save to a temp path.
2. Call `load_heat_surface(tmp_path)`.
3. Append to `state.heat_surfaces`.
4. Update `raster_list.options`.
5. Render a thumbnail map using `hvplot` or a simple matplotlib figure.

### Travel behavior section

Three mode tabs (Panel `Tabs` with `dynamic=False`):

**Widgets mode** — `app/widgets/behavior_form.py`:

```python
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
        "transit_wait_tolerance_min", watch=True
    )
    def _sync_to_state(self):
        state.behavior_params = TravelBehaviorParams(
            trip_rate_mean=self.trip_rate_mean,
            ...
        )
```

Use `pn.Param(form, widgets={...})` to render — do not build individual widgets manually.

**JSON mode**:
```python
json_editor = pn.widgets.CodeEditor(language="json", height=320)
load_btn = pn.widgets.Button(name="Load JSON", button_type="primary")
save_btn = pn.widgets.Button(name="Save JSON")
```

On load: parse JSON → validate with `jsonschema` → update `state.behavior_params` → sync form widgets.
On save: serialise `state.behavior_params` → set `json_editor.value`.

**RDM mode**: Display read-only note: "In RDM mode, behavior parameters are sampled automatically. Configure ranges in the RDM Explorer tab."

### Population parameters section

```python
n_agents_slider = pn.widgets.IntSlider(name="Agent count", start=100, end=10000, step=100, value=5000)
start_hour = pn.widgets.IntSlider(name="Start hour", start=0, end=12, value=6)
end_hour = pn.widgets.IntSlider(name="End hour", start=12, end=24, value=20)
seed_input = pn.widgets.IntInput(name="Random seed", value=42)
```

### Graph status panel

```python
def graph_status_panel():
    if state.graph is None:
        return pn.pane.Alert("Graph not loaded. Run: python -m nairobi_heat_abm.data.graph --build", alert_type="warning")
    G = state.graph
    return pn.pane.Markdown(f"""
| | |
|---|---|
| Nodes | {G.number_of_nodes():,} |
| Edges | {G.number_of_edges():,} |
| Transit stops | {sum(1 for n,d in G.nodes(data=True) if d.get('node_type')=='transit_stop'):,} |
| Amenity nodes | {sum(1 for n,d in G.nodes(data=True) if d.get('node_type')=='amenity'):,} |
""")
```

---

## 3.4 Run tab

File: `app/pages/run.py`

### Single run mode

```python
run_btn = pn.widgets.Button(name="▶ Run simulation", button_type="success")
pause_btn = pn.widgets.Button(name="⏸ Pause", disabled=True)
reset_btn = pn.widgets.Button(name="↺ Reset")
status_indicator = pn.indicators.Progress(name="Simulation", value=0, max=100)
tick_display = pn.pane.Markdown("**08:00**")
```

Run in a background thread using `pn.state.execute`:

```python
def _run_background():
    params = build_simulation_params_from_state()
    # Stream ticks — yield control back to Panel periodically
    for result in run_streaming(params):   # generator that yields partial results
        pn.state.execute(lambda r=result: _update_live_display(r))
    pn.state.execute(lambda: _on_complete())
```

### Live agent map

Use `hvplot` + `geoviews` to render agent positions as a scatter overlay on the road network. Update every N ticks (not every tick — keep UI responsive). A simple approach:

```python
def build_live_map(pool: AgentPool, G: nx.MultiDiGraph) -> pn.pane.HoloViews:
    # Sample a subset of agents for display (max 2000 points)
    active_idx = np.where(pool.active)[0]
    sample_idx = active_idx[:2000]
    lons, lats = agent_positions_to_coords(pool, G, sample_idx)
    exposure = pool.heat_exposure_degC_min[sample_idx]
    df = pd.DataFrame({"lon": lons, "lat": lats, "exposure": exposure})
    return df.hvplot.scatter(x="lon", y="lat", c="exposure", cmap="YlOrRd", ...)
```

### Live exposure histogram

```python
def build_exposure_histogram(pool: AgentPool) -> pn.pane.HoloViews:
    data = pool.heat_exposure_degC_min[pool.active]
    return pd.Series(data).hvplot.hist(bins=30, title="°C·min distribution")
```

### Live stats row

Four metric cards updating each display tick:
- Active agents: `pool.active.sum()`
- In transit: `(pool.mode == MODE_TRANSIT).sum()`
- Waiting: `(pool.mode == MODE_WAIT).sum()`
- Avg °C·min: `pool.heat_exposure_degC_min[pool.active].mean()`

---

## 3.5 Results tab

File: `app/pages/results.py`

Populated from `state.last_result` (a `ScenarioResult`).

### Summary metrics row (4 cards)

```python
def metrics_row(result: ScenarioResult) -> pn.Row:
    exposure = result.agent_exposure_degC_min
    return pn.Row(
        metric_card("Mean °C·min / trip", f"{exposure.mean():.1f}"),
        metric_card("90th pct °C·min", f"{np.percentile(exposure, 90):.1f}"),
        metric_card("% above threshold", f"{(exposure > THRESHOLD).mean() * 100:.1f}%"),
        metric_card("Mean dwell time", compute_mean_dwell(result)),
    )
```

### Exposure by mode (violin/box plot)

```python
import hvplot.pandas

def exposure_by_mode_chart(result: ScenarioResult) -> pn.pane.HoloViews:
    df = trips_to_dataframe(result)
    return df.hvplot.violin(y="heat_degC_min", by="mode_label", ...)
```

### Spatial heatmap

Aggregate mean `heat_degC_min` per origin edge. Build a GeoDataFrame of edges coloured by exposure. Render with `geoviews.Path`.

### Export buttons

```python
csv_btn = pn.widgets.FileDownload(
    callback=lambda: io.StringIO(trips_df.to_csv(index=False)),
    filename="nairobi_abm_results.csv",
    button_type="default",
    name="Export CSV",
)
```

---

## 3.6 JSON Schema

File: `schemas/travel_behavior.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "TravelBehaviorParams",
  "type": "object",
  "required": ["schema_version", "trip_rate", "mode_split"],
  "properties": {
    "schema_version": { "type": "string", "const": "1.0" },
    "trip_rate": {
      "type": "object",
      "required": ["mean", "std"],
      "properties": {
        "mean": { "type": "number", "minimum": 0.5, "maximum": 15 },
        "std":  { "type": "number", "minimum": 0 },
        "distribution": { "type": "string", "enum": ["normal", "poisson"] }
      }
    },
    "departure_time": {
      "type": "object",
      "properties": {
        "profile": { "type": "string", "enum": ["bimodal", "uniform", "custom"] },
        "peak1_hour":   { "type": "number", "minimum": 0, "maximum": 23 },
        "peak1_weight": { "type": "number", "minimum": 0, "maximum": 1  },
        "peak2_hour":   { "type": "number", "minimum": 0, "maximum": 23 },
        "peak2_weight": { "type": "number", "minimum": 0, "maximum": 1  }
      }
    },
    "mode_split": {
      "type": "object",
      "required": ["walk_only"],
      "properties": {
        "walk_only": { "type": "number", "minimum": 0, "maximum": 1 }
      }
    },
    "trip_purpose_weights": {
      "type": "object",
      "properties": {
        "work":   { "type": "number", "minimum": 0 },
        "school": { "type": "number", "minimum": 0 },
        "market": { "type": "number", "minimum": 0 },
        "other":  { "type": "number", "minimum": 0 }
      }
    },
    "walk_speed_mps": {
      "type": "object",
      "properties": {
        "mean": { "type": "number", "minimum": 0.3, "maximum": 3.0 },
        "std":  { "type": "number", "minimum": 0 }
      }
    },
    "transit_wait_tolerance_min": {
      "type": "object",
      "properties": {
        "mean": { "type": "number", "minimum": 1, "maximum": 60 },
        "std":  { "type": "number", "minimum": 0 }
      }
    }
  }
}
```

---

## 3.7 Tests for Phase 3

File: `tests/test_phase3.py`

```python
def test_behavior_form_syncs_to_state():
    form = BehaviorForm()
    form.trip_rate_mean = 4.0
    assert state.behavior_params.trip_rate_mean == 4.0

def test_json_roundtrip_via_editor(mock_state):
    # set params → save JSON → clear params → load JSON → check params match
    ...

def test_json_schema_validates_valid_params():
    p = TravelBehaviorParams()
    json_str = params_to_json(p)
    validate_against_schema(json_str)   # should not raise

def test_json_schema_rejects_invalid_params():
    bad = '{"schema_version": "1.0", "trip_rate": {"mean": -1}}'
    with pytest.raises(jsonschema.ValidationError):
        validate_against_schema(bad)

def test_app_creates_without_error():
    app = create_app()
    assert app is not None

def test_results_tab_renders_with_mock_result(mock_scenario_result):
    state.last_result = mock_scenario_result
    page = ResultsPage()
    view = page.view()
    assert view is not None
```
