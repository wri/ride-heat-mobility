"""
Tables of agent behaviour as modelled in notebook 01 (10,000 agents, seed 42, default
TravelBehaviorParams and DemographicParams with the WorldPop age/sex rasters):

  table_behaviour   every behavioural rule and parameter, which agent attributes it depends
                    on (age, sex, purpose, distance, ...) and its source
  table_population  age/sex composition of the simulated agents and their trip-purpose mix

Values are read from the model's own dataclasses (model/agent.py), not retyped, so the table
follows the code. The population table reads the run's GeoPackage; purposes are replayed from
the seed (purposes.py).

Writes behaviour_tables.json (read by build_doc.py) and two CSVs next to this script.
Run from the repo root:  .venv/Scripts/python.exe artifacts/paper_nb01/behaviour_tables.py
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

from nairobi_heat_abm.model.agent import (
    AGE_CHILD, SCHOOL_END_HOUR, SCHOOL_START_HOUR, DemographicParams, TravelBehaviorParams,
)
from purposes import reconstruct_purposes  # same folder

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GPKG = ROOT / "outputs" / "heat_exposure_heat_10000agents_seed42.gpkg"

b = TravelBehaviorParams()
d = DemographicParams()


def hm(h: float) -> str:
    return f"{int(h):02d}:{round((h % 1) * 60):02d}"


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


# Guard the one demographic rule the text describes, so a code change can't silently
# make the table wrong.
assert set(d.age_modifiers) == {AGE_CHILD}, d.age_modifiers
assert d.age_modifiers[AGE_CHILD].departure_window_h == {"school": [0.0, SCHOOL_START_HOUR]}
assert d.age_modifiers[AGE_CHILD].purpose_weight_mult == {"work": 0.0, "market": 0.0, "other": 0.0}
assert not d.gender_modifiers and not d.ses_modifiers
assert all(p == 1.0 for p in b.travel_probability.values())

pw = b.purpose_weights
curve, intra = b.walk_share_curve, b.walk_share_intrazonal
tilt = b.departure_purpose_tilt
edges = b.departure_tilt_band_edges_h
peak_off = 1 - b.peak1_weight - b.peak2_weight

NONE = "—"
rows = [
    # (section, parameter, value, differs by, source)
    ("Who travels", "Home location",
     "Drawn in proportion to population (100 m grid), snapped to the nearest street node",
     NONE, "WorldPop 100 m population, Kenya"),
    ("Who travels", "Age group",
     "Child 0–14, youth 15–19, adult 20–59, elderly 60+; drawn from the age mix of the agent's home grid cell",
     "Home location", "WorldPop age-group rasters (youth = total − children − adults 20+)"),
    ("Who travels", "Sex",
     "Drawn from the female share of the home grid cell, independently of age",
     "Home location", "WorldPop female-population raster"),
    ("Who travels", "Trips per agent",
     "One round trip: home → destination → home. Every agent travels (travel probability 1)",
     NONE, "Model design"),
    ("Who travels", "Trip purpose",
     f"Children 0–14: school only. Everyone else: work {pct(pw['work'])}, school {pct(pw['school'])}, "
     f"market {pct(pw['market'])}, other {pct(pw['other'])}",
     "Age: children vs. others (same for both sexes)", "Children: school attendance; others: assumption"),
    ("Who travels", "Destination",
     f"OpenStreetMap amenity of the trip's purpose, chosen with weight distance^−{b.destination_distance_decay:g}^",
     "Purpose, distance", "Calibrated: WRI rider survey Q11 (median time on board 22.7 min)"),

    ("When", "Outbound departure time",
     f"Two normal peaks (SD 30 min) at {hm(b.peak1_hour)} ({pct(b.peak1_weight)}) and "
     f"{hm(b.peak2_hour)} ({pct(b.peak2_weight)}), {pct(peak_off)} spread evenly over "
     "06:00–20:00",
     NONE, "Assumption, refit so outbound + return departures match an assumed all-journey profile"),
    ("When", "Departure timing by purpose",
     f"Profile × purpose multiplier per time band, e.g. work ×{tilt['work'][0]:.2f} at "
     f"{hm(edges[0])}–{hm(edges[1])}, market ×{tilt['market'][-1]:.2f} at {hm(edges[-2])}–{hm(edges[-1])}",
     "Purpose", "WRI rider survey Q9 (adults ≥ 18, bus/matatu riders, weekdays)"),
    ("When", "Children's school departures",
     f"Leave before {hm(SCHOOL_START_HOUR)} (school starts {hm(SCHOOL_START_HOUR)})",
     "Age: children 0–14 only", f"Nairobi school day {hm(SCHOOL_START_HOUR)}–{hm(SCHOOL_END_HOUR)}"),
    ("When", "Trip home: work",
     f"Leave at {hm(b.work_end_hour_mean)} ± {b.work_end_hour_std:g} h (normal), at least "
     f"{b.min_stay_min:.0f} min after arriving",
     "Purpose", "Assumption; Kenya public-service hours 08:00–17:00"),
    ("When", "Trip home: school",
     f"Leave at {hm(b.school_end_hour_mean)} ± {b.school_end_hour_std * 60:.0f} min (normal), at least "
     f"{b.min_stay_min:.0f} min after arriving",
     "Purpose (all ages alike)", f"Nairobi school day {hm(SCHOOL_START_HOUR)}–{hm(SCHOOL_END_HOUR)}"),
    ("When", "Trip home: market, other",
     f"Stay a log-normal time, median {b.market_dwell_median_min:.0f} min (market), "
     f"{b.other_dwell_median_min:.0f} min (other); log-SD {b.dwell_sigma_log:g}",
     "Purpose", "Assumption"),

    ("How", "Walk the whole way",
     f"Probability by trip length d (km): under {b.walk_intrazonal_max_km:g} km, work {intra['work']:.0f}%, "
     f"school {intra['school']:.0f}%, market/other {intra['other']:.0f}%; longer trips, "
     f"work {curve['work'][0]:.1f} − {curve['work'][1]:.1f} ln d %, "
     f"school {curve['school'][0]:.1f} − {curve['school'][1]:.1f} ln d %, "
     f"market/other {curve['other'][0]:.1f} − {curve['other'][1]:.1f} ln d %",
     "Purpose, distance", "JICA (2014) Nairobi walk-split curves, 2013 household survey"),
    ("How", "Route for everyone else",
     f"Least cost: time riding + {b.walk_time_weight:g} × time walking + expected wait; may still be "
     "all walking",
     NONE, "Calibrated: WRI rider survey Q8 (access walk time)"),
    ("How", "Walking speed",
     f"{b.walk_speed_mean_mps:g} ± {b.walk_speed_std_mps:g} m/s (normal, one draw per person)",
     "None (same for all ages)", "Common pedestrian default"),
    ("How", "Wait to board",
     f"Exponential, mean {b.transit_mean_wait_min:g} min",
     NONE, "WRI rider survey Q15 (bus and matatu riders, n = 1,484)"),
    ("How", "Wait tolerance",
     f"Walk instead if the drawn wait exceeds {b.transit_wait_tolerance_min:g} min",
     NONE, "Assumption"),
]
sections = {}
out_rows = []
for i, (sec, *rest) in enumerate(rows):
    if sec not in sections.values():
        sections[i] = sec
    out_rows.append(rest)
pd.DataFrame(rows, columns=["section", "parameter", "value", "differs_by", "source"]).to_csv(
    HERE / "table_behaviour_parameters.csv", index=False)

# ---- Population composition and purpose mix of the run ----------------------------------------
agents = gpd.read_file(GPKG, layer="agent_homes", ignore_geometry=True)
agents["purpose"] = reconstruct_purposes(agents)
n = len(agents)
P = ["work", "school", "market", "other"]
groups = [("All agents", slice(None))]
groups += [(lab, agents["age_group"] == g) for g, lab in
           (("child", "Child (0–14)"), ("youth", "Youth (15–19)"), ("adult", "Adult (20–59)"),
            ("elderly", "Elderly (60+)"))]
groups += [(lab, agents["gender"] == g) for g, lab in (("female", "Female"), ("male", "Male"))]
prow, pdata = [], []
for lab, m in groups:
    a = agents.loc[m]
    shares = a["purpose"].value_counts(normalize=True).reindex(P, fill_value=0)
    prow.append([lab, f"{len(a):,}", f"{len(a) / n * 100:.1f}"] + [f"{s * 100:.0f}" for s in shares])
    pdata.append({"group": lab, "n": len(a), "share_pct": len(a) / n * 100,
                  **{f"{p}_pct": s * 100 for p, s in shares.items()}})
pd.DataFrame(pdata).to_csv(HERE / "table_population_composition.csv", index=False)
female_by_age = agents.groupby("age_group")["gender"].apply(lambda s: (s == "female").mean() * 100).round(1)

out = {
    "table_behaviour": {"header": ["Rule or parameter", "Value in the main run", "Differs by", "Source"],
                        "rows": out_rows, "section_rows": {str(k): v for k, v in sections.items()}},
    "table_population": {"header": ["Group", "n", "% of agents", "Work (%)", "School (%)", "Market (%)",
                                    "Other (%)"],
                         "rows": prow, "section_rows": {"1": "Age group", "5": "Sex"}},
    "numbers": {"female_pct_by_age": female_by_age.to_dict(),
                "child_school_pct": float(pdata[1]["school_pct"]),
                "all_school_pct": float(pdata[0]["school_pct"])},
}
(HERE / "behaviour_tables.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
for r in out_rows:
    print(" | ".join(r))
print(pd.DataFrame(pdata).round(1).to_string(index=False))
print(out["numbers"])
