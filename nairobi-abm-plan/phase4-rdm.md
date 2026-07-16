# Phase 4 — RDM batch analysis

Build the Latin Hypercube sampler, parallel batch runner, outcome analysis, and RDM Explorer tab. Phases 2 and 3 must be complete first.

**Completion gate:** `pytest tests/test_phase4.py -x` passes. A batch of 10 scenarios runs to completion via `ProcessPoolExecutor` and produces a valid `RDMResultSet`.

---

## 4.1 Parameter space definition

File: `rdm/sampling.py`

### Uncertainty range schema

```python
@dataclass
class ParameterRange:
    name: str              # must match a field in TravelBehaviorParams
    min_val: float
    max_val: float
    label: str             # human-readable, for display

STANDARD_RANGES: list[ParameterRange] = [
    ParameterRange("trip_rate_mean",             1.5,  5.0,  "Trip rate mean"),
    ParameterRange("trip_rate_std",              0.3,  2.0,  "Trip rate std dev"),
    ParameterRange("walk_only_share",            0.3,  0.8,  "Walk-only share"),
    ParameterRange("peak1_hour",                 6.0,  9.0,  "Morning peak (hour)"),
    ParameterRange("peak2_hour",                14.0, 19.0,  "Evening peak (hour)"),
    ParameterRange("walk_speed_mean_mps",        0.8,  1.6,  "Walk speed mean (m/s)"),
    ParameterRange("transit_wait_tolerance_min", 5.0, 30.0,  "Transit wait tolerance (min)"),
]
```

### Latin Hypercube Sampling

```python
from scipy.stats import qmc

def generate_lhs_scenarios(
    n_scenarios: int,
    ranges: list[ParameterRange],
    heat_surfaces: list[HeatSurface],
    base_params: SimulationParams,
    seed: int = 42,
) -> list[SimulationParams]:
    """
    Generate n_scenarios SimulationParams via LHS over the parameter ranges.
    Heat surfaces are assigned round-robin (or randomly if n_scenarios > len(heat_surfaces)).
    Each scenario gets a unique seed derived from the base seed.
    """
    sampler = qmc.LatinHypercube(d=len(ranges), seed=seed)
    unit_sample = sampler.random(n=n_scenarios)          # shape (n_scenarios, n_params)
    lower = np.array([r.min_val for r in ranges])
    upper = np.array([r.max_val for r in ranges])
    scaled = qmc.scale(unit_sample, lower, upper)        # shape (n_scenarios, n_params)

    scenarios = []
    for i, row in enumerate(scaled):
        behavior = TravelBehaviorParams(**{
            r.name: float(row[j]) for j, r in enumerate(ranges)
        })
        heat_idx = i % len(heat_surfaces)
        scenarios.append(dataclasses.replace(
            base_params,
            behavior=behavior,
            heat_surface=heat_surfaces[heat_idx],
            seed=seed + i,
        ))
    return scenarios
```

---

## 4.2 Batch runner

File: `rdm/batch.py`

```python
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable

def run_batch(
    scenarios: list[SimulationParams],
    max_workers: int | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[ScenarioResult | Exception]:
    """
    Run all scenarios in parallel. Returns results in the same order as input.
    Failed scenarios return the Exception rather than raising, so one failure
    doesn't abort the batch.
    progress_callback(completed, total) is called from the main thread after each result.
    """
    results = [None] * len(scenarios)
    n_workers = max_workers or max(1, os.cpu_count() - 1)

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        future_to_index = {
            pool.submit(run, scenario): i
            for i, scenario in enumerate(scenarios)
        }
        completed = 0
        for future in as_completed(future_to_index):
            i = future_to_index[future]
            try:
                results[i] = future.result()
            except Exception as e:
                results[i] = e
            completed += 1
            if progress_callback:
                progress_callback(completed, len(scenarios))

    return results
```

### Panel integration — background batch run

In `app/pages/run.py` (batch mode):

```python
def _launch_batch(n_scenarios, ranges, heat_surfaces):
    scenarios = generate_lhs_scenarios(n_scenarios, ranges, heat_surfaces, base_params)
    state.rdm_results = []

    def progress_cb(completed, total):
        pn.state.execute(lambda: _update_batch_progress(completed, total))

    def _run():
        results = run_batch(scenarios, progress_callback=progress_cb)
        valid = [r for r in results if isinstance(r, ScenarioResult)]
        pn.state.execute(lambda: _on_batch_complete(valid))

    threading.Thread(target=_run, daemon=True).start()
```

---

## 4.3 Outcome metrics

File: `rdm/analysis.py`

```python
THRESHOLD_DEFAULT_DEGC_MIN = 60.0

def compute_outcomes(result: ScenarioResult, threshold: float = THRESHOLD_DEFAULT_DEGC_MIN) -> dict:
    """
    Returns a flat dict of scalar metrics for one scenario.
    """
    exp = result.agent_exposure_degC_min
    walk_mask = result.agent_modes == MODE_WALK
    transit_mask = result.agent_modes == MODE_TRANSIT

    return {
        # Primary metrics
        "mean_exposure":     float(np.mean(exp)),
        "p90_exposure":      float(np.percentile(exp, 90)),
        "pct_above_threshold": float((exp > threshold).mean() * 100),
        "mean_dwell_min":    _mean_dwell_from_log(result.trip_log),

        # Mode gap
        "walk_mean_exposure":    float(np.mean(exp[walk_mask])) if walk_mask.any() else np.nan,
        "transit_mean_exposure": float(np.mean(exp[transit_mask])) if transit_mask.any() else np.nan,
        "mode_exposure_gap":     float(np.mean(exp[walk_mask]) - np.mean(exp[transit_mask]))
                                 if (walk_mask.any() and transit_mask.any()) else np.nan,

        # Input parameters (for sensitivity analysis)
        "param_trip_rate_mean":   result.params.behavior.trip_rate_mean,
        "param_walk_only_share":  result.params.behavior.walk_only_share,
        "param_walk_speed":       result.params.behavior.walk_speed_mean_mps,
        "param_peak1_hour":       result.params.behavior.peak1_hour,
        "param_wait_tolerance":   result.params.behavior.transit_wait_tolerance_min,
        "heat_surface_name":      result.params.heat_surface.name,
    }
```

### Outcome matrix

```python
@dataclass
class RDMResultSet:
    results: list[ScenarioResult]
    outcomes_df: pd.DataFrame    # one row per scenario, columns = metrics + params

def build_result_set(results: list[ScenarioResult], threshold: float = THRESHOLD_DEFAULT_DEGC_MIN) -> RDMResultSet:
    rows = [compute_outcomes(r, threshold) for r in results]
    df = pd.DataFrame(rows)
    df.insert(0, "scenario_id", range(len(rows)))
    return RDMResultSet(results=results, outcomes_df=df)
```

### Sensitivity analysis (Spearman rank correlation)

```python
def sensitivity_analysis(result_set: RDMResultSet) -> pd.DataFrame:
    """
    Returns DataFrame with columns: parameter, metric, correlation, abs_correlation.
    Rows sorted by abs_correlation descending.
    """
    param_cols = [c for c in result_set.outcomes_df.columns if c.startswith("param_")]
    metric_cols = ["mean_exposure", "p90_exposure", "pct_above_threshold"]
    df = result_set.outcomes_df

    rows = []
    for param in param_cols:
        for metric in metric_cols:
            valid = df[[param, metric]].dropna()
            if len(valid) < 3:
                continue
            corr, _ = scipy.stats.spearmanr(valid[param], valid[metric])
            rows.append({"parameter": param, "metric": metric,
                         "correlation": corr, "abs_correlation": abs(corr)})

    return pd.DataFrame(rows).sort_values("abs_correlation", ascending=False)
```

---

## 4.4 RDM Explorer tab

File: `app/pages/rdm_explorer.py`

### Parameter ranges section (left panel)

```python
class RDMSetupForm(param.Parameterized):
    n_scenarios = param.Integer(default=200, bounds=(10, 1000), step=10)

    # One min/max pair per standard range
    trip_rate_mean_min = param.Number(default=1.5, bounds=(0.5, 5.0))
    trip_rate_mean_max = param.Number(default=5.0, bounds=(0.5, 8.0))
    # ... repeat for each parameter in STANDARD_RANGES
```

Render as a compact two-column (min / max) grid using `pn.Param`.

### Launch + progress section

```python
launch_btn = pn.widgets.Button(name="▶ Run 200 scenarios", button_type="success")
progress_bar = pn.indicators.Progress(name="Batch", value=0, max=100, bar_color="success")
status_text = pn.pane.Markdown("Ready")
```

### Outcome matrix (centre panel)

```python
outcome_table = pn.widgets.Tabulator(
    pd.DataFrame(),
    formatters={
        "mean_exposure": {"type": "progress", "max": 120, "color": "orange"},
        "p90_exposure":  {"type": "progress", "max": 150, "color": "red"},
        "pct_above_threshold": {"type": "progress", "max": 100, "color": "red"},
    },
    selectable=True,
    pagination="local",
    page_size=15,
)
```

On row selection → populate the scenario detail view → allow "Replay this scenario" to re-run it via the Run tab.

### Parallel coordinates plot

```python
import plotly.express as px

def parallel_coords_chart(df: pd.DataFrame) -> pn.pane.Plotly:
    param_cols = [c for c in df.columns if c.startswith("param_")]
    metric_cols = ["mean_exposure", "p90_exposure", "pct_above_threshold"]
    cols = param_cols + metric_cols
    fig = px.parallel_coordinates(
        df[cols],
        color="mean_exposure",
        color_continuous_scale="YlOrRd",
        labels={c: c.replace("param_", "").replace("_", " ") for c in cols},
    )
    return pn.pane.Plotly(fig, height=280)
```

### Sensitivity chart (right panel)

```python
def sensitivity_bar_chart(sens_df: pd.DataFrame, metric: str = "mean_exposure") -> pn.pane.HoloViews:
    sub = sens_df[sens_df["metric"] == metric].sort_values("abs_correlation")
    sub["parameter"] = sub["parameter"].str.replace("param_", "").str.replace("_", " ")
    return sub.hvplot.barh(x="parameter", y="abs_correlation", title=f"Sensitivity → {metric}")
```

### Vulnerability threshold widget

```python
threshold_slider = pn.widgets.FloatSlider(
    name="Flag p90 °C·min above", start=20, end=120, step=5, value=65
)
```

On change: recompute `pct_above_threshold` column in outcomes_df, highlight rows exceeding threshold in the Tabulator.

---

## 4.5 Tests for Phase 4

File: `tests/test_phase4.py`

```python
def test_lhs_generates_correct_n_scenarios():
    scenarios = generate_lhs_scenarios(50, STANDARD_RANGES, [mock_surface], base_params)
    assert len(scenarios) == 50

def test_lhs_respects_bounds():
    scenarios = generate_lhs_scenarios(100, STANDARD_RANGES, [mock_surface], base_params)
    for s in scenarios:
        assert 1.5 <= s.behavior.trip_rate_mean <= 5.0
        assert 0.3 <= s.behavior.walk_only_share <= 0.8

def test_batch_runner_returns_all_results(mini_scenarios):
    results = run_batch(mini_scenarios, max_workers=2)
    assert len(results) == len(mini_scenarios)
    assert all(isinstance(r, ScenarioResult) for r in results)

def test_batch_runner_handles_failing_scenario(mini_scenarios_one_bad):
    results = run_batch(mini_scenarios_one_bad, max_workers=2)
    assert any(isinstance(r, Exception) for r in results)
    assert any(isinstance(r, ScenarioResult) for r in results)

def test_batch_is_deterministic(mini_scenarios):
    r1 = run_batch(mini_scenarios, max_workers=1)
    r2 = run_batch(mini_scenarios, max_workers=1)
    for a, b in zip(r1, r2):
        np.testing.assert_array_equal(
            a.agent_exposure_degC_min, b.agent_exposure_degC_min
        )

def test_compute_outcomes_returns_expected_keys(mock_result):
    out = compute_outcomes(mock_result)
    for key in ["mean_exposure", "p90_exposure", "pct_above_threshold", "mode_exposure_gap"]:
        assert key in out

def test_sensitivity_analysis_runs_on_full_result_set(mini_result_set):
    sens = sensitivity_analysis(mini_result_set)
    assert "correlation" in sens.columns
    assert len(sens) > 0

def test_progress_callback_is_called(mini_scenarios):
    calls = []
    run_batch(mini_scenarios, max_workers=2, progress_callback=lambda c, t: calls.append(c))
    assert len(calls) == len(mini_scenarios)
    assert calls[-1] == len(mini_scenarios)
```
