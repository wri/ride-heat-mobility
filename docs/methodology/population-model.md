# Population model

→ [Back to index](index.md)

## Agent spawning

Agents are spawned by sampling from the WorldPop 100 m resolution population grid for Kenya. Grid cells are sampled with probability proportional to their estimated population count; each sampled cell is then snapped to the nearest walkable graph node.

<!-- TODO: describe the grid vintage (year), whether it captures informal settlement density well, known over/under-estimation areas in Nairobi -->

## What WorldPop represents

<!-- TODO: WorldPop uses satellite imagery + census data; discuss what it is and is not (residential population, not daytime activity population); implications for spawn distribution -->

## What agents represent

Each agent in the model represents a **person-trip**, not a unique individual. A single person making three trips per day is represented as three agents with different departure times and destinations.

<!-- TODO: explain why this simplification is made and what it implies for interpreting results -->

## Population size and scaling

The default run uses 5,000 agents. Results are not automatically scaled to the full Nairobi population.

<!-- TODO: discuss how to interpret aggregate outputs given the agent count; note that relative comparisons across scenarios are valid regardless of scale -->

## Limitations

<!-- TODO: WorldPop does not capture time-of-day population distribution; agents spawn at residential locations at all hours regardless of actual presence; floating population (commuters from outside bbox) is not represented -->

See [References](references.md) for WorldPop citation and full bibliography.
