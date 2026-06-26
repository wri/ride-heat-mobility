# Heat exposure metric

→ [Back to index](index.md)

## What the model measures

The model accumulates heat exposure for each agent in **°C·min** (degree-Celsius × minutes of outdoor exposure). At each 60-second timestep, the agent's interpolated position is sampled from the heat raster and the instantaneous temperature is added to a running total:

```
exposure += temperature_°C × (timestep_s / 60)
```

<!-- TODO: contrast this with wet-bulb globe temperature (WBGT), physiological equivalent temperature (PET), and simpler ambient temperature approaches; justify why °C·min is tractable given our input data -->

## Why not a comfort index?

<!-- TODO: WBGT and PET require humidity, wind speed, radiation — data we don't have at fine spatial resolution over Nairobi; discuss trade-off -->

## Physiological basis

<!-- TODO: link °C·min cumulative exposure to heat strain literature; note that the metric is monotone in both intensity and duration, which is the relevant property for comparing scenarios -->

## Threshold value

The default flag threshold is **60 °C·min**. This means a trip where an agent walks for 50 minutes at 32 °C accumulates 1,600 °C·min — well above the flag. A 10-minute walk at 28 °C accumulates 280 °C·min.

<!-- TODO: justify threshold with reference to heat-strain literature or calibrate against field observations -->

## Limitations

<!-- TODO: the metric ignores thermal adaptation, clothing, physiological variation across agents, indoor rest periods between trips -->

See [References](references.md) for full citations.
