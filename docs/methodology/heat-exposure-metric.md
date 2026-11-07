# Heat exposure metric

→ [Back to index](index.md)

## What the model measures

The model accumulates heat exposure for each agent in **°C·min above 26 °C UTCI**: the degrees by which the Universal Thermal Climate Index exceeds 26 °C, times the minutes spent outdoors at that level. At each 60-second timestep, the agent's interpolated position is sampled from the hourly UTCI raster, and the excess over the threshold is added to a running total:

```
exposure += max(UTCI_°C − 26, 0) × outdoor_share × (timestep_s / 60)
```

where `outdoor_share` is the fraction of the timestep spent walking or waiting. Agents move continuously, through as many street segments as the timestep allows, so time outdoors equals walking distance ÷ walking speed plus waiting time (see [ABM core](../dev/abm-core.md#continuous-movement-within-a-tick)). UTCI is sampled at the agent's position at the end of the timestep. Minutes at or below 26 °C add nothing, so a 20-minute walk at UTCI 28 °C adds 40 °C·min and the same walk at 25 °C adds none. The threshold is `SimulationParams.utci_threshold_c`.

The model also keeps the raw total, UTCI × outdoor minutes, without the threshold (`ScenarioResult.agent_utci_degC_min`). Divided by minutes outdoors it gives the mean UTCI an agent experienced, which the sensitivity analysis reports as `mean_temp_experienced`.

**Why a threshold.** With raw UTCI, which varies by only a few degrees across the daytime hours travellers experience, exposure was almost proportional to minutes outdoors: a minute at 26 °C counted nearly as much as a minute at 32 °C. Counting only the excess over 26 °C makes the hot hours and places count for much more than the mild ones. 26 °C is the lower bound of UTCI's "moderate heat stress" category, so the metric counts only minutes under at least moderate heat stress (UTCI assessment scale: 9–26 °C no thermal stress, 26–32 moderate, 32–38 strong, 38–46 very strong heat stress; Bröde et al. 2012, Błażejczyk et al. 2013).

"Outdoor" is enforced in code, not just in name: `model/scheduler.py::tick()` skips this accumulation entirely while an agent's mode is `MODE_TRANSIT` (actually riding a matatu, as opposed to `MODE_WAIT` standing at a stop) — a passenger inside a vehicle isn't exposed to ambient heat the way a walking or waiting pedestrian is.

### Where exposure happens: street segments and stops

The same heat is also attributed to the place it was taken on (`model/segment_exposure.py`): to the street segment an agent is walking along, or to the stop where it waits to board. For each segment, the model and the GIS export (`data/export.py`, notebook §3.5 and §3.7) report:

- `heat_degC_min`: the total over everyone who walked it. Busy, long segments score high.
- `heat_degC_min_per_100m`: the same per 100 m of street.
- `mean_heat_degC`: `heat_degC_min / person_min`, the average UTCI excess over 26 °C people experienced there.
- `n_persons` and `heat_degC_min_per_person`: the exposure **one person** takes on walking the segment. It reflects how long and how hot the segment is to walk, not how many people use it.

<!-- TODO: contrast this with wet-bulb globe temperature (WBGT), physiological equivalent temperature (PET), and simpler ambient temperature approaches; justify why °C·min is tractable given our input data -->

## Why not a comfort index?

<!-- TODO: WBGT and PET require humidity, wind speed, radiation — data we don't have at fine spatial resolution over Nairobi; discuss trade-off -->

## Physiological basis

<!-- TODO: link °C·min cumulative exposure to heat strain literature; note that the metric is monotone in both intensity and duration, which is the relevant property for comparing scenarios -->

## Threshold value

Two thresholds are involved:

- **The UTCI threshold, 26 °C**, defines the metric itself (above).
- **The flag threshold, 60 °C·min** (`rdm/analysis.py::THRESHOLD_DEFAULT_DEGC_MIN`), marks a day's exposure as high in the older RDM outcome table (`pct_above_threshold`). On the threshold metric, 60 °C·min is, for example, 30 minutes outdoors at UTCI 28 °C; 50 minutes at 32 °C accumulates 300 °C·min.

<!-- TODO: justify threshold with reference to heat-strain literature or calibrate against field observations -->

## Limitations

<!-- TODO: the metric ignores thermal adaptation, clothing, physiological variation across agents, indoor rest periods between trips -->

See [References](references.md) for full citations.
