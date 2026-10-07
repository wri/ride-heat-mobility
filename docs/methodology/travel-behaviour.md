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

### Departure time by trip purpose

The profile above sets the overall shape of departures across the day. Each trip's purpose then shifts its own timing. Every agent draws its purpose first, then its departure tick from

P(tick | purpose) ∝ P_profile(tick) × tilt[purpose][band of tick]

where `departure_purpose_tilt` holds one multiplier per purpose per time band, and `departure_tilt_band_edges_h` gives the band edges in local clock hours. A multiplier of 1.0 means the purpose departs in that band as often as the profile alone would predict. Outside every band, or for a purpose missing from the dict, the multiplier is 1.0, so setting `departure_purpose_tilt = {}` gives departure times that don't depend on purpose, as in earlier versions of the model. Purpose shares themselves are still set by `purpose_weights`; the tilt only moves each purpose's trips around the day. As a side effect, the overall departure profile is no longer exactly the bimodal shape: with the default weights, about 28% of all trips leave between 07:00 and 08:00, down from 32%.

| Band (local) | 06–09 | 09–11 | 11–13 | 13–15 | 15–17 | 17–20 |
|---|---|---|---|---|---|---|
| work | 1.49 | 1.22 | 0.96 | 0.83 | 0.88 | 0.83 |
| school | 0.85 | 1.00 | 1.10 | 1.07 | 0.97 | 0.75 |
| market | 0.40 | 0.69 | 0.94 | 1.22 | 1.19 | 1.50 |
| other | 0.23 | 0.62 | 1.09 | 1.26 | 1.22 | 1.27 |

Resulting share of each purpose's trips by departure time, with the default profile:

| Departure | No tilt | work | school | market | other |
|---|---|---|---|---|---|
| 06–09 | 49% | 62% | 48% | 23% | 16% |
| 09–15 | 9% | 7% | 11% | 10% | 12% |
| 15–20 | 42% | 31% | 41% | 67% | 73% |

**Calibration.** The defaults come from the WRI Nairobi rider survey (see [Transit wait time](#calibration-from-the-wri-rider-survey) and [References](references.md)), Q9 *"What is the Purpose of this Journey?"*. The number of interviews per hour reflects when interviewers were working, not when people travel, so the survey cannot give P(hour). The purpose mix within an hour does not depend on interviewer schedules, so it does give P(purpose | hour). By Bayes' rule, P(hour | purpose) ∝ P(hour) × P(purpose | hour). The model's own profile supplies P(hour), and the survey supplies the second factor, expressed relative to the overall purpose share: tilt = P(purpose | band) / P(purpose).

Processing:
- Timestamps are taken as UTC and shifted +3 h to Nairobi time (inferred; see the wait-time limitations above).
- Each respondent's departure from origin is estimated as interview time minus the midpoint of their reported access time (Q8: <5 → 2.5, 6–10 → 8, 11–20 → 15.5, 21–30 → 25.5, >30 → 35 min; 0 if missing).
- Purposes map to model purposes as Work → work, School → school, Shop or Market → market, Other and healthcare → other.
- 104 home-bound trips ("Other" with *home* in the free text) are excluded: the model simulates only the outbound trip from home.
- Departures before 06:00 fall into the first band and after 20:00 into the last. Bands hold 180–490 respondents each.

**Limitations.**
- **Adults only.** The survey only interviewed people aged 18 and over. "School" trips here are adult students (and perhaps escorts), which is why the school tilt is nearly flat. Children's trips of any purpose are not represented, yet the model applies these tilts to child agents too.
- **Transit riders only**, as for the wait-time calibration. Walk-only trips may be timed differently.
- **Weekdays only.** The fieldwork ran Monday–Friday.
- **Survey purpose is "this journey".** Respondents heading home from work may have answered "Work" instead of "Other: home", so some evening work responses may be return trips.
- The tilt has no demographic breakdown, so there are no `ParamModifier` multipliers for it.

<!-- TODO: find a source for children's trip timing by purpose (e.g. JICA 2013) -->

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

## Transit wait time and wait tolerance

| Parameter | Default | Source |
|---|---|---|
| `transit_mean_wait_min` | 5.65 min | WRI Nairobi rider survey (2026), Q15 — fit described below |
| `transit_wait_tolerance_min` | 15 min | <!-- TODO --> |
| `transit_wait_tolerance_std` | 5 min | <!-- TODO --> |

An agent who boards transit waits at the first stop for a time drawn from `Exponential(mean = transit_mean_wait_min)`. The same mean is used as the expected wait when the agent plans its route, so it shapes both whether the agent rides at all and how long it actually stands at the stop (see [ABM core](../dev/abm-core.md#transit-routing--route_transit)). If the drawn wait exceeds `transit_wait_tolerance_min`, the agent walks instead.

The GTFS feed's headways are **not** used for the wait. The 2019 DigitalMatatus feed gives every one of its trips the same headways (5 min 06–09 and 15–21, 15 min 09–15), which looks like a placeholder schedule rather than measured service. The feed's frequency bands still decide whether a route is running at all at the agent's departure time (see [Transport network](transport-network.md)).

### Calibration from the WRI rider survey

`WRI_Survey_DATA_23_09_2023.xlsx` (sheet `WRI_Survey_Cleaned_DATA`, 2,122 respondents interviewed at Nairobi stages, almost all on weekdays 14–18 and 21 September 2026; the date in the file name does not match the survey dates) asks *"15. How long do you have to wait for the mode to set off?"*, answered in bins: Immediate, 1–5, 6–10, 10–15, 16–20, and over 20 minutes. The model only represents bus and matatu service, so the fit uses those respondents (diesel + electric bus and matatu, N = 1,484) and leaves out boda and tuk-tuk riders.

Because the answers are binned, the exponential mean was fit by maximum likelihood on interval-censored data: each respondent contributes the probability that an exponential wait falls inside their bin. Bin edges were taken as [0, 1), [1, 5.5), [5.5, 10.5), [10.5, 15.5), [15.5, 20.5) and [20.5, ∞) minutes, so "Immediate" counts as under one minute.

| Respondents | N | Fitted mean wait |
|---|---|---|
| Bus (diesel + electric) | 996 | 5.1 min |
| Matatu (diesel + electric) | 488 | 6.7 min |
| **Bus + matatu (model default)** | **1,484** | **5.65 min** |
| Boda (not modeled; for comparison) | 599 | 1.3 min |

Transit edges in the graph are not tagged as bus or matatu, so the model uses the pooled bus + matatu value for every boarding.

**Limitations.**

- **The exponential shape fits only roughly.** Reported waits cluster at 6–10 minutes and almost never exceed 15. The fitted exponential puts fewer riders in 6–10 minutes than were observed (329 vs. 565) and more in the long tail (16–20 min: 56 vs. 12; over 20 min: 39 vs. 2). With a 5.65-minute mean, about 7% of draws exceed 15 minutes, while about 1% of respondents reported that. The model therefore sends somewhat more agents back to walking under the default 15-minute tolerance than the survey would suggest.
- **One mean all day.** Each interview has a timestamp (`Date of Survey`). The timestamps appear to be in UTC, so Nairobi local time is the recorded time plus 3 hours. This is inferred from the data, not confirmed by the survey team: as recorded, about a quarter of interviewer shifts would start before 05:00, and trips home would peak around 13:00–14:00; shifted by +3 h, shifts run roughly 07:00–17:00 and trips home peak in the late afternoon. Fitting each GTFS time band separately (local time) gives bus + matatu means of 4.8 min for 06–09 (N = 114), 5.4 min for 09–15 (N = 952) and 6.4 min for 15–21 (N = 416). That is a modest rise through the day, nothing like the feed's 5/15/5-minute headways, so the model uses the single pooled mean. Morning-peak interviews are few, because most interviews took place between 09:00 and 15:00 local time.
- **Riders only.** Everyone surveyed was already waiting for or riding a vehicle, so the survey describes waits experienced by transit users and says nothing about people who decided to walk instead. It cannot inform `walk_only_share`.
- **Self-reported.** Wait times are respondents' recollections and are likely rounded toward bin boundaries.

<!-- TODO: informal transit in Nairobi has highly variable headways; discuss what evidence exists for acceptable wait times (transit_wait_tolerance_min/std) -->

## Travel probability by destination type

Each agent draws exactly one destination for one purpose (work/school/market/other) — `trip_rate_mean` above is a reported statistic (`ScenarioResult.agent_n_trips`), not a literal count of simulated trips. `travel_probability` (a `dict[str, float]` on `TravelBehaviorParams`, one entry per purpose, default `1.0` everywhere) is the probability that an agent's single drawn trip actually happens, conditioned on which purpose it's for.

An agent that fails this draw stays inactive for the whole run: zero trips, zero heat exposure — the same outcome as a routing failure (no path found), but a different mechanism. See the notebook's §3.2 non-travel breakdown for how to tell the two apart in results.

| Parameter | Default | Source |
|---|---|---|
| `travel_probability` | `1.0` for every purpose (no gating) | <!-- TODO --> |

<!-- TODO: cite empirical evidence for heat- or demographic-driven trip suppression by destination type in Nairobi (e.g. discretionary market trips skipped more than work trips during extreme heat) to justify non-default values -->

## Demographic modifiers

Age group, gender, and socioeconomic/informality status (see [Population model](population-model.md#demographic-composition) for how agents get these attributes) can each carry a `ParamModifier` (`model/agent.py`) that multiplicatively adjusts a base `TravelBehaviorParams` for agents with that attribute value. Every scalar field on `TravelBehaviorParams` except `transit_mean_wait_min` has a corresponding `_mult` (default `1.0`, no-op) — trip generation, departure timing, mode split, walk speed, and transit wait tolerance are all covered, plus two dict-keyed-by-purpose modifiers:

- `purpose_weight_mult` — adjusts trip purpose weights (**Trip purpose**, above) for specific purposes; unspecified purposes are left at their base weight. Weights are renormalized after all three attributes' modifiers are applied, so only the *relative* shift matters, not the absolute multiplier.
- `travel_probability_mult` — adjusts `travel_probability` (**Travel probability by destination type**, above) per purpose; the combined value is clipped to `[0, 1]` rather than renormalized, since it's a set of independent probabilities, not a simplex.

`trip_rate_distribution` and `departure_profile` (string enums, not magnitudes) have no modifier — multiplying a category label isn't meaningful. `transit_mean_wait_min` has none because it describes the transit service rather than the traveller, and because route assignment (`assign_routes()`) reads only the base `TravelBehaviorParams`, so a per-segment value would never take effect.

The three attributes combine **independently and multiplicatively** — e.g. a youth x female x informal-settlement agent's effective `trip_rate_mean` is `base x age_mult x gender_mult x ses_mult` — rather than each (age, gender, SES) combination having its own independently-calibrated profile. This was a deliberate simplification to keep the parameter count tractable for calibration and RDM sweeps, at the cost of not capturing genuine three-way interaction effects (e.g. if young informal-settlement women behave differently from what their individual age/gender/SES effects alone would predict).

<!-- TODO: cite empirical differentials in trip rate, purpose mix, and travel probability by age/gender/SES for Nairobi (or comparable East African cities) to justify default modifier values; currently all modifier dicts default empty/no-op until populated per scenario -->

## Uncertainty ranges for RDM

All parameters above are varied in RDM sweeps. See [RDM approach](rdm-approach.md) for how ranges are chosen and how sensitivity is assessed.

Demographic modifiers, `travel_probability`, and the newly-modifiable fields (departure timing, mode split, walk speed, transit wait tolerance) are not currently swept by the RDM pipeline (`rdm/sampling.py` only varies the subset of base `TravelBehaviorParams` fields in `STANDARD_RANGES`) — this is a known gap, not a design decision, and would be natural follow-up work once modifier values are empirically grounded.

See [References](references.md) for full citations.
