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

The bimodal profile sets when agents leave home on their **outbound** trip: two normal peaks (30-minute standard deviation) plus an off-peak share spread evenly over the day (1 − both peak weights). Trips home are timed separately, by the return-trip rules ([Return trips](#return-trips)).

| Parameter | Default | Before round trips |
|---|---|---|
| `peak1_hour` | 7.4 (07:24) | 7.5 |
| `peak1_weight` | 0.66 | 0.45 |
| `peak2_hour` | 16.75 (16:45) | 17.0 |
| `peak2_weight` | 0.14 | 0.35 |
| off-peak share | 0.20 | 0.20 |

**Refit for round trips.** The earlier values (07:30/0.45, 17:00/0.35) were set when each agent made a single trip, so they described *all* journeys, including the evening trips home. Applied to outbound trips alone, they double-counted the evening once trips home were added. `nairobi_heat_abm/departure_fit.py` refits the outbound profile so that outbound and return departures *together* reproduce the earlier all-journey distribution (the one-way model's, with the purpose tilt), in hourly bins over 06:00–20:00:

- Return departures depend on arrival times, so each candidate profile is scored with a fast stand-in for the model. Outbound departures are drawn from the profile × tilt as in the model, trip durations are resampled by purpose from a full 3,000-agent one-way run (median 35–39 minutes), and return times follow the return-trip rules.
- The off-peak share is held at 0.20. With it free, the fit removed nearly all midday departures, trading them against the evening surplus of trips home.
- The score is the sum of squared differences in hourly shares: 0.023 for the refit profile, against 0.038 for the old profile with round trips.
- Remaining misfit: the round trips leave too many departures at 15:00 (school ends at 15:30) and 18:00–19:00 (work ends at 17:00 ± 1 h), and too few at 07:00.

| Departures | 06–09 | 09–15 | 15–20 |
|---|---|---|---|
| Earlier all-journey profile (target) | 43% | 9% | 48% |
| Outbound, refit profile | 61% | 10% | 29% |
| Outbound + return, refit profile | 36% | 13% | 52% |

Run: `python -m nairobi_heat_abm.departure_fit --off-peak 0.2` (writes `outputs/departure_fit/`: `fit.json`, `hourly_shares.csv`).

**The target is itself an assumption.** No source in this project gives Nairobi person-trip departures by hour: the WRI survey's interview times follow interviewer shifts, and the JICA report's hourly chart counts vehicles crossing the city boundary. The refit carries the earlier assumed shape over to round trips; it adds no new data. The four peak parameters are factors in the sensitivity analysis.

### Departure time by trip purpose

The profile above sets the overall shape of departures across the day. Each trip's purpose then shifts its own timing. Every agent draws its purpose first, then its departure tick from

P(tick | purpose) ∝ P_profile(tick) × tilt[purpose][band of tick]

where `departure_purpose_tilt` holds one multiplier per purpose per time band, and `departure_tilt_band_edges_h` gives the band edges in local clock hours. A multiplier of 1.0 means the purpose departs in that band as often as the profile alone would predict. Outside every band, or for a purpose missing from the dict, the multiplier is 1.0, so setting `departure_purpose_tilt = {}` gives departure times that don't depend on purpose, as in earlier versions of the model. Purpose shares themselves are still set by `purpose_weights`; the tilt only moves each purpose's trips around the day. As a side effect, the overall outbound profile is no longer exactly the bimodal shape: with the default weights, about 40% of outbound trips leave between 07:00 and 08:00.

| Band (local) | 06–09 | 09–11 | 11–13 | 13–15 | 15–17 | 17–20 |
|---|---|---|---|---|---|---|
| work | 1.49 | 1.22 | 0.96 | 0.83 | 0.88 | 0.83 |
| school | 0.85 | 1.00 | 1.10 | 1.07 | 0.97 | 0.75 |
| market | 0.40 | 0.69 | 0.94 | 1.22 | 1.19 | 1.50 |
| other | 0.23 | 0.62 | 1.09 | 1.26 | 1.22 | 1.27 |

Resulting share of each purpose's outbound trips by departure time, with the default profile:

| Departure | No tilt | work | school | market | other |
|---|---|---|---|---|---|
| 06–09 | 70% | 80% | 68% | 44% | 32% |
| 09–15 | 9% | 7% | 10% | 13% | 17% |
| 15–20 | 21% | 14% | 21% | 43% | 52% |

Counting trips home as well, departures by purpose are: work 40% / 4% / 56% (06–09 / 09–15 / 15–20), school 35% / 12% / 54%, market 35% / 22% / 44%, other 24% / 23% / 52%.

**Calibration.** The defaults come from the WRI Nairobi rider survey (see [Transit wait time](#calibration-from-the-wri-rider-survey) and [References](references.md)), Q9 *"What is the Purpose of this Journey?"*. The number of interviews per hour reflects when interviewers were working, not when people travel, so the survey cannot give P(hour). The purpose mix within an hour does not depend on interviewer schedules, so it does give P(purpose | hour). By Bayes' rule, P(hour | purpose) ∝ P(hour) × P(purpose | hour). The model's own profile supplies P(hour), and the survey supplies the second factor, expressed relative to the overall purpose share: tilt = P(purpose | band) / P(purpose).

Processing:
- Timestamps are taken as UTC and shifted +3 h to Nairobi time (inferred; see the wait-time limitations above).
- Each respondent's departure from origin is estimated as interview time minus the midpoint of their reported access time (Q8: <5 → 2.5, 6–10 → 8, 11–20 → 15.5, 21–30 → 25.5, >30 → 35 min; 0 if missing).
- Purposes map to model purposes as Work → work, School → school, Shop or Market → market, Other and healthcare → other.
- 104 home-bound trips ("Other" with *home* in the free text) are excluded. This was done when the model simulated only the outbound trip. The survey has no "going home" answer, so most people heading home gave their activity's purpose; the tilt therefore describes all journeys, and the model applies it to outbound trips only (see the refit above).
- Departures before 06:00 fall into the first band and after 20:00 into the last. Bands hold 180–490 respondents each.

**Limitations.**
- **Adults only.** The survey only interviewed people aged 18 and over. "School" trips here are adult students (and perhaps escorts), which is why the school tilt is nearly flat. Children's trip timing is not represented in the survey; children's school trips get a separate rule instead (see **Children's school trips**, below).
- **Transit riders only**, as for the wait-time calibration. Walk-only trips may be timed differently.
- **Weekdays only.** The fieldwork ran Monday–Friday.
- **Survey purpose is "this journey".** Respondents heading home from work may have answered "Work" instead of "Other: home", so some evening work responses are likely trips home. The model applies the tilt to outbound trips, whose timing should differ; refitting the tilt for round trips (as the peak parameters were) is not done yet.
- The tilt has no demographic breakdown, so there are no `ParamModifier` multipliers for it.

<!-- TODO: find a source for children's trip timing for purposes other than school (e.g. JICA 2013) -->

### Children's school trips

**Children make only school trips.** By default, `DemographicParams.age_modifiers[AGE_CHILD]` sets `purpose_weight_mult = {"work": 0, "market": 0, "other": 0}`, so after renormalization every child (age ≤14) is assigned a school trip. Youth, adults and the elderly keep the population purpose weights (see [Trip purpose](#trip-purpose)); their school trips stand for secondary-school, college and university students. (Before 2026-11-07, purpose did not depend on age and about 39% of children were assigned work trips.)

Nairobi schools run from 08:00 to 15:30. Children's school trips therefore depart before 08:00: the same modifier carries `departure_window_h = {"school": [0.0, 8.0]}` (`SCHOOL_START_HOUR` in `model/agent.py`). A departure window sets the departure probability to zero outside [earliest, latest) for that purpose, on top of the profile and tilt. With the default profile this puts every child school departure between 06:00 (simulation start) and 08:00, mostly around the 07:30 peak.

- The window limits **departure**, not arrival: travel time isn't known until routes are assigned, so a child leaving at 07:55 arrives after 08:00.
- It applies only when demographics are enabled. Without `DemographicParams`, agents have no age, and school trips follow the survey tilt alone.
- Youth (15–19), which includes most secondary-school students, has no window and follows the adult survey tilt.
- **The trip home** leaves at school's end, 15:30 ± 30 min by default, for children and adult students alike (see [Return trips](#return-trips)).

`TravelBehaviorParams.departure_window_h` sets windows for the whole population (empty by default). Windows from the base parameters and from the age, gender and SES modifiers combine by **intersection**; if they don't overlap, the window for that purpose is dropped with a logged warning.

## Return trips

Every agent who reaches its destination makes a trip home the same day. When it arrives, the model sets the time it leaves again, then plans the route home for that departure time, by the same rules as the outbound trip ([Mode split](#mode-split)):

- **Work and school:** leave at a clock time drawn from Normal(mean, SD): work 17:00 ± 1 h, school 15:30 ± 30 min, but no sooner than `min_stay_min` (60 min) after arriving.
- **Market and other:** stay for a dwell time drawn from a lognormal distribution with median 45 min (market) or 60 min (other) and log-SD 0.6 (so the middle 80% of market stays last 21–97 min), then leave. Market destinations are supermarkets and marketplaces; other destinations are places of worship, community centres and libraries (`data/amenities.py`). Health facilities are not a destination type: they appear only as workplaces, so trips for medical care are not modelled separately.

| Parameter | Default | Source |
|---|---|---|
| `return_trips` | `True` | `False` restores one-way trips |
| `work_end_hour_mean`, `work_end_hour_std` | 17.0, 1.0 h | assumption; Kenya's public-service working hours are 08:00–17:00 |
| `school_end_hour_mean`, `school_end_hour_std` | 15.5, 0.5 h | Nairobi school day 08:00–15:30 (`SCHOOL_END_HOUR`) |
| `min_stay_min` | 60 min | assumption |
| `market_dwell_median_min` | 45 min | assumption |
| `other_dwell_median_min` | 60 min | assumption |
| `dwell_sigma_log` | 0.6 | assumption |

- **Walk or ride home.** The trip home reuses the agent's outbound walk/ride draw, so the mode choice agrees with the outbound one, except where the distance home differs enough to cross the draw. A rider draws a fresh boarding wait, and the transit options depend on the time it leaves. In a 3,000-agent run, 2,635 of 2,854 agents who set off home used the same mode both ways.
- **Days that run out.** A trip home due to leave after 20:00 (the end of the simulated day) is not simulated, and neither is the rest of a trip still under way at 20:00. In a 3,000-agent baseline run, 90% of travellers were home by 20:00. Most of the rest were on market or other errands.
- **Random numbers.** One standard-normal draw per agent (the `returns` random stream) sets both rules, so a sensitivity run that changes a mean or median shifts every agent's return time without reshuffling who leaves early or late.
- **Outputs.** `ScenarioResult.agent_exposure_degC_min` is the whole day's exposure; `agent_outbound_exposure_degC_min` is the part picked up on the way out. `agent_modes` is the outbound mode and `agent_return_modes` the mode home. `trip_log` has one entry per finished leg, marked `outbound` or `return`.

**Effect.** In a 3,000-agent baseline run, round trips raise mean exposure from 95 to 291 °C·min (above 26 °C UTCI) and time outdoors from 34 to 63 minutes. Two-thirds of the exposure is picked up on the way home, because trips home fall in the hot afternoon while most outbound trips leave in the cooler early morning.

<!-- TODO: find Nairobi sources for work end times and for activity durations (shopping, worship, community activities); JICA 2013 person-trip data may have them -->

## Mode split

Whether a trip is walked the whole way depends on its length and purpose. Each agent walks with probability *P*<sub>walk</sub>(*d*, purpose), where *d* is the shortest walking-network distance from home to destination. Everyone else plans a route that may ride a matatu or bus (see [ABM core](../dev/abm-core.md#transit-routing--route_transit)). Such a route can still turn out to be all walking, if no transit route is in service or the drawn wait exceeds the agent's tolerance.

*P*<sub>walk</sub> comes from the walk-split model of the JICA Nairobi master plan (JICA 2014, Appendix 4, §A4.5.3; `articles/jica_appendix3_2012.pdf`), fitted to the 2013 Nairobi household person-trip survey:

| Purpose (model → JICA) | Trips ≥ 1.3 km: walk share (%) | Trips < 1.3 km |
|---|---|---|
| work → Work | 37.948 − 12.19 ln *d*<sub>km</sub> | 67.2% |
| school → School | 59.215 − 19.17 ln *d*<sub>km</sub> | 76.5% |
| market, other → Others | 51.848 − 15.40 ln *d*<sub>km</sub> | 82.7% |

| Parameter | Default | Meaning |
|---|---|---|
| `walk_choice` | `"distance"` | `"fixed_share"` restores the earlier rule: a fixed `walk_only_share` (0.55) of agents walk regardless of distance |
| `walk_share_curve` | JICA interzonal curves (above) | [intercept %, slope % per ln km] per purpose |
| `walk_share_intrazonal` | JICA 2013 intrazonal shares | % walking for trips shorter than `walk_intrazonal_max_km` |
| `walk_intrazonal_max_km` | 1.3 | see below |
| `walk_share_shift_pp` | 0 | percentage points added at every distance (for sensitivity analysis) |

**Why two parts.** JICA's diversion curves model trips *between* its traffic zones; short trips within a zone have a separate, flat walk share. Applied to very short trips, the curves give too little walking: 74% of 50 m work trips. The model mirrors JICA's structure. Trips shorter than 1.3 km get the 2013 intrazonal share for their purpose; longer trips get the curve. 1.3 km is the mean distance between two random points in an average Nairobi small zone (City of Nairobi: 106 zones, ~6.6 km² each, so ~2.9 km across). The switch causes a jump at 1.3 km (work: 67% just below, 35% just above), as in JICA's own model.

**Check.** Tatah et al. (2023), from the same 2013 survey, report walking as the main mode of 43% of Nairobi trips. At the calibrated β and walking weight, the model walks 43% of trips the whole way (see [Calibration](#calibration-of-β-and-the-walking-time-weight)). The curves set the walk share *given* trip length, so this checks the trip-length distribution (β) against an independent source.

**Limitations.**
- **Car trips are not modelled.** JICA's walk shares are of all trips, including by car (2013 household car ownership 29%). In the model, everyone who doesn't walk is offered transit, so the motorised share is all matatu/bus.
- **Survey year 2013**, a decade before the heat data and the rider survey.
- **No variation by income or car ownership** beyond what the curves average over. JICA's intrazonal shares differ by car ownership (e.g. work 35% for car owners vs 75% for others).

## Trip purpose

| Purpose | Default weight |
|---|---|
| Work | 0.40 |
| School | 0.20 |
| Market | 0.25 |
| Other | 0.15 |

These weights apply to youth, adults and the elderly. Children (age ≤14) make only school trips (see [Children's school trips](#childrens-school-trips)), so when demographics are enabled the population-wide mix shifts towards school: with the WorldPop age mix of the study area (~27% children), about 42% of all agents make school trips.

<!-- TODO: cite purpose distribution from JICA 2013 or other Nairobi surveys -->

## Destination choice

Each agent's destination is drawn from the OSM amenities of its trip purpose, weighted by distance<sup>−β</sup> from home (distance floored at 25 m; the home node itself is excluded).

| Parameter | Default | Source |
|---|---|---|
| `destination_distance_decay` (β) | 1.5 | WRI rider survey Q11, jointly with `walk_time_weight` (below) |

Because the number of candidate destinations at distance *d* grows roughly in proportion to *d*, β = 1 (the earlier, uncalibrated rule) makes trip lengths almost uniform up to the edge of the study area; larger β favours nearby destinations. The default of 1.5 matches the median time on board reported by bus and matatu riders, and gives the 43% walk share of the 2013 JICA survey. β is calibrated with the walking-time weight; see [Calibration of β and the walking-time weight](#calibration-of-β-and-the-walking-time-weight).

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

### Walking-time weight in route choice

| Parameter | Default | Source |
|---|---|---|
| `walk_time_weight` | 5.0 | WRI rider survey Q8, jointly with β |

When an agent that may ride plans its route, each minute of walking counts `walk_time_weight` times a minute on board (waiting is charged at its expected value, unweighted). The weight changes which route is chosen, not how long the walk takes. Transport planning commonly weights walking 1.5–2.5× in-vehicle time, since people dislike walking to and between stops more than sitting in a vehicle.

With a weight of 1 (pure time minimisation), simulated riders walked past nearby stops to reach more direct routes. Their median walk to the first stop was 21 minutes, though the median home is 7 minutes from a boardable stop; only 15% boarded at their nearest stop.

### Calibration of β and the walking-time weight

`nairobi_heat_abm/calibration.py` (`python -m nairobi_heat_abm.calibration`) fits both parameters to two questions of the WRI rider survey, bus and matatu respondents only:

| Survey question | Respondents | Model counterpart | Mainly identifies |
|---|---|---|---|
| Q8 "How long did it take you to access this stage?" | 1,227 who walked to the stage | walk from home to the first boarding stop, on transit trips | walking-time weight |
| Q11 "How long does this trip usually take you?" | 1,482 | boarding the first vehicle to leaving the last, on transit trips | β (through trip length) |

The calibration was run with the JICA distance-based walk choice ([Mode split](#mode-split)), over a grid of β (1.0–1.8) × weight (3–6); an earlier grid under the old fixed walk-only share covered β 0.5–3.0 × weight 1–6 and established the method. Each cell pools 2 seeds of 3,000 agents. In each cell, the model's transit trips were binned like the survey answers, and the fit to each question was scored with the multinomial log-likelihood.

**Adopted: median matching.** The model can't reproduce the *shape* of either survey distribution at any β and weight. Survey answers are tightly bunched (55% of access walks at 6–10 minutes, 72% of rides at 11–30 minutes); the model's are much more spread out. Maximising the full-distribution likelihood therefore chases the tails: in the first grid its best cell ran to the edge (β = 0.75, weight 6), with a median ride of 28 minutes against 22.7 surveyed. The adopted calibration matches the medians instead (`calibration.py::median_match`):

- **Walking-time weight: 5.0.** The median access walk falls from 21 min (weight 1) to 9.5 (3), 8.8 (4) and 8.5 (5), then levels off (8.2 at 6). It never reaches the survey's 7.6 minutes, because the median home is itself 7 minutes from a boardable stop. The weight is set where the Q8 fit stops improving by more than simulation noise (log-likelihood within 10 of the best; weight 5 vs 6 differ by at most 2).
- **β: 1.5.** At weight 5, the β at which the model's median time on board equals the survey's 22.7 minutes (23.9 at β = 1.4, 21.4 at 1.6). The medians carry about ±1 minute of simulation noise, about ±0.1 in β.

**Independent check: walk share.** Not fitted, but at the calibrated values 43% of trips are walked the whole way (40% at β = 1.4, 46% at 1.6), matching the 43% walking main-mode share that Tatah et al. (2023) report from the same 2013 survey JICA's curves come from. Travellers spend a mean of about 34 minutes outdoors (median walk-only trip 18 minutes).

Results are in `outputs/calibration_jica/` (`calibration_grid.csv`, `calibration_bins.csv`, `survey_bins.csv`, `calibration_fit.json`). The grid run was stopped by low system memory with 17 of 20 cells done; the missing three (weight 6, β 1.6–1.8) don't affect either rule. The superseded fixed-share calibration is in `outputs/calibration/`.

Fit near the calibrated values (weight 5, mean of β = 1.4 and 1.6):

| Q8 access walk | <5 min | 6–10 | 11–20 | 21–30 | >30 |
|---|---|---|---|---|---|
| Survey (N = 1,227) | 27% | 55% | 17% | 1% | 0.1% |
| Model | 33% | 26% | 24% | 8% | 9% |

| Q11 time on board | 1–10 min | 11–20 | 21–30 | 31–40 | >40 |
|---|---|---|---|---|---|
| Survey (N = 1,482) | 5% | 38% | 35% | 16% | 7% |
| Model | 25% | 21% | 19% | 15% | 21% |

Model: 2 seeds × 3,000 agents per cell, ~3,400 transit trips each. Medians: access walk 8.6 min (survey 7.6), time on board 22.7 min (survey 22.7).

**A weight of 5 is high.** Studies usually find walking weighted 1.5–2.5× in-vehicle time. Here the weight also stands in for something the network lacks. Nairobi matatus pick up and set down along their routes, but the model only allows boarding at the GTFS stages, so to match real access times riders must be strongly steered to the nearest stage. The sensitivity analysis varies the weight from 2 to 6.

**Why Q8 alone couldn't calibrate β.** With the weight fixed at 1, raising β from 0.5 to 4 shortened trips (outdoor time fell from 174 to 28 minutes) but barely moved the access walk (median 21 to 15 minutes, against ~7 in the survey). Access time is set by route choice, not trip length. The likelihood kept improving with β only because transit use collapsed.

**Limitations.**
- **Q11 interpretation.** The question is asked at the stage, about "this trip" on this mode, after the access question, so it is compared with time on board. If respondents included access and waiting, the model's door-to-door time is the right comparison instead, and β would come out higher (shorter trips). Both log-likelihoods are recorded in `calibration_grid.csv`.
- **Riders only.** Both questions describe transit trips, so β is identified only through trips long enough to ride. Walk-only trip lengths follow from the same β but are not checked against data.
- **Intervals are optimistic.** They reflect the survey's sample size, not simulation noise or model structure.
- **One weight for everyone.** No variation by age, gender or income.
- **Walk/ride choice.** Calibrated together with the JICA distance-based walk choice (see [Mode split](#mode-split)). An earlier calibration under a fixed 55% walk-only share (β = 1.2, weight 5) is superseded; under that rule travellers spent ~110 minutes outdoors. (Those figures, and the ~51 minutes in the calibration grid, also carry the movement bug described in [ABM core](../dev/abm-core.md#continuous-movement-within-a-tick); with it fixed, ~34 minutes.)
- **Outbound trips only, and before the round-trip refit.** The calibration compares planned *outbound* routes with Q8 and Q11; trips home don't enter it. It was run with the earlier departure profile. Departure time changes only which transit routes are in service, so the refit outbound profile is not expected to move β or the walking weight much, but this hasn't been rechecked.

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
- `departure_window_h` — not a multiplier: a per-purpose [earliest, latest) departure window, combined with the base and other attributes' windows by intersection (**Children's school trips**, above).

`trip_rate_distribution` and `departure_profile` (string enums, not magnitudes) have no modifier — multiplying a category label isn't meaningful. `transit_mean_wait_min` has none because it describes the transit service rather than the traveller, and because route assignment (`assign_routes()`) reads only the base `TravelBehaviorParams`, so a per-segment value would never take effect.

The three attributes combine **independently and multiplicatively** — e.g. a youth x female x informal-settlement agent's effective `trip_rate_mean` is `base x age_mult x gender_mult x ses_mult` — rather than each (age, gender, SES) combination having its own independently-calibrated profile. This was a deliberate simplification to keep the parameter count tractable for calibration and RDM sweeps, at the cost of not capturing genuine three-way interaction effects (e.g. if young informal-settlement women behave differently from what their individual age/gender/SES effects alone would predict).

<!-- TODO: cite empirical differentials in trip rate, purpose mix, and travel probability by age/gender/SES for Nairobi (or comparable East African cities) to justify default modifier values; all modifier dicts default empty/no-op except children's (school-only purpose, school departure before 08:00) -->

## Uncertainty ranges for RDM

All parameters above are varied in RDM sweeps. See [RDM approach](rdm-approach.md) for how ranges are chosen and how sensitivity is assessed.

Demographic modifiers, `travel_probability`, and the newly-modifiable fields (departure timing, mode split, walk speed, transit wait tolerance) are not currently swept by the RDM pipeline (`rdm/sampling.py` only varies the subset of base `TravelBehaviorParams` fields in `STANDARD_RANGES`) — this is a known gap, not a design decision, and would be natural follow-up work once modifier values are empirically grounded.

See [References](references.md) for full citations.
