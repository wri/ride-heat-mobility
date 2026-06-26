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

## Uncertainty ranges for RDM

All parameters above are varied in RDM sweeps. See [RDM approach](rdm-approach.md) for how ranges are chosen and how sensitivity is assessed.

See [References](references.md) for full citations.
