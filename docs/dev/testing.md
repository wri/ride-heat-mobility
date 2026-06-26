# Testing

→ [Back to index](index.md)

## Philosophy

- **Phase gates block progress.** Do not start phase N+1 until `pytest tests/test_phaseN.py -x` passes.
- **Tests use real data where cheap, mocks where expensive.** The OSM graph requires a network download; use the cached `small_bbox` fixture. Agent arrays are cheap; always use a real `AgentPool`.
- **Test behaviour, not implementation.** Assert on documented contracts (output shapes, invariants), not on internal array structure unless that structure is itself the contract.

## Running the suite

```bash
# Full suite, stop on first failure
pytest tests/ -x --tb=short

# One phase only
pytest tests/test_phase1.py -x

# Skip network-dependent tests
pytest tests/ -x -m "not slow"

# With coverage
pytest tests/ --cov=nairobi_heat_abm --cov-report=term-missing

# Parallel execution
pytest tests/ -n auto
```

## Fixture catalogue

All fixtures are defined in [`tests/conftest.py`](../../tests/conftest.py).

### Geographic

| Fixture | Scope | Description |
|---|---|---|
| `small_bbox` | session | `(-1.275, 36.800, -1.255, 36.820)` — ~2 km² patch around Westlands; requires network |
| `tiny_graph` | function | 3×3 grid, 9 nodes, all required edge attributes; no network needed |

### Heat surfaces

| Fixture | Scope | Description |
|---|---|---|
| `flat_heat_surface` | function | 25 °C uniform, 24 hourly bands, full Nairobi bbox |
| `flat_heat_surface_30C` | function | 30 °C uniform; used for exact accumulation maths |
| `sample_tif` | function | Writes a synthetic single-band GeoTIFF to `tmp_path` |

### Simulation

| Fixture | Scope | Description |
|---|---|---|
| `mini_simulation_params` | function | 20 agents, 2-hour run, `tiny_graph`, no real data files |
| `mock_scenario_result` | function | 100-agent `ScenarioResult` with pre-populated plausible values |
| `mini_scenarios` | function | 5 × `mini_simulation_params` with different seeds |
| `mini_result_set` | function | `RDMResultSet` from 20 mock results with varying exposures |

## Slow-test marking

Mark any test that requires a network call or the raw data files:

```python
@pytest.mark.slow
def test_graph_builds_from_real_osm(small_bbox): ...
```

## Common failure modes

<!-- TODO: expand as issues are encountered during implementation -->

**"No path found" in routing tests** — `tiny_graph` must be connected between all test origin/destination nodes.

**Heat sampling returns NaN** — Agent interpolated position is outside the raster extent. Check that `tiny_graph` node coordinates fall inside `flat_heat_surface`'s bounding box (36.649–37.104 lon, −1.444–(−1.163) lat).

**`ProcessPoolExecutor` hangs** — A module-level Panel import is being triggered in worker processes. Ensure `app/` is never imported from `model/` or `rdm/`.

**Simulation not deterministic** — An `np.random.seed()` global call exists somewhere. All randomness must flow through the `rng = np.random.default_rng(seed)` passed to each function.
