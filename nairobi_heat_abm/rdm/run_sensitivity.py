"""
Behavioural sensitivity analysis — batch driver.

    python -m nairobi_heat_abm.rdm.run_sensitivity [--config config.yaml] [--n-agents N]
                                                   [--trajectories R] [--out DIR]

Reads `sensitivity:` from config.yaml, runs
  1. baseline replicates: the survey/default parameters at several seeds, giving the
     seed-to-seed (sampling) spread of each outcome at this agent count, and
  2. a Morris design over the behavioural factors in rdm/sensitivity.py,
then writes Morris indices per outcome. Everything goes to the output directory:

  factors.csv           factor names, labels, ranges, baselines, sources
  design.csv            the Morris design, unit and natural values (run_id = row)
  runs.csv              one row per finished run: run_id, kind, seed, factor values, outcomes
  morris_indices.csv    mu, mu*, 95% CI, sigma, rank per (outcome, factor)
  baseline_summary.csv  mean / SD / CV of each outcome over the baseline replicates
  run_config.json       settings used (a resume with different settings is refused)

Graph, router, amenities, population rasters, heat surface and home SES tags are
loaded once and shared by every run. Finished runs are appended to runs.csv as they
complete, so an interrupted batch resumes where it stopped.
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import logging
import os
import sys
import time
from pathlib import Path

# Use rasterio's bundled PROJ/GDAL data, not whatever PROJ_DATA/GDAL_DATA a conda
# install left in the environment (breaks CRS lookups) — must happen before rasterio
# is imported.
_rio = importlib.util.find_spec("rasterio")
if _rio and _rio.submodule_search_locations:
    _rio_dir = Path(list(_rio.submodule_search_locations)[0])
    if (_rio_dir / "proj_data").exists():
        os.environ["PROJ_DATA"] = str(_rio_dir / "proj_data")
        os.environ.pop("PROJ_LIB", None)
    if (_rio_dir / "gdal_data").exists():
        os.environ["GDAL_DATA"] = str(_rio_dir / "gdal_data")

import numpy as np
import pandas as pd
import yaml

from nairobi_heat_abm.data.heat import load_heat_surface
from nairobi_heat_abm.data.ses import load_informality, load_rwi, load_wards, tag_homes
from nairobi_heat_abm.model.agent import DemographicParams, TravelBehaviorParams
from nairobi_heat_abm.model.simulation import SimulationParams, load_context, run
from nairobi_heat_abm.rdm.sensitivity import (
    OUTCOMES, apply_factors, factors_with_ranges, morris_design, morris_indices, scenario_outcomes, to_natural,
)

log = logging.getLogger("sensitivity")


def _base_params(cfg: dict, root: Path, n_agents: int, surface) -> SimulationParams:
    b, sim, paths = cfg["bbox"], cfg["simulation"], cfg["paths"]
    wp = {k: root / v for k, v in paths["worldpop_tifs"].items()}
    return SimulationParams(
        bbox=(b["south"], b["west"], b["north"], b["east"]),
        n_agents=n_agents,
        start_hour=sim["start_hour"], end_hour=sim["end_hour"], timestep_s=sim["timestep_seconds"],
        seed=sim["default_seed"],
        behavior=TravelBehaviorParams(),
        graph_cache_path=root / paths["graph_cache"],
        amenity_cache_path=root / paths["amenity_cache"],
        worldpop_tif_path=wp["total"],
        heat_surface=surface,
        demographics=DemographicParams(population_raster_paths=wp, informal_settlement_path=None),
    )


def plan_runs(factors, n_trajectories: int, design_seed: int, base_seed: int, n_replicates: int) -> pd.DataFrame:
    """All runs: baseline replicates first, then the Morris design (trajectory t uses
    seed base_seed + t). Columns: run_id, kind, seed, trajectory, step, factor_changed,
    x0.. (unit) and one column per factor name (natural units)."""
    k = len(factors)
    names = [f.name for f in factors]
    base_unit = [(f.baseline - f.low) / (f.high - f.low) for f in factors]
    reps = pd.DataFrame({
        "kind": "baseline", "seed": base_seed + 10_000 + np.arange(n_replicates),
        "trajectory": -1, "step": -1, "factor_changed": -1,
        **{f"x{j}": base_unit[j] for j in range(k)},
    })
    design = morris_design(k, n_trajectories, seed=design_seed)
    design.insert(0, "kind", "morris")
    design.insert(1, "seed", base_seed + design["trajectory"])
    plan = pd.concat([reps, design], ignore_index=True)
    natural = to_natural(factors, plan[[f"x{j}" for j in range(k)]].to_numpy())
    for j, name in enumerate(names):
        plan[name] = natural[:, j]
    for j, f in enumerate(factors):  # replicates sit exactly on the baseline values
        plan.loc[plan["kind"] == "baseline", f.name] = f.baseline
    plan.insert(0, "run_id", np.arange(len(plan)))
    return plan


def analyse(out: Path, factors) -> pd.DataFrame:
    plan = pd.read_csv(out / "design.csv")
    runs = pd.read_csv(out / "runs.csv")
    k = len(factors)
    morris = plan[plan["kind"] == "morris"].merge(runs[["run_id", *OUTCOMES]], on="run_id", how="left")
    tables = []
    for outcome in OUTCOMES:
        if morris[outcome].notna().sum() < 2:
            continue
        # Only trajectories with every run finished, so effects aren't biased by a partial batch.
        complete = morris.groupby("trajectory")[outcome].transform(lambda s: s.notna().all())
        d = morris[complete]
        if d.empty:
            continue
        idx = morris_indices(d[["trajectory", "step", "factor_changed", *[f"x{j}" for j in range(k)]]],
                             d[outcome], factors)
        idx.insert(0, "outcome", outcome)
        tables.append(idx)
    result = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame()
    result.to_csv(out / "morris_indices.csv", index=False)

    base = runs[runs["kind"] == "baseline"]
    if not base.empty:
        summ = base[list(OUTCOMES)].agg(["mean", "std", "count"]).T
        summ["cv"] = summ["std"] / summ["mean"].abs()
        summ.index.name = "outcome"
        summ.to_csv(out / "baseline_summary.csv")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--n-agents", type=int)
    ap.add_argument("--trajectories", type=int)
    ap.add_argument("--replicates", type=int)
    ap.add_argument("--out")
    ap.add_argument("--analyse-only", action="store_true", help="recompute indices from runs.csv")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("nairobi_heat_abm").setLevel(logging.ERROR)  # per-agent no-path warnings
    cfg_path = Path(args.config).resolve()
    root = cfg_path.parent
    cfg = yaml.safe_load(cfg_path.read_text())
    sens = cfg.get("sensitivity", {})
    n_agents = args.n_agents or sens.get("n_agents", 3000)
    n_traj = args.trajectories or sens.get("trajectories", 10)
    n_reps = args.replicates if args.replicates is not None else sens.get("baseline_replicates", 5)
    out = Path(args.out) if args.out else root / sens.get("output_dir", "outputs/sensitivity")
    out.mkdir(parents=True, exist_ok=True)
    factors = factors_with_ranges(sens.get("ranges"), sens.get("factors"))

    settings = {
        "n_agents": n_agents, "trajectories": n_traj, "baseline_replicates": n_reps,
        "design_seed": sens.get("design_seed", 2026), "base_seed": sens.get("base_seed", 1000),
        "factors": {f.name: [f.low, f.high, f.baseline] for f in factors},
    }
    cfg_file = out / "run_config.json"
    if cfg_file.exists() and (out / "runs.csv").exists():
        previous = json.loads(cfg_file.read_text())
        if previous != settings:
            log.error("%s holds runs made with different settings:\n%s\nUse another --out or delete it.", out, previous)
            return 2
    cfg_file.write_text(json.dumps(settings, indent=2))

    pd.DataFrame([{"factor": f.name, "label": f.label, "low": f.low, "high": f.high, "baseline": f.baseline,
                   "source": f.source} for f in factors]).to_csv(out / "factors.csv", index=False)
    plan = plan_runs(factors, n_traj, settings["design_seed"], settings["base_seed"], n_reps)
    plan.to_csv(out / "design.csv", index=False)
    if args.analyse_only:
        analyse(out, factors)
        return 0

    runs_path = out / "runs.csv"
    done = set(pd.read_csv(runs_path)["run_id"]) if runs_path.exists() else set()
    todo = plan[~plan["run_id"].isin(done)]
    log.info("%d runs planned (%d baseline + %d Morris = %d trajectories x %d), %d already done, %d agents each",
             len(plan), n_reps, len(plan) - n_reps, n_traj, len(factors) + 1, len(done), n_agents)
    if todo.empty:
        analyse(out, factors)
        return 0

    t0 = time.perf_counter()
    b = cfg["bbox"]
    surface = load_heat_surface(root / cfg["paths"]["heat_dir"], bbox=(b["south"], b["west"], b["north"], b["east"]))
    base = _base_params(cfg, root, n_agents, surface)
    ctx = load_context(base)
    ses = cfg["paths"].get("ses", {})
    ses_layers = None
    if ses and all((root / p).exists() for p in ses.values()):
        ses_layers = dict(wards=load_wards(root / ses["wards"], base.bbox), rwi=load_rwi(root / ses["rwi"], base.bbox),
                          informality=load_informality(root / ses["informality"], base.bbox))
    log.info("Loaded heat, graph, router, rasters%s in %.0f s", " and SES layers" if ses_layers else "",
             time.perf_counter() - t0)

    tags_by_seed: dict[int, pd.DataFrame] = {}
    for i, row in enumerate(todo.itertuples(index=False), start=1):
        t = time.perf_counter()
        values = [getattr(row, f.name) for f in factors]
        params = dataclasses.replace(base, seed=int(row.seed),
                                     behavior=apply_factors(TravelBehaviorParams(), factors, values))
        result = run(params, context=ctx)
        tags = None
        if ses_layers is not None:
            # Homes come from the spawn stream alone, so they're the same for every run with this seed.
            if int(row.seed) not in tags_by_seed:
                tags_by_seed[int(row.seed)] = tag_homes(result.agent_home_lon, result.agent_home_lat, **ses_layers)
            tags = tags_by_seed[int(row.seed)]
        outcomes = scenario_outcomes(result, tags)
        record = {"run_id": int(row.run_id), "kind": row.kind, "seed": int(row.seed),
                  **{f.name: v for f, v in zip(factors, values)}, **outcomes,
                  "seconds": round(time.perf_counter() - t, 1)}
        pd.DataFrame([record]).to_csv(runs_path, mode="a", header=not runs_path.exists(), index=False)
        log.info("run %d (%d/%d, %s) %.0f s: mean %.0f °C·min, %.1f min outdoors",
                 row.run_id, i, len(todo), row.kind, record["seconds"], outcomes["mean_exposure"],
                 outcomes["mean_outdoor_min"])
        del result

    analyse(out, factors)
    log.info("Done in %.1f h; results in %s", (time.perf_counter() - t0) / 3600, out)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stderr, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
