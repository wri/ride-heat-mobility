# Travel behaviour

→ [Back to index](index.md)

## Overview

Travel behaviour in the model is governed by a `TravelBehaviorParams` dataclass. Every parameter has a default value and an uncertainty range used in RDM sweeps. This document explains the empirical basis for both.

## Trip generation

| Parameter | Default | Source |
|---|---|---|
| `trip_rate_mean` | 3.2 trips/day | <!-- TODO --> |
| `trip_rate_std` | 1.1 | <!-- TODO --> |
| `trip_rate_distribution` | normal | <!-- TODO --> |

<!-- TODO: cite survey evidence for Nairobi trip rates; compare with JICA 2013 household travel survey; note that Tatah et al. 2023 reports 2.4 trips/day IQR [2–2] for Nairobi — reconcile -->

## Departure time profile

The bimodal departure profile reflects morning and evening commute peaks observed in Nairobi household travel surveys.

| Parameter | Default | Source |
|---|---|---|
| `peak1_hour` | 7.5 (07:30) | <!-- TODO --> |
| `peak1_weight` | 0.45 | <!-- TODO --> |
| `peak2_hour` | 17.0 (17:00) | <!-- TODO --> |
| `peak2_weight` | 0.35 | <!-- TODO --> |

<!-- TODO: cite empirical departure time distributions from JICA 2013 or other Nairobi surveys -->

## Mode split

| Parameter | Default | Source |
|---|---|---|
| `walk_only_share` | 0.55 | <!-- TODO --> |

<!-- TODO: Tatah et al. 2023 reports 42% walk mode share in Nairobi; Tembe et al. 2019 and Tembe et al. data from JICA 2013 provide additional context; discuss why our default differs from reported shares and what sensitivity looks like -->

## Trip purpose

| Purpose | Default weight |
|---|---|
| Work | 0.40 |
| School | 0.20 |
| Market | 0.25 |
| Other | 0.15 |

<!-- TODO: cite purpose distribution from JICA 2013 or other Nairobi surveys -->

## Walk speed

| Parameter | Default | Source |
|---|---|---|
| `walk_speed_mean_mps` | 1.2 m/s | <!-- TODO --> |
| `walk_speed_std_mps` | 0.15 m/s | <!-- TODO --> |

<!-- TODO: 1.2 m/s is a widely-used pedestrian default; discuss whether it is appropriate in heat conditions; note that the model does not reduce walk speed with heat exposure (a known limitation) -->

## Transit wait tolerance

| Parameter | Default | Source |
|---|---|---|
| `transit_wait_tolerance_min` | 15 min | <!-- TODO --> |
| `transit_wait_tolerance_std` | 5 min | <!-- TODO --> |

<!-- TODO: informal transit in Nairobi has highly variable headways; discuss what evidence exists for acceptable wait times -->

## Travel probability by destination type

Each agent draws exactly one destination for one purpose (work/school/market/other) — `trip_rate_mean` above is a reported statistic (`ScenarioResult.agent_n_trips`), not a literal count of simulated trips. `travel_probability` (a `dict[str, float]` on `TravelBehaviorParams`, one entry per purpose, default `1.0` everywhere) is the probability that an agent's single drawn trip actually happens, conditioned on which purpose it's for.

An agent that fails this draw stays inactive for the whole run: zero trips, zero heat exposure — the same outcome as a routing failure (no path found), but a different mechanism. See the notebook's §3.2 non-travel breakdown for how to tell the two apart in results.

| Parameter | Default | Source |
|---|---|---|
| `travel_probability` | `1.0` for every purpose (no gating) | <!-- TODO --> |

<!-- TODO: cite empirical evidence for heat- or demographic-driven trip suppression by destination type in Nairobi (e.g. discretionary market trips skipped more than work trips during extreme heat) to justify non-default values -->

## Demographic modifiers

Age group, gender, and socioeconomic/informality status (see [Population model](population-model.md#demographic-composition) for how agents get these attributes) can each carry a `ParamModifier` (`model/agent.py`) that multiplicatively adjusts a base `TravelBehaviorParams` for agents with that attribute value. Every scalar field on `TravelBehaviorParams` has a corresponding `_mult` (default `1.0`, no-op) — trip generation, departure timing, mode split, walk speed, and transit wait tolerance are all covered, plus two dict-keyed-by-purpose modifiers:

- `purpose_weight_mult` — adjusts trip purpose weights (**Trip purpose**, above) for specific purposes; unspecified purposes are left at their base weight. Weights are renormalized after all three attributes' modifiers are applied, so only the *relative* shift matters, not the absolute multiplier.
- `travel_probability_mult` — adjusts `travel_probability` (**Travel probability by destination type**, above) per purpose; the combined value is clipped to `[0, 1]` rather than renormalized, since it's a set of independent probabilities, not a simplex.

`trip_rate_distribution` and `departure_profile` (string enums, not magnitudes) have no modifier — multiplying a category label isn't meaningful.

The three attributes combine **independently and multiplicatively** — e.g. a youth x female x informal-settlement agent's effective `trip_rate_mean` is `base x age_mult x gender_mult x ses_mult` — rather than each (age, gender, SES) combination having its own independently-calibrated profile. This was a deliberate simplification to keep the parameter count tractable for calibration and RDM sweeps, at the cost of not capturing genuine three-way interaction effects (e.g. if young informal-settlement women behave differently from what their individual age/gender/SES effects alone would predict).

<!-- TODO: cite empirical differentials in trip rate, purpose mix, and travel probability by age/gender/SES for Nairobi (or comparable East African cities) to justify default modifier values; currently all modifier dicts default empty/no-op until populated per scenario -->

## Uncertainty ranges for RDM

All parameters above are varied in RDM sweeps. See [RDM approach](rdm-approach.md) for how ranges are chosen and how sensitivity is assessed.

Demographic modifiers, `travel_probability`, and the newly-modifiable fields (departure timing, mode split, walk speed, transit wait tolerance) are not currently swept by the RDM pipeline (`rdm/sampling.py` only varies the subset of base `TravelBehaviorParams` fields in `STANDARD_RANGES`) — this is a known gap, not a design decision, and would be natural follow-up work once modifier values are empirically grounded.

See [References](references.md) for full citations.
