# Population model

→ [Back to index](index.md)

## Agent spawning

Agents are spawned by sampling from the WorldPop 100 m resolution total-population grid for Kenya (`nairobipop_total.tif`). Grid cells are sampled with probability proportional to their estimated population count; each sampled cell is then snapped to the nearest walkable graph node.

<!-- TODO: describe the grid vintage (year), whether it captures informal settlement density well, known over/under-estimation areas in Nairobi -->

## What WorldPop represents

<!-- TODO: WorldPop uses satellite imagery + census data; discuss what it is and is not (residential population, not daytime activity population); implications for spawn distribution -->

## Per-demographic-group population rasters

Alongside the total-population raster, four demographic-group WorldPop rasters cover the same area: `nairobipop_children.tif` (age ≤14), `nairobipop_adult.tif` (age ≥20, which includes the elderly count below), `nairobipop_elderly.tif` (age ≥60), and `nairobipop_female.tif` (female, any age). These are loaded together via `data/population.py::load_population_rasters`, which reprojects every group raster onto the exact same pixel grid as `total` (regardless of each file's own native resolution/extent) so per-pixel values across rasters can be compared directly — see [Demographic composition](#demographic-composition) below for how they drive spatially-varying age/gender draws.

There is no raster for the 15–19 age band ("youth") or for male population specifically — both are reconstructed as residuals (`total` minus the other age groups; `total` minus `female`) rather than measured directly, since no rasters for them exist.

## What agents represent

Each agent in the model represents a **person-trip**, not a unique individual. A single person making three trips per day is represented as three agents with different departure times and destinations.

<!-- TODO: explain why this simplification is made and what it implies for interpreting results -->

## Population size and scaling

The default run uses 5,000 agents. Results are not automatically scaled to the full Nairobi population.

<!-- TODO: discuss how to interpret aggregate outputs given the agent count; note that relative comparisons across scenarios are valid regardless of scale -->

## Demographic composition

Agents can optionally carry **age group**, **gender**, and **socioeconomic/informality status**, via `DemographicParams` (`model/agent.py`). When a scenario doesn't set `SimulationParams.demographics`, none of this applies — agents are undifferentiated, exactly as before.

### Age and gender

Age is represented as one of four discrete groups — child, youth, adult, elderly — rather than continuous years, to match how demographic survey data and travel-behaviour differentials are typically reported. Gender is binary (male/female), matching WorldPop's sex-disaggregated data conventions.

Age and gender can be drawn one of two ways, controlled by `DemographicParams.population_raster_paths`:

- **Flat, non-spatial (default, `population_raster_paths=None`)**: drawn independently per agent from city-wide proportions set on `age_group_shares` / `gender_shares` — not spatially varying, exactly as before.
- **Spatially-varying (`population_raster_paths` set to the 5 rasters above)**: `data/demographics.py::draw_age_gender_spatial` looks up each agent's local group composition *at its own spawn pixel* and draws age/gender from that — an agent spawned in a pixel with a high elderly share is more likely to be drawn elderly, etc. `age_group_shares`/`gender_shares` are ignored in this mode. Concretely, at each pixel: `child` and `elderly` come directly from their own rasters; `adult` (20–59) is the `adult` raster (20+) minus `elderly` (since elderly is a subset of it); `youth` (15–19) is the residual `total − children − adult(20+)`; `female` comes directly from the `female` raster and `male` is the residual. Because each raster is reprojected independently, per-pixel values can fail to sum to exactly `total` near demographic boundaries (bilinear resampling doesn't preserve that identity) — probabilities are clipped to ≥0 and renormalized per agent rather than trusted to sum to 1 on their own. Age and gender are still drawn independently of each other given the pixel (there's no age×sex cross-tabulated raster to draw them jointly), and there's no correlation with SES beyond what both share spatially through the agent's spawn location.

<!-- TODO: cite Kenya census / KNBS age-sex pyramid for Nairobi to justify default flat shares -->

### Socioeconomic status / informality

SES is binary (formal / informal) and, unlike age/gender, is **spatially derived**: each agent's spawn location is tested against a polygon layer of informal-settlement boundaries (`data/demographics.py::assign_ses`, using a `geopandas` point-in-polygon join against `DemographicParams.informal_settlement_path`).

**Blocked on real data, same as the UTCI heat tiles** (see the RDM approach / heat surface docs): no Nairobi informal-settlement boundary file exists in this project yet. Until one is supplied, `informal_settlement_path` stays `None` and every agent is classified `SES_FORMAL` — a documented placeholder, not a silent failure. The join logic itself is implemented and tested against a synthetic polygon (`tests/test_demographics.py`).

<!-- TODO: identify and vet a real Nairobi informal-settlement boundary source — candidates to investigate include OSM/Map Kibera-style community mapping and KNBS/SDI slum enumeration data; confirm licensing and vintage before use -->

### Home-area context: ward, wealth and informality

For reporting only, each agent's home is also tagged with three area attributes (`data/ses.py::tag_homes`). None of them changes behaviour; they let results be broken down by where people live.

| Attribute | Source | Unit | Notes |
|---|---|---|---|
| Ward | geoBoundaries Kenya ADM3, 2020 IEBC wards (Runfola et al. 2020), CC BY 4.0 | polygon | point-in-polygon |
| Relative Wealth Index | Data for Good at Meta (Chi et al. 2022), CC BY-NC 4.0 | ~2.4 km tile (zoom-14 Bing quadkey) | relative within Kenya, not an absolute income; nearest tile centre |
| Morphological informality | IDEAMAPS, Morphological Informality Modelled Dataset in Nairobi, Kenya, v2 (Hafner et al. 2026), CC BY-NC 4.0 | 100 m cell of the GHS grid | low / medium / high, see below |

**Morphological informality** distinguishes planned from unplanned areas by the form of buildings and roads, as an indication of urban deprivation. The dataset's own class definitions:

- **Low (0):** "Buildings are larger, detached from one another, and regularly arranged. It is easy to visualise roads, pathways, or open spaces between them. Areas with no buildings are also categorised as low."
- **Medium (1):** "Buildings are small and close together (it can be hard to visualise roads, pathways, or spaces between them) OR buildings are irregularly arranged (with varying alignment to neighbouring structures). Roads are moderately present."
- **High (2):** "Buildings are small and close together AND buildings are irregularly arranged (with varying alignment to neighbouring structures). Roads are hard to visualise or they are absent."

The file has 110,463 cells: 58% low, 41% medium and under 1% high. It covers Nairobi's built-up core (longitude 36.61–37.04, latitude −1.42 to −1.12), so homes further east (e.g. Ruai) have no class: 261 of 10,000 agents in the notebook 01 run. The file's `focused` column marks cells chosen for validation campaigns and is not used. The method is described in the dataset's related ISPRS Archives paper (doi:10.5194/isprs-archives-XLVIII-M-7-2025-221-2025).

This layer is separate from the binary SES attribute above: it is a continuous-coverage morphology classification used for reporting, not a boundary layer of informal settlements, and it doesn't set `SES_INFORMAL`.

### How demographics affect behaviour

Rather than a fully independent travel-behaviour profile per (age x gender x SES) combination, each attribute value carries an optional multiplicative *modifier* (`ParamModifier`) that adjusts a base `TravelBehaviorParams` — see [Travel behaviour](travel-behaviour.md#demographic-modifiers). The three attributes' modifiers combine independently (age x gender x SES), not as a fully interactive segment table.

## Limitations

<!-- TODO: WorldPop does not capture time-of-day population distribution; agents spawn at residential locations at all hours regardless of actual presence; floating population (commuters from outside bbox) is not represented -->

Demographic composition is drawn once per agent and applies to whichever single trip that agent represents (see "What agents represent" above) — it does not model within-household correlation (e.g. that trips from the same household share a residence) or age/gender-correlated spatial sorting beyond what the informal-settlement join captures for SES.

See [References](references.md) for WorldPop citation and full bibliography.
