# Testing strategy

Read this before writing any test or debugging a failing test.

---

## Philosophy

- **Test gates block progress.** Each phase has a gate; do not start the next phase until the current gate passes cleanly.
- **Tests use real data where cheap, mocks where expensive.** The OSM graph is expensive to download; use a cached small-bbox fixture. Agent arrays are cheap; always use a real AgentPool.
- **Test behaviour, not implementation.** Don't assert on internal array shapes unless they are part of the documented contract.

---

## Fixture catalogue

All fixtures live in `tests/conftest.py`.

### `small_bbox`
```python
@pytest.fixture(scope="session")
def small_bbox():
    # ~2km² patch around Westlands, Nairobi
    return (-1.275, 36.800, -1.255, 36.820)
```

### `tiny_graph`
```python
@pytest.fixture
def tiny_graph():
    """10-node, 14-edge walkable graph. No OSM download needed."""
    G = nx.MultiDiGraph()
    # ... manually constructed graph with required edge attributes
    return G
```

### `flat_heat_surface`
```python
@pytest.fixture
def flat_heat_surface():
    """Uniform 25°C across Nairobi bbox, 24 hourly bands."""
    array = np.full((24, 50, 50), 25.0, dtype=np.float32)
    transform = rasterio.transform.from_bounds(36.649, -1.444, 37.104, -1.163, 50, 50)
    return HeatSurface(array=array, transform=transform,
                       hours=list(range(24)), crs="EPSG:4326", name="flat_test")
```

### `flat_heat_surface_30C`
Same as above but 30°C, used for testing exact accumulation maths.

### `sample_tif` (tmp_path fixture)
Writes a minimal synthetic GeoTIFF to a temp directory for testing `load_heat_surface`.

### `mini_simulation_params`
```python
@pytest.fixture
def mini_simulation_params(tiny_graph, flat_heat_surface, tmp_path):
    """SimulationParams for 20 agents, 2-hour run. No real data files needed."""
    # write tiny_graph to tmp_path as graphml, write minimal worldpop raster
    ...
```

### `mock_scenario_result`
A `ScenarioResult` with 100 agents, pre-populated with plausible values. Used for Results tab and RDM analysis tests without running a full simulation.

### `mini_scenarios`
List of 5 `SimulationParams` using `mini_simulation_params` with different seeds.

### `mini_result_set`
`RDMResultSet` built from 20 `mock_scenario_result` instances with varying exposure values.

---

## Running tests

```bash
# Full suite
pytest tests/ -x --tb=short

# One phase only
pytest tests/test_phase1.py -x

# With coverage
pytest tests/ --cov=nairobi_heat_abm --cov-report=term-missing

# Skip slow integration tests (marked slow)
pytest tests/ -x -m "not slow"
```

Mark tests that require a real OSM download:
```python
@pytest.mark.slow
def test_graph_builds_from_real_osm(small_bbox): ...
```

---

## Common failure modes

### "No path found" in routing tests
The `tiny_graph` fixture must have a connected component containing all test origin/destination nodes. Check fixture construction.

### Heat sampling returns NaN
The agent's interpolated position is outside the raster extent. Check that `tiny_graph` node coordinates fall within the `flat_heat_surface` bbox.

### ProcessPoolExecutor hangs
Caused by module-level Panel import in worker processes. Ensure `app/` is never imported from `model/` or `rdm/`. The simulation runner must not import Panel.

### Simulation is not deterministic
Check that `rng` is always created from `np.random.default_rng(seed)` and passed through — never use `np.random.seed()` global state.

### JSON schema validation fails on valid params
Ensure `params_to_json` always adds `schema_version: "1.0"` and uses field names matching the schema exactly.

---

## Integration test checklist (run before tagging a release)

- [ ] `python -m nairobi_heat_abm.data.graph --build` completes on real Nairobi bbox
- [ ] Single run of 5000 agents, 14-hour simulation completes in < 5 minutes
- [ ] Batch of 10 scenarios (2 workers) completes without errors
- [ ] Panel app launches and all four tabs render in a browser
- [ ] JSON export/import roundtrip preserves all parameter values exactly
- [ ] Results CSV exports with correct column headers and non-empty rows
