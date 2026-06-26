# RDM approach

→ [Back to index](index.md)

## What is Robust Decision Making?

Robust Decision Making (RDM) is an analytic framework for evaluating policies or designs under deep uncertainty — situations where probability distributions over key parameters cannot be specified with confidence. Instead of running a single best-estimate scenario, RDM explores a wide range of plausible futures and asks: under which conditions does the outcome of interest exceed a threshold of concern?

<!-- TODO: cite foundational RDM literature (Lempert et al., RAND) -->

## Why RDM for heat exposure modelling?

The key parameters governing heat exposure in Nairobi — travel behaviour, mode split, departure times, pedestrian speeds — are not well-characterised by existing survey data. Survey evidence is limited, dated, or reflects conditions before recent climate trends.

Rather than treating uncertain parameters as fixed point estimates, we treat them as ranges to be explored. The outputs of an RDM sweep are not probability distributions over outcomes; they are a catalogue of which input combinations drive exposure above threshold.

<!-- TODO: expand with specific justification for why each uncertain parameter belongs in the sweep rather than being fixed -->

## Latin Hypercube Sampling

We generate scenarios using Latin Hypercube Sampling (LHS), a space-filling design that ensures coverage of the parameter space more efficiently than simple random sampling. With N scenarios and K parameters, LHS guarantees that each parameter's range is divided into N equal-probability strata with exactly one sample per stratum.

<!-- TODO: cite McKay et al. 1979 original LHS paper; discuss number of scenarios needed for stable sensitivity estimates -->

## Parameter ranges

The seven parameters varied in the standard sweep, and the justification for each range, are documented in [Travel behaviour](travel-behaviour.md).

## Outcome metrics

For each scenario the model computes:

| Metric | Description |
|---|---|
| `mean_exposure` | Mean °C·min across all agents |
| `p90_exposure` | 90th-percentile °C·min — the exposure of the most-exposed decile |
| `pct_above_threshold` | Percentage of agents exceeding the flag threshold (default 60 °C·min) |
| `mode_exposure_gap` | Difference in mean exposure between walk-only and transit users |

<!-- TODO: justify choice of p90 over mean as the primary policy-relevant metric; note that the tail is where heat health risk is concentrated -->

## Sensitivity analysis

Sensitivity is assessed using the Spearman rank correlation between each input parameter and each outcome metric across the full scenario set. Spearman correlation is used rather than Pearson because the input-output relationship may be non-linear and non-monotone.

<!-- TODO: discuss limitations of rank correlation for sensitivity in the presence of interactions; mention possible extension to variance-based sensitivity indices (Sobol) -->

## How to read an RDM output

<!-- TODO: guide for non-technical readers on how to interpret the parallel coordinates plot and the outcome table; what "scenario X drives high p90 exposure" means in plain language -->

See [References](references.md) for full citations.
