"""
Joint calibration of two behavioural parameters to the WRI Nairobi rider survey:
TravelBehaviorParams.walk_time_weight (how heavily walking counts in route choice) and
destination_distance_decay (beta, how strongly destination choice favours near places).

    python -m nairobi_heat_abm.calibration [--survey WRI_Survey_DATA_23_09_2023.xlsx]
        [--betas 1 1.5 2 2.5 3] [--walk-weights 1 1.5 2 2.5 3 4]
        [--n-agents 3000] [--seeds 2] [--out outputs/calibration]

Targets (bus and matatu respondents — the modes the model's transit represents):
- Q8 "How long did it take you to access this stage?", among riders who walked to the
  stage. Model: on trips that ride transit, the walk from home to the first boarding
  stop (ScenarioResult.agent_access_walk_min). Mainly set by walk_time_weight: with
  walking counted like riding (1.0), simulated riders walk past nearby stops to reach
  more direct routes.
- Q11 "How long does this trip usually take you?". Model: boarding the first vehicle to
  leaving the last (agent_ride_min). Mainly set by beta, through trip length. Taken as
  the time on board because the question is asked about "this mode" at the stage after
  the access question; whether respondents included access and waiting is not known, so
  the door-to-door log-likelihood is also recorded for comparison.

Fit: multinomial log-likelihood of each question's binned answers under the model's
share of transit trips per bin, summed over the two questions, over a beta x weight grid
(seeds pooled per cell to damp simulation noise). The estimate is the peak of a quadratic
surface fitted around the best cell; the intervals are Wald 95% intervals from its
curvature. They reflect survey sample size only, not simulation noise or model
structure, so they are optimistic.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# Survey bins. Answers are whole minutes with gaps between bins ("Less than 5", "6 - 10"),
# so model minutes are split at the midpoints, as in the wait-time fit.
ACCESS_BINS = {"Less than 5 mins": (0.0, 5.5), "6 - 10 mins": (5.5, 10.5), "11 - 20 mins": (10.5, 20.5),
               "21 - 30 mins": (20.5, 30.5), "More than 30 mins": (30.5, np.inf)}
TRIP_BINS = {"1 - 10 mins": (0.0, 10.5), "11 - 20 mins": (10.5, 20.5), "21 - 30 mins": (20.5, 30.5),
             "31 - 40 mins": (30.5, 40.5), "More than 40 mins": (40.5, np.inf)}

_COL_MODE = "Which Mode of Transport are you Using?"
_COL_ACCESS_MODE = "7. How did you access your bus stage?"
_COL_ACCESS_TIME = "8. How long did it take you to access this stage?"
_COL_TRIP_TIME = "11. How long does this trip usually take you?"

log = logging.getLogger("calibration")


def survey_counts(path: str | Path) -> dict[str, pd.Series]:
    """Binned answer counts for bus/matatu riders (the modes the model's transit
    represents): 'access' = Q8 among those who walked to the stage; 'trip' = Q11."""
    df = pd.read_excel(path, sheet_name="WRI_Survey_Cleaned_DATA")
    bus_matatu = df[_COL_MODE].str.contains("Bus|Matatu", case=False, na=False)
    walked = df[_COL_ACCESS_MODE].eq("Walking")
    access = df.loc[bus_matatu & walked, _COL_ACCESS_TIME].value_counts().reindex(list(ACCESS_BINS), fill_value=0)
    trip = df.loc[bus_matatu, _COL_TRIP_TIME].value_counts().reindex(list(TRIP_BINS), fill_value=0)
    return {"access": access, "trip": trip}


def bin_shares(minutes: np.ndarray, bins: dict[str, tuple[float, float]]) -> pd.Series:
    m = np.asarray(minutes, dtype=float)
    m = m[np.isfinite(m)]
    counts = [((m >= lo) & (m < hi)).sum() for lo, hi in bins.values()]
    return pd.Series(np.asarray(counts, float) / max(len(m), 1), index=list(bins))


def multinomial_loglik(counts: pd.Series, shares: pd.Series, floor: float = 1e-4) -> float:
    """sum(n_bin * log p_bin), with p floored so an empty model bin isn't -inf."""
    p = np.maximum(shares.to_numpy(float), floor)
    p = p / p.sum()
    return float((counts.to_numpy(float) * np.log(p)).sum())


def fit_peak(betas: np.ndarray, loglik: np.ndarray) -> dict[str, float]:
    """1-D version: quadratic through the best grid point and its neighbours; argmax and
    the likelihood-ratio 95% interval (loglik within 1.92 of the max). Falls back to the
    best grid point (interval NaN) at the grid edge or if the curve isn't concave."""
    i = int(np.nanargmax(loglik))
    out = {"beta_hat": float(betas[i]), "lo": float("nan"), "hi": float("nan"), "at_grid_edge": i in (0, len(betas) - 1)}
    if out["at_grid_edge"]:
        return out
    sel = slice(max(i - 2, 0), min(i + 3, len(betas)))
    a, b, c = np.polyfit(betas[sel], loglik[sel], 2)
    if a >= 0:
        return out
    beta_hat = -b / (2 * a)
    half = np.sqrt(1.92 / -a)
    return {"beta_hat": float(beta_hat), "lo": float(beta_hat - half), "hi": float(beta_hat + half), "at_grid_edge": False}


def fit_peak_2d(grid: pd.DataFrame, x: str, y: str, z: str) -> dict:
    """
    Quadratic surface z ~ x + y + x^2 + xy + y^2 fitted to the grid points within two
    grid steps of the best one; returns its maximum and Wald 95% intervals from the
    curvature (log-likelihood Hessian). Falls back to the best grid point (intervals NaN)
    if the surface isn't concave there or its peak falls outside the grid.
    """
    xs, ys = np.sort(grid[x].unique()), np.sort(grid[y].unique())
    best = grid.loc[grid[z].idxmax()]
    out = {x: float(best[x]), y: float(best[y]), f"{x}_lo": np.nan, f"{x}_hi": np.nan,
           f"{y}_lo": np.nan, f"{y}_hi": np.nan, "method": "best grid point"}
    ix, iy = int(np.searchsorted(xs, best[x])), int(np.searchsorted(ys, best[y]))
    near = grid[grid[x].isin(xs[max(ix - 2, 0):ix + 3]) & grid[y].isin(ys[max(iy - 2, 0):iy + 3])]
    if len(near) < 6:
        return out
    X = np.column_stack([np.ones(len(near)), near[x], near[y], near[x] ** 2, near[x] * near[y], near[y] ** 2])
    c = np.linalg.lstsq(X, near[z].to_numpy(float), rcond=None)[0]
    H = np.array([[2 * c[3], c[4]], [c[4], 2 * c[5]]])
    if np.any(np.linalg.eigvalsh(H) >= 0):
        return out
    peak = np.linalg.solve(H, -c[1:3])
    if not (xs[0] <= peak[0] <= xs[-1] and ys[0] <= peak[1] <= ys[-1]):
        return out
    se = np.sqrt(np.diag(np.linalg.inv(-H)))
    return {x: float(peak[0]), y: float(peak[1]),
            f"{x}_lo": float(peak[0] - 1.96 * se[0]), f"{x}_hi": float(peak[0] + 1.96 * se[0]),
            f"{y}_lo": float(peak[1] - 1.96 * se[1]), f"{y}_hi": float(peak[1] + 1.96 * se[1]),
            "method": "quadratic surface"}


def binned_median(counts: pd.Series, bins: dict[str, tuple[float, float]]) -> float:
    """Median of binned answers, interpolating linearly within the bin that holds it."""
    n = counts.to_numpy(float)
    cum = np.cumsum(n) / n.sum()
    i = int(np.searchsorted(cum, 0.5))
    lo, hi = list(bins.values())[i]
    if not np.isfinite(hi):
        return lo
    below = cum[i - 1] if i > 0 else 0.0
    return lo + (0.5 - below) / (cum[i] - below) * (hi - lo)


def median_match(grid: pd.DataFrame, access_target: float, ride_target: float, plateau_tol: float = 10.0) -> dict:
    """
    The adopted calibration (see module docstring and docs/methodology/travel-behaviour.md):

    - walk_time_weight: the smallest grid weight whose median access walk (averaged over
      beta, on which it barely depends) reaches access_target, interpolated between grid
      weights; if no weight reaches it, the smallest weight whose best Q8 log-likelihood
      (over beta) is within plateau_tol of the overall best — i.e. where Q8 stops
      improving by more than simulation noise.
    - beta: at that weight (nearest grid row), the beta at which the median ride time
      equals ride_target, interpolated linearly between grid betas.
    """
    acc = grid.groupby("walk_time_weight")["access_median_min"].mean().sort_index()
    ww = None
    below = acc[acc <= access_target]
    if len(below):
        w1 = below.index[0]
        prev = acc[acc.index < w1]
        if len(prev):
            w0 = prev.index[-1]
            ww = float(w0 + (acc[w0] - access_target) / (acc[w0] - acc[w1]) * (w1 - w0))
        else:
            ww = float(w1)
        rule = "median access walk = survey median"
    else:
        prof = grid.groupby("walk_time_weight")["loglik_q8"].max().sort_index()
        ww = float(prof[prof >= prof.max() - plateau_tol].index[0])
        rule = f"Q8 log-likelihood plateau (within {plateau_tol:g} of best); survey median access not reached"
    row_w = acc.index[np.argmin(np.abs(acc.index.to_numpy(float) - ww))]
    ride = grid[grid["walk_time_weight"] == row_w].set_index("beta")["ride_median_min"].sort_index()
    # ride median falls as beta rises: interpolate on the reversed (increasing) series
    beta = float(np.interp(ride_target, ride.to_numpy()[::-1], ride.index.to_numpy(float)[::-1]))
    at_edge = ride_target > ride.max() or ride_target < ride.min()
    return {"beta": beta, "walk_time_weight": ww, "walk_time_weight_rule": rule,
            "beta_from_grid_row_walk_time_weight": float(row_w), "beta_at_grid_edge": bool(at_edge),
            "access_target_min": access_target, "ride_target_min": ride_target,
            "model_access_median_at_weight": float(np.interp(ww, acc.index.to_numpy(float), acc.to_numpy()))}


def main(argv: list[str] | None = None) -> int:
    from nairobi_heat_abm.rdm.run_sensitivity import _base_params  # also fixes PROJ/GDAL env
    import yaml
    from nairobi_heat_abm.data.heat import load_heat_surface
    from nairobi_heat_abm.model.agent import MODE_TRANSIT
    from nairobi_heat_abm.model.simulation import load_context, run

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--survey", default="WRI_Survey_DATA_23_09_2023.xlsx")
    ap.add_argument("--betas", type=float, nargs="+", default=[1.0, 1.5, 2.0, 2.5, 3.0])
    ap.add_argument("--walk-weights", type=float, nargs="+", default=[1.0, 1.5, 2.0, 2.5, 3.0, 4.0])
    ap.add_argument("--n-agents", type=int, default=3000)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--out", default="outputs/calibration")
    ap.add_argument("--analyse-only", action="store_true", help="fit from the existing grid, run nothing")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("nairobi_heat_abm").setLevel(logging.ERROR)

    cfg_path = Path(args.config).resolve()
    root = cfg_path.parent
    cfg = yaml.safe_load(cfg_path.read_text())
    out = root / args.out
    out.mkdir(parents=True, exist_ok=True)
    survey = survey_counts(root / args.survey)
    log.info("Survey: %d bus/matatu riders who walked to the stage (Q8); %d answered Q11",
             survey["access"].sum(), survey["trip"].sum())
    pd.DataFrame([{"question": q, "bin": k, "survey_n": n, "survey_share": n / survey[key].sum()}
                  for key, q in (("access", "Q8 access"), ("trip", "Q11")) for k, n in survey[key].items()]
                 ).to_csv(out / "survey_bins.csv", index=False)

    grid_path = out / "calibration_grid.csv"
    bins_path = out / "calibration_bins.csv"
    done_keys = set()
    if grid_path.exists():  # resume: skip cells already run with these settings
        prev = pd.read_csv(grid_path)
        done_keys = {(round(r.beta, 6), round(r.walk_time_weight, 6), int(r.n_agents), int(r.seeds))
                     for r in prev.itertuples()}
    todo = [(ww, beta) for ww in args.walk_weights for beta in args.betas
            if (round(beta, 6), round(ww, 6), args.n_agents, args.seeds) not in done_keys]
    if args.analyse_only:
        todo = []

    if todo:
        b = cfg["bbox"]
        surface = load_heat_surface(root / cfg["paths"]["heat_dir"], bbox=(b["south"], b["west"], b["north"], b["east"]))
        base = _base_params(cfg, root, args.n_agents, surface)
        ctx = load_context(base)
    for ww, beta in todo:
        t = time.perf_counter()
        access, ride, door, outdoor, n_trav = [], [], [], [], 0
        for s in range(args.seeds):
            behavior = dataclasses.replace(base.behavior, destination_distance_decay=beta, walk_time_weight=ww)
            r = run(dataclasses.replace(base, seed=base.seed + s, behavior=behavior), context=ctx)
            transit = r.agent_modes == MODE_TRANSIT
            access.append(r.agent_access_walk_min[transit])
            ride.append(r.agent_ride_min[transit])
            door.append(r.agent_trip_min[transit])
            trav = r.agent_outdoor_min > 0
            outdoor.append(r.agent_outdoor_min[trav])
            n_trav += int(trav.sum())
        access, ride, door, outdoor = map(np.concatenate, (access, ride, door, outdoor))
        shares = {"Q8 access": bin_shares(access, ACCESS_BINS), "Q11 ride": bin_shares(ride, TRIP_BINS),
                  "Q11 door-to-door": bin_shares(door, TRIP_BINS)}
        row = {
            "beta": beta, "walk_time_weight": ww, "n_agents": args.n_agents, "seeds": args.seeds,
            "n_transit_trips": len(access), "transit_share": len(access) / max(n_trav, 1),
            "access_median_min": float(np.nanmedian(access)) if len(access) else np.nan,
            "ride_median_min": float(np.nanmedian(ride)) if len(ride) else np.nan,
            "loglik_q8": multinomial_loglik(survey["access"], shares["Q8 access"]),
            "loglik_q11_ride": multinomial_loglik(survey["trip"], shares["Q11 ride"]),
            "loglik_q11_door": multinomial_loglik(survey["trip"], shares["Q11 door-to-door"]),
            "mean_outdoor_min": float(outdoor.mean()), "seconds": round(time.perf_counter() - t, 1),
        }
        pd.DataFrame([row]).to_csv(grid_path, mode="a", header=not grid_path.exists(), index=False)
        pd.DataFrame([{"beta": beta, "walk_time_weight": ww, "question": q, "bin": k, "model_share": v}
                      for q, sh in shares.items() for k, v in sh.items()]).to_csv(
            bins_path, mode="a", header=not bins_path.exists(), index=False)
        log.info("beta %.2f, walk weight %.2f: %d transit trips (%.0f%%), access median %.1f, ride median %.1f, "
                 "loglik Q8 %.0f Q11 %.0f, outdoor %.0f min (%.0f s)", beta, ww, row["n_transit_trips"],
                 100 * row["transit_share"], row["access_median_min"], row["ride_median_min"],
                 row["loglik_q8"], row["loglik_q11_ride"], row["mean_outdoor_min"], row["seconds"])

    grid = pd.read_csv(grid_path)
    grid = grid[(grid["n_agents"] == args.n_agents) & (grid["seeds"] == args.seeds)].copy()
    grid["loglik_joint"] = grid["loglik_q8"] + grid["loglik_q11_ride"]
    likelihood = fit_peak_2d(grid, "beta", "walk_time_weight", "loglik_joint")
    likelihood["objective"] = "loglik Q8 access + Q11 (as boarding-to-alighting)"
    adopted = median_match(grid, binned_median(survey["access"], ACCESS_BINS), binned_median(survey["trip"], TRIP_BINS))
    fit = {"adopted": adopted, "max_likelihood": likelihood, "n_agents": args.n_agents, "seeds": args.seeds,
           "survey_n_q8": int(survey["access"].sum()), "survey_n_q11": int(survey["trip"].sum())}
    (out / "calibration_fit.json").write_text(json.dumps(fit, indent=2))
    log.info("Adopted (median match): %s", adopted)
    log.info("Max likelihood (reference): %s", likelihood)
    return 0


if __name__ == "__main__":
    sys.exit(main())
