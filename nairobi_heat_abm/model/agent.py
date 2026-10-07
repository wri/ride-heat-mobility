from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Mode codes stored in AgentPool.mode (uint8)
MODE_WALK = 0
MODE_WAIT = 1
MODE_TRANSIT = 2

# Trip purpose codes stored in AgentPool.trip_purpose (uint8)
PURPOSE_WORK = 0
PURPOSE_SCHOOL = 1
PURPOSE_MARKET = 2
PURPOSE_OTHER = 3

# Age group codes stored in AgentPool.age_group (uint8)
AGE_CHILD = 0
AGE_YOUTH = 1
AGE_ADULT = 2
AGE_ELDERLY = 3

# Gender codes stored in AgentPool.gender (uint8)
GENDER_MALE = 0
GENDER_FEMALE = 1

# Socioeconomic/informality status codes stored in AgentPool.ses (uint8)
SES_FORMAL = 0
SES_INFORMAL = 1


@dataclass
class TravelBehaviorParams:
    # Trip generation
    trip_rate_mean: float = 3.2
    trip_rate_std: float = 1.1
    trip_rate_distribution: str = "normal"  # "normal" | "poisson"

    # Departure time profile
    departure_profile: str = "bimodal"  # "bimodal" | "uniform" | "custom"
    peak1_hour: float = 7.5
    peak1_weight: float = 0.45
    peak2_hour: float = 17.0
    peak2_weight: float = 0.35

    # Purpose-dependent departure timing. The profile above sets the overall shape of
    # departures across the day; each purpose's departure probability in a time band is
    # then multiplied by departure_purpose_tilt[purpose][band] and renormalized, so
    # P(tick | purpose) ∝ P_profile(tick) × tilt. Bands are local clock hours
    # [edges[i], edges[i+1]); outside every band, and for any purpose missing from the
    # dict, the multiplier is 1.0. All-1.0 (or an empty dict) = departure time
    # independent of purpose. Defaults: P(purpose | hour) / P(purpose) from the WRI
    # Nairobi rider survey (Sep 2026, UTC timestamps + 3 h, minus reported access time,
    # home-bound trips excluded) — see docs/methodology/travel-behaviour.md.
    departure_tilt_band_edges_h: list[float] = field(default_factory=lambda: [6.0, 9.0, 11.0, 13.0, 15.0, 17.0, 20.0])
    departure_purpose_tilt: dict[str, list[float]] = field(default_factory=lambda: {
        "work":   [1.49, 1.22, 0.96, 0.83, 0.88, 0.83],
        "school": [0.85, 1.00, 1.10, 1.07, 0.97, 0.75],
        "market": [0.40, 0.69, 0.94, 1.22, 1.19, 1.50],
        "other":  [0.23, 0.62, 1.09, 1.26, 1.22, 1.27],
    })

    # Mode split (walk_transit_share = 1.0 - walk_only_share)
    walk_only_share: float = 0.55

    # Trip purpose weights (normalised in __post_init__)
    purpose_weights: dict[str, float] = field(default_factory=lambda: {
        "work": 0.40, "school": 0.20, "market": 0.25, "other": 0.15
    })

    # Movement
    walk_speed_mean_mps: float = 1.2
    walk_speed_std_mps: float = 0.15
    transit_wait_tolerance_min: float = 15.0
    transit_wait_tolerance_std: float = 5.0
    # Mean of the Exponential boarding-wait draw (and the expected wait used when
    # planning routes). 5.65 min is the maximum-likelihood fit of an exponential to
    # Q15 ("How long do you have to wait for the mode to set off?") of the WRI Nairobi
    # rider survey (WRI_Survey_DATA_23_09_2023.xlsx), bus + matatu respondents only,
    # N=1484 — see docs/methodology/travel-behaviour.md.
    transit_mean_wait_min: float = 5.65

    # Probability an agent's single simulated trip actually happens, keyed by the
    # purpose/amenity type it would be headed to. 1.0 (default) = always travels;
    # an agent that fails this draw stays inactive for the whole run (zero trips,
    # zero heat exposure) — see model/simulation.py::_draw_travel_gate.
    travel_probability: dict[str, float] = field(default_factory=lambda: {
        "work": 1.0, "school": 1.0, "market": 1.0, "other": 1.0
    })

    def __post_init__(self) -> None:
        total = sum(self.purpose_weights.values())
        self.purpose_weights = {k: v / total for k, v in self.purpose_weights.items()}
        if not 0.0 <= self.walk_only_share <= 1.0:
            raise ValueError("walk_only_share must be in [0, 1]")
        if self.transit_mean_wait_min <= 0.0:
            raise ValueError("transit_mean_wait_min must be > 0")
        edges = self.departure_tilt_band_edges_h
        if len(edges) < 2 or any(b <= a for a, b in zip(edges[:-1], edges[1:])):
            raise ValueError("departure_tilt_band_edges_h must be at least 2 strictly increasing hours")
        for purpose, tilt in self.departure_purpose_tilt.items():
            if len(tilt) != len(edges) - 1:
                raise ValueError(
                    f"departure_purpose_tilt[{purpose!r}] needs {len(edges) - 1} values (one per band), got {len(tilt)}"
                )
            if any(not np.isfinite(v) or v < 0.0 for v in tilt):
                raise ValueError(f"departure_purpose_tilt[{purpose!r}] values must be finite and >= 0")
        for purpose, p in self.travel_probability.items():
            if not 0.0 <= p <= 1.0:
                raise ValueError(f"travel_probability[{purpose!r}] must be in [0, 1]")


def params_to_json(p: TravelBehaviorParams) -> str:
    d = dataclasses.asdict(p)
    d["schema_version"] = "1.0"
    return json.dumps(d, indent=2)


def params_from_json(s: str) -> TravelBehaviorParams:
    d = json.loads(s)
    d.pop("schema_version", None)
    return TravelBehaviorParams(**d)


@dataclass
class ParamModifier:
    """A multiplicative adjustment to a subset of TravelBehaviorParams, applied for one
    value of one demographic attribute (an age group, a gender, or an SES level).

    trip_rate_distribution and departure_profile (string enums on TravelBehaviorParams)
    have no modifier here — multiplying a category label isn't meaningful. Neither do
    departure_tilt_band_edges_h/departure_purpose_tilt: they are already relative
    multipliers, and their survey calibration has no demographic breakdown."""
    trip_rate_mean_mult: float = 1.0
    trip_rate_std_mult: float = 1.0
    purpose_weight_mult: dict[str, float] = field(default_factory=dict)  # e.g. {"work": 1.3}

    peak1_hour_mult: float = 1.0
    peak1_weight_mult: float = 1.0
    peak2_hour_mult: float = 1.0
    peak2_weight_mult: float = 1.0
    walk_only_share_mult: float = 1.0
    walk_speed_mean_mps_mult: float = 1.0
    walk_speed_std_mps_mult: float = 1.0
    transit_wait_tolerance_min_mult: float = 1.0
    transit_wait_tolerance_std_mult: float = 1.0

    # Per-purpose multiplier on TravelBehaviorParams.travel_probability. Missing keys
    # mean "no adjustment", same convention as purpose_weight_mult.
    travel_probability_mult: dict[str, float] = field(default_factory=dict)  # e.g. {"market": 0.5}


@dataclass
class DemographicParams:
    # Age/gender composition — independent weighted draws, not spatial. Used unless
    # population_raster_paths is set (see below), in which case age/gender are instead
    # drawn per agent from the local demographic-group population rasters and these two
    # shares are ignored.
    age_group_shares: dict[int, float] = field(default_factory=lambda: {
        AGE_CHILD: 0.35, AGE_YOUTH: 0.20, AGE_ADULT: 0.35, AGE_ELDERLY: 0.10,
    })
    gender_shares: dict[int, float] = field(default_factory=lambda: {
        GENDER_MALE: 0.49, GENDER_FEMALE: 0.51,
    })

    # Optional per-demographic-group WorldPop rasters (e.g. nairobipop_{key}.tif), all
    # covering the same area as the "total" one. When set, age_group/gender are instead
    # drawn spatially — from each agent's local demographic composition at its spawn
    # pixel — via data/population.py::load_population_rasters and
    # data/demographics.py::draw_age_gender_spatial. Required keys: "total" (used as the
    # spawn-density surface, superseding SimulationParams.worldpop_tif_path), "children"
    # (age <=14), "adult" (age >=20, includes elderly), "elderly" (age >=60), "female"
    # (any age). None (default) = use the flat age_group_shares/gender_shares above.
    population_raster_paths: dict[str, Path] | None = None

    # SES/informality is spatially derived from this boundary file (see data/demographics.py
    # assign_ses()). None = no real boundary data available yet -> every agent is SES_FORMAL.
    informal_settlement_path: Path | None = None

    # Modifiers keyed by the code of the attribute value they apply to (AGE_*, GENDER_*, SES_*).
    # Missing keys mean "no adjustment" (ParamModifier() is a no-op).
    age_modifiers: dict[int, ParamModifier] = field(default_factory=dict)
    gender_modifiers: dict[int, ParamModifier] = field(default_factory=dict)
    ses_modifiers: dict[int, ParamModifier] = field(default_factory=dict)


@dataclass
class AgentPool:
    n: int

    # Position — current edge
    edge_u: np.ndarray       # int64,   shape (n,) — source node
    edge_v: np.ndarray       # int64,   shape (n,) — target node
    edge_key: np.ndarray     # int32,   shape (n,) — MultiDiGraph edge key
    progress: np.ndarray     # float32, shape (n,) — 0.0 (at u) → 1.0 (at v)
    edge_length: np.ndarray  # float32, shape (n,) — metres, cached on route assignment

    # Mode: 0=walk, 1=wait, 2=transit
    mode: np.ndarray         # uint8,   shape (n,)

    # Movement
    speed_mps: np.ndarray       # float32, shape (n,) — per-agent walk speed
    edge_speed_mps: np.ndarray  # float32, shape (n,) — effective speed on the CURRENT edge:
                                 #   speed_mps for walk/access-link edges, but the transit
                                 #   edge's own (length / travel_time) while riding — a matatu
                                 #   segment isn't traversed at the agent's personal walk pace
    wait_ticks_remaining: np.ndarray  # int32, shape (n,) — ticks left waiting to board transit
                                       #   (mode==MODE_WAIT); decremented in scheduler.py::tick()

    # Trip state
    active: np.ndarray       # bool,    shape (n,) — False when trip complete
    trip_purpose: np.ndarray # uint8,   shape (n,) — 0=work,1=school,2=market,3=other

    # Demographics — zero-initialized (AGE_CHILD/GENDER_MALE/SES_FORMAL) when not modeled
    age_group: np.ndarray    # uint8,   shape (n,) — see AGE_* codes
    gender: np.ndarray       # uint8,   shape (n,) — see GENDER_* codes
    ses: np.ndarray          # uint8,   shape (n,) — see SES_* codes

    # Exposure accumulation (°C × minutes) — OUTDOOR only: scheduler.py::tick() excludes
    # MODE_TRANSIT (in-vehicle riding) ticks, since a matatu passenger isn't exposed to
    # ambient heat the way a walking/waiting pedestrian is.
    heat_exposure_degC_min: np.ndarray  # float32, shape (n,)

    # Routing
    route_edges: list[list[tuple]]  # per-agent list of (u, v, key, wait_ticks) tuples —
                                     # wait_ticks is 0 for every edge except a transit-
                                     # boarding edge, where it's the ticks to wait before riding
    route_index: np.ndarray         # int32, shape (n,) — current position in route

    @classmethod
    def create(cls, n: int) -> "AgentPool":
        return cls(
            n=n,
            edge_u=np.zeros(n, dtype=np.int64),
            edge_v=np.zeros(n, dtype=np.int64),
            edge_key=np.zeros(n, dtype=np.int32),
            progress=np.zeros(n, dtype=np.float32),
            edge_length=np.ones(n, dtype=np.float32),
            mode=np.zeros(n, dtype=np.uint8),
            speed_mps=np.full(n, 1.2, dtype=np.float32),
            edge_speed_mps=np.full(n, 1.2, dtype=np.float32),
            wait_ticks_remaining=np.zeros(n, dtype=np.int32),
            active=np.zeros(n, dtype=bool),
            trip_purpose=np.zeros(n, dtype=np.uint8),
            age_group=np.zeros(n, dtype=np.uint8),
            gender=np.zeros(n, dtype=np.uint8),
            ses=np.zeros(n, dtype=np.uint8),
            heat_exposure_degC_min=np.zeros(n, dtype=np.float32),
            route_edges=[[] for _ in range(n)],
            route_index=np.zeros(n, dtype=np.int32),
        )
