from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field

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

    def __post_init__(self) -> None:
        total = sum(self.purpose_weights.values())
        self.purpose_weights = {k: v / total for k, v in self.purpose_weights.items()}
        if not 0.0 <= self.walk_only_share <= 1.0:
            raise ValueError("walk_only_share must be in [0, 1]")


def params_to_json(p: TravelBehaviorParams) -> str:
    d = dataclasses.asdict(p)
    d["schema_version"] = "1.0"
    return json.dumps(d, indent=2)


def params_from_json(s: str) -> TravelBehaviorParams:
    d = json.loads(s)
    d.pop("schema_version", None)
    return TravelBehaviorParams(**d)


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
    speed_mps: np.ndarray    # float32, shape (n,) — per-agent walk speed

    # Trip state
    active: np.ndarray       # bool,    shape (n,) — False when trip complete
    trip_purpose: np.ndarray # uint8,   shape (n,) — 0=work,1=school,2=market,3=other

    # Exposure accumulation (°C × minutes)
    heat_exposure_degC_min: np.ndarray  # float32, shape (n,)

    # Routing
    route_edges: list[list[tuple]]  # per-agent list of (u, v, key) tuples
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
            active=np.zeros(n, dtype=bool),
            trip_purpose=np.zeros(n, dtype=np.uint8),
            heat_exposure_degC_min=np.zeros(n, dtype=np.float32),
            route_edges=[[] for _ in range(n)],
            route_index=np.zeros(n, dtype=np.int32),
        )
