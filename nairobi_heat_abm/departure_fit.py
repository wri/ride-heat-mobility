"""
Refit the OUTBOUND departure-time profile for round trips.

The bimodal departure profile (peak1_hour/weight, peak2_hour/weight) was set for a
model in which every agent made one trip, so it describes ALL journeys: outbound and
home-bound alike. The purpose tilt (departure_purpose_tilt) likewise comes from the WRI
rider survey's Q9, which has no "going home" answer, so respondents heading home gave
their activity's purpose. With round trips, the trips home add their own departures,
mostly in the afternoon and evening, and the profile applied to outbound trips alone
double-counts the evening.

This module chooses the outbound profile's four parameters so that outbound and return
departures TOGETHER reproduce the earlier all-journey departure distribution (the
one-way model's, with the default profile and tilt), in hourly bins over the simulated
day. The purpose tilt is kept unchanged.

Return departures depend on arrival times, so each candidate profile is scored with a
fast stand-in for the model: outbound departure ticks are drawn from the profile x tilt
by inverse CDF (as the model does), trip durations are resampled per purpose from one
full one-way model run, and return times follow model.agent.return_departure_hour.
Fixed random numbers make the score a smooth function of the parameters.

The target shape itself is an assumption (no Nairobi source in this project gives
person-trip departures by hour; the survey's interview times follow interviewer shifts),
so the fit carries that assumption over to round trips rather than adding information.

Run:  python -m nairobi_heat_abm.departure_fit [--n-agents 3000] [--out outputs/departure_fit]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from nairobi_heat_abm.model.agent import TravelBehaviorParams, return_departure_hour

log = logging.getLogger(__name__)

FIT_FIELDS = ("peak1_hour", "peak1_weight", "peak2_hour", "peak2_weight")


def purpose_pmfs(behavior: TravelBehaviorParams, start_hour: int, end_hour: int, timestep_s: float) -> np.ndarray:
    """P(departure tick | purpose), shape (n_purposes, n_ticks), as the model draws it
    (profile x purpose tilt; population-level, without demographic departure windows)."""
    from nairobi_heat_abm.model.simulation import PURPOSE_KEYS, _departure_profile_pmf, _purpose_tilt_by_tick

    n_ticks = int((end_hour - start_hour) * 3600 / timestep_s)
    base = _departure_profile_pmf(behavior, n_ticks, start_hour, timestep_s)
    out = np.empty((len(PURPOSE_KEYS), n_ticks))
    for code, purpose in enumerate(PURPOSE_KEYS):
        pmf = base * _purpose_tilt_by_tick(behavior, purpose, n_ticks, start_hour, timestep_s)
        out[code] = pmf / pmf.sum()
    return out


class RoundTripSampler:
    """Stand-in for the model's departure timing: outbound and return departure hours
    for a fixed synthetic population, as a function of the behaviour parameters."""

    def __init__(self, durations_min: dict[int, np.ndarray], purpose_weights: dict[str, float],
                 start_hour: int, end_hour: int, timestep_s: float, n: int = 200_000, seed: int = 0):
        from nairobi_heat_abm.model.simulation import PURPOSE_KEYS

        rng = np.random.default_rng(seed)
        w = np.array([purpose_weights.get(k, 0.0) for k in PURPOSE_KEYS])
        self.purposes = rng.choice(len(PURPOSE_KEYS), size=n, p=w / w.sum())
        self.u = rng.random(n)
        self.z = rng.standard_normal(n)
        self.duration_h = np.empty(n)
        for code in range(len(PURPOSE_KEYS)):
            idx = np.flatnonzero(self.purposes == code)
            d = durations_min[code]
            self.duration_h[idx] = d[rng.integers(0, len(d), len(idx))] / 60.0
        self.start_hour, self.end_hour, self.timestep_s = start_hour, end_hour, timestep_s
        self.keys = PURPOSE_KEYS

    def departures(self, behavior: TravelBehaviorParams, round_trips: bool = True) -> tuple[np.ndarray, np.ndarray]:
        """(departure hours of every simulated leg, purpose code of each leg)."""
        pmfs = purpose_pmfs(behavior, self.start_hour, self.end_hour, self.timestep_s)
        ticks = np.empty(len(self.u), dtype=np.int64)
        for code in range(len(self.keys)):
            idx = np.flatnonzero(self.purposes == code)
            cdf = np.cumsum(pmfs[code])
            ticks[idx] = np.minimum(np.searchsorted(cdf, self.u[idx] * cdf[-1], side="right"), len(cdf) - 1)
        dep_h = self.start_hour + ticks * self.timestep_s / 3600.0
        if not round_trips:
            return dep_h, self.purposes
        arrival_h = dep_h + self.timestep_s / 3600.0 + self.duration_h
        ret_h = return_hours(behavior, self.purposes, arrival_h, self.z)
        ok = (arrival_h < self.end_hour) & (ret_h < self.end_hour)
        return np.concatenate([dep_h, ret_h[ok]]), np.concatenate([self.purposes, self.purposes[ok]])


def return_hours(behavior: TravelBehaviorParams, purposes: np.ndarray, arrival_h: np.ndarray,
                 z: np.ndarray) -> np.ndarray:
    """Vectorised model.agent.return_departure_hour (purpose codes 0-3)."""
    min_stay_h = behavior.min_stay_min / 60.0
    work = np.maximum(behavior.work_end_hour_mean + behavior.work_end_hour_std * z, arrival_h + min_stay_h)
    school = np.maximum(behavior.school_end_hour_mean + behavior.school_end_hour_std * z, arrival_h + min_stay_h)
    dwell = np.exp(behavior.dwell_sigma_log * z) / 60.0
    market = arrival_h + behavior.market_dwell_median_min * dwell
    other = arrival_h + behavior.other_dwell_median_min * dwell
    return np.choose(purposes, [work, school, market, other])


def hourly_shares(hours: np.ndarray, start_hour: int, end_hour: int) -> np.ndarray:
    counts = np.histogram(hours, bins=np.arange(start_hour, end_hour + 1))[0].astype(float)
    return counts / counts.sum()


def fit_outbound_profile(sampler: RoundTripSampler, base: TravelBehaviorParams,
                         off_peak: float | None = None) -> dict:
    """Outbound peak hours/weights whose round-trip departures best match (least squares
    on hourly shares) the one-way model's departures under `base`.

    off_peak: if given, the off-peak (all-day uniform) share of outbound departures is
    held at this value and only the peak hours and the split of the remaining share
    between the two peaks are fitted. Left free, the fit removes nearly all midday
    departures, trading them against the evening surplus of trips home."""
    target = hourly_shares(sampler.departures(base, round_trips=False)[0], sampler.start_hour, sampler.end_hour)
    h_lo, h_hi = (float(sampler.start_hour), 11.0), (12.0, float(sampler.end_hour))

    if off_peak is None:
        lo = np.array([h_lo[0], 0.0, h_hi[0], 0.0])
        hi = np.array([h_lo[1], 1.0, h_hi[1], 1.0])
        x0 = np.array([getattr(base, f) for f in FIT_FIELDS])
        starts = (x0, x0 * [1, 1, 1, 0.3], x0 * [1, 1.2, 1, 0.1])

        def values(x):
            x = np.clip(x, lo, hi)
            total = x[1] + x[3]
            w1, w2 = (x[1] / total, x[3] / total) if total > 1.0 else (x[1], x[3])
            return dict(peak1_hour=x[0], peak1_weight=w1, peak2_hour=x[2], peak2_weight=w2)
    else:
        lo = np.array([h_lo[0], 0.0, h_hi[0]])
        hi = np.array([h_lo[1], 1.0, h_hi[1]])
        peaks = 1.0 - off_peak
        x0 = np.array([base.peak1_hour, base.peak1_weight / (base.peak1_weight + base.peak2_weight), base.peak2_hour])
        starts = (x0, x0 * [1, 1.2, 1], x0 * [1, 0.8, 1])

        def values(x):
            x = np.clip(x, lo, hi)
            return dict(peak1_hour=x[0], peak1_weight=peaks * x[1], peak2_hour=x[2], peak2_weight=peaks * (1 - x[1]))

    def behaviour(x) -> TravelBehaviorParams:
        return dataclasses.replace(base, **{k: float(v) for k, v in values(np.asarray(x)).items()})

    def score(x) -> float:
        x = np.asarray(x)
        penalty = 1e3 * (np.sum(np.clip(lo - x, 0, None) ** 2) + np.sum(np.clip(x - hi, 0, None) ** 2))
        model = hourly_shares(sampler.departures(behaviour(x))[0], sampler.start_hour, sampler.end_hour)
        return float(np.sum((model - target) ** 2)) + penalty

    best = None
    for start in starts:
        res = minimize(score, start, method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 1e-9, "maxiter": 800})
        if best is None or res.fun < best.fun:
            best = res
    fitted = behaviour(best.x)
    hours = np.arange(sampler.start_hour, sampler.end_hour)
    shares = pd.DataFrame({
        "hour": hours,
        "target_all_journeys": target,
        "round_trip_old_profile": hourly_shares(sampler.departures(base)[0], sampler.start_hour, sampler.end_hour),
        "round_trip_fitted": hourly_shares(sampler.departures(fitted)[0], sampler.start_hour, sampler.end_hour),
        "outbound_fitted": hourly_shares(sampler.departures(fitted, round_trips=False)[0],
                                         sampler.start_hour, sampler.end_hour),
    })
    return {
        "off_peak": off_peak,
        "fitted": {f: round(float(getattr(fitted, f)), 3) for f in FIT_FIELDS},
        "previous": {f: float(getattr(base, f)) for f in FIT_FIELDS},
        "sse_previous": float(np.sum((shares["round_trip_old_profile"] - target) ** 2)),
        "sse_fitted": float(best.fun),
        "shares": shares,
    }


def main(argv: list[str] | None = None) -> int:
    import yaml

    from nairobi_heat_abm.data.heat import load_heat_surface
    from nairobi_heat_abm.model.simulation import load_context, run
    from nairobi_heat_abm.rdm.run_sensitivity import _base_params

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--n-agents", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=11000)
    ap.add_argument("--out", default="outputs/departure_fit")
    ap.add_argument("--off-peak", type=float, default=None,
                    help="hold the outbound off-peak share at this value (default: fit it too)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    root = Path(args.config).resolve().parent
    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    b = cfg["bbox"]
    surface = load_heat_surface(root / cfg["paths"]["heat_dir"], bbox=(b["south"], b["west"], b["north"], b["east"]))
    params = dataclasses.replace(_base_params(cfg, root, args.n_agents, surface), seed=args.seed)
    one_way = dataclasses.replace(params, behavior=dataclasses.replace(params.behavior, return_trips=False))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = out / f"trip_durations_{args.n_agents}agents_seed{args.seed}.npz"
    if cache.exists():
        durations = {int(k): v for k, v in np.load(cache).items()}
    else:
        t0 = time.perf_counter()
        r = run(one_way, context=load_context(params))
        log.info("One-way run for trip durations: %.0f s", time.perf_counter() - t0)
        durations = {code: r.agent_trip_min[(r.agent_purposes == code) & np.isfinite(r.agent_trip_min)]
                     for code in range(4)}
        np.savez(cache, **{str(k): v for k, v in durations.items()})

    sampler = RoundTripSampler(durations, params.behavior.purpose_weights,
                               params.start_hour, params.end_hour, params.timestep_s)
    fit = fit_outbound_profile(sampler, params.behavior, off_peak=args.off_peak)
    fit["shares"].to_csv(out / "hourly_shares.csv", index=False)
    summary = {k: v for k, v in fit.items() if k != "shares"}
    summary["median_trip_min"] = {str(c): float(np.median(d)) for c, d in durations.items()}
    (out / "fit.json").write_text(json.dumps(summary, indent=2))
    log.info("Fitted outbound profile: %s (SSE %.2e; unchanged profile with round trips: %.2e)",
             summary["fitted"], summary["sse_fitted"], summary["sse_previous"])
    print(fit["shares"].round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
