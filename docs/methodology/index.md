# Methodology notes

Design rationale for the Nairobi Heat Exposure ABM. Audience: researchers and journalists who want to understand why the model is built the way it is — the scientific basis, the data choices, and the uncertainties we acknowledge.

## Contents

| Document | What it covers |
|---|---|
| [Study context](study-context.md) | Why Nairobi, what problem we are addressing, scope and limits |
| [Heat exposure metric](heat-exposure-metric.md) | What °C·min measures, why it is the right unit, physiological basis |
| [Transport network](transport-network.md) | OSM walking network and matatu GTFS — what they capture and what they miss |
| [Population model](population-model.md) | WorldPop-based agent spawning, representativeness, known biases |
| [Travel behaviour](travel-behaviour.md) | Parameter choices, empirical basis, what survey evidence exists for Nairobi |
| [RDM approach](rdm-approach.md) | Why Robust Decision Making, what Latin Hypercube Sampling does, how to read the outputs |
| [References](references.md) | Full bibliography |

## Reading order

Readers new to the project should start with [Study context](study-context.md), then [Heat exposure metric](heat-exposure-metric.md). Readers primarily interested in uncertainty and scenario analysis should skip to [RDM approach](rdm-approach.md).

All claims that rest on published evidence cite the [References](references.md) list. Claims that rest on modelling assumptions are marked **[assumption]** and explain the sensitivity of results to that assumption.
