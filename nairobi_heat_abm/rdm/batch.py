from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable

from nairobi_heat_abm.model.simulation import SimulationParams, ScenarioResult, run


def run_batch(
    scenarios: list[SimulationParams],
    max_workers: int | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[ScenarioResult | Exception]:
    """
    Run all scenarios in parallel. Returns results in input order.
    Failed scenarios return the Exception rather than raising.
    progress_callback(completed, total) is called after each result.
    """
    results: list[ScenarioResult | Exception | None] = [None] * len(scenarios)
    n_workers = max_workers or max(1, (os.cpu_count() or 2) - 1)

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
            except Exception as exc:
                results[i] = exc
            completed += 1
            if progress_callback:
                progress_callback(completed, len(scenarios))

    return results  # type: ignore[return-value]
