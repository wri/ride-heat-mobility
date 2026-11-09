---
title: "Heat exposure of travellers in Nairobi: main results"
subtitle: "Figures and tables from the agent-based model (notebook 01; behavioural sensitivity: notebook 02)"
---

## Model run

20,000 agents on one simulated weekday, 06:00–20:00, in 60-second steps (random seed 42). Each agent lives at a location drawn from WorldPop population density and makes a round trip: out from home to a destination chosen by trip purpose (work, school, market, other), a stay at the destination, and back. Each trip is walked the whole way or ridden by matatu or bus, by distance-based walk shares (JICA 2014) and a route choice calibrated to the WRI Nairobi rider survey (2023). Heat exposure is the sum, over every minute spent outdoors (walking or waiting at a stop), of the degrees by which the Universal Thermal Climate Index (UTCI) at the agent's position exceeds 26 °C, the lower bound of UTCI's moderate heat stress category; minutes riding inside a vehicle add nothing. UTCI comes from 10 m hourly rasters for 14 March 2025.

Across all agents, mean daily exposure is 269 °C·min (median 194; 90th percentile 570). 3.6% of agents have zero exposure: all their outdoor minutes were at UTCI of 26 °C or below.

## Model parameters

Table 1 lists every behavioural rule and parameter of the main run, which agent attributes it depends on, and its source. Age group and sex are assigned to each agent from WorldPop at its home location. Age sets two rules, both for children (0–14): they make only school trips, and they leave for school before 08:00. Sex sets none. Purpose shares of everyone over 14, mode choice, walking speed and waiting behaviour are the same for all ages and both sexes: the calibration uses no age or sex breakdowns, the WRI rider survey interviewed only adults (18+) riding buses and matatus, and the JICA walk-share curves are given by trip purpose only. Wealth (RWI) and informality are used only to group results, not to set behaviour. Table 2 gives the resulting composition of the simulated population and its mix of trip purposes.

| Rule or parameter | Value in the main run | Differs by | Source |
|:---|---:|---:|---:|
| *Who travels* | | | |
| Home location | Drawn in proportion to population (100 m grid), snapped to the nearest street node | — | WorldPop 100 m population, Kenya |
| Age group | Child 0–14, youth 15–19, adult 20–59, elderly 60+; drawn from the age mix of the agent's home grid cell | Home location | WorldPop age-group rasters (youth = total − children − adults 20+) |
| Sex | Drawn from the female share of the home grid cell, independently of age | Home location | WorldPop female-population raster |
| Trips per agent | One round trip: home → destination → home. Every agent travels (travel probability 1) | — | Model design |
| Trip purpose | Children 0–14: school only. Everyone else: work 40%, school 20%, market 25%, other 15% | Age: children vs. others (same for both sexes) | Children: school attendance; others: assumption |
| Destination | OpenStreetMap amenity of the trip's purpose, chosen with weight distance^−1.5^ | Purpose, distance | Calibrated: WRI rider survey Q11 (median time on board 22.7 min) |
| *When* | | | |
| Outbound departure time | Two normal peaks (SD 30 min) at 07:24 (66%) and 16:45 (14%), 20% spread evenly over 06:00–20:00 | — | Assumption, refit so outbound + return departures match an assumed all-journey profile |
| Departure timing by purpose | Profile × purpose multiplier per time band, e.g. work ×1.49 at 06:00–09:00, market ×1.50 at 17:00–20:00 | Purpose | WRI rider survey Q9 (adults ≥ 18, bus/matatu riders, weekdays) |
| Children's school departures | Leave before 08:00 (school starts 08:00) | Age: children 0–14 only | Nairobi school day 08:00–15:30 |
| Trip home: work | Leave at 17:00 ± 1 h (normal), at least 60 min after arriving | Purpose | Assumption; Kenya public-service hours 08:00–17:00 |
| Trip home: school | Leave at 15:30 ± 30 min (normal), at least 60 min after arriving | Purpose (all ages alike) | Nairobi school day 08:00–15:30 |
| Trip home: market, other | Stay a log-normal time, median 45 min (market), 60 min (other); log-SD 0.6 | Purpose | Assumption |
| *How* | | | |
| Walk the whole way | Probability by trip length d (km): under 1.3 km, work 67%, school 76%, market/other 83%; longer trips, work 37.9 − 12.2 ln d %, school 59.2 − 19.2 ln d %, market/other 51.8 − 15.4 ln d %; none beyond 15 km | Purpose, distance | JICA (2014) Nairobi walk-split curves, 2013 household survey; cap: last distance with walk trips in JICA's data |
| Route for everyone else | Least cost: time riding + 5 × time walking + expected wait; may still be all walking | — | Calibrated: WRI rider survey Q8 (access walk time) |
| Walking speed | 1.2 ± 0.15 m/s (normal, one draw per person) | None (same for all ages) | Common pedestrian default |
| Wait to board | Exponential, mean 5.65 min | — | WRI rider survey Q15 (bus and matatu riders, n = 1,484) |
| Wait tolerance | If the drawn wait exceeds 15 min, walk instead when walking is no slower than waiting and riding; otherwise wait | — | Assumption |

Table: **Table 1.** Agent behaviour as modelled in the main run.

Note. Differs by: the agent attributes a rule depends on; — = the same for every agent. Age changes only children's trips (school only, leaving before 08:00); sex changes nothing. Where a rule depends on purpose, it applies equally to every age and sex (for example, adult students and children both head home from school at 15:30). Calibrated: destination distance decay and the walking-time weight were fitted jointly to the WRI Nairobi rider survey (2023), and with the JICA curves they give a 43% walk share, as reported by Tatah et al. (2023). WRI rider survey: adults 18 and over, bus and matatu riders, weekdays.

| Group | n | % of agents | Work (%) | School (%) | Market (%) | Other (%) |
|:---|---:|---:|---:|---:|---:|---:|
| All agents | 20,000 | 100.0 | 29 | 42 | 19 | 11 |
| *Age group* | | | | | | |
| Child (0–14) | 5,424 | 27.1 | 0 | 100 | 0 | 0 |
| Youth (15–19) | 1,759 | 8.8 | 40 | 20 | 25 | 15 |
| Adult (20–59) | 12,395 | 62.0 | 40 | 20 | 26 | 15 |
| Elderly (60+) | 422 | 2.1 | 42 | 20 | 25 | 13 |
| *Sex* | | | | | | |
| Female | 9,663 | 48.3 | 30 | 41 | 18 | 11 |
| Male | 10,337 | 51.7 | 28 | 42 | 19 | 11 |

Table: **Table 2.** Simulated population by age group and sex, and its trip purposes (% of each group).

Note. Age group and sex come from the WorldPop rasters at each agent's home; youth (15–19) is the residual of total minus children and adults 20+. Children make only school trips; agents over 14 share the population purpose weights, so their school trips stand for secondary-school, college and university students. Overall, 42% of agents make school trips. Purposes are not stored in the model's GIS export; they were reproduced exactly from the run's random seed (see purposes.py).

## Figures

![**Figure 1.** Distribution of daily heat exposure per person, by the mode of the outbound trip. Exposure is the sum over outdoor minutes (walking and waiting at stops) of the degrees by which UTCI exceeds 26 °C, over the outbound trip and the trip home. Dashed lines: medians. Bins of 25 °C·min. Filled bars at right: share of agents with exposure ≥ 1,500 °C·min, plotted off-scale (206 agents, 1% of all; maximum 3,413). n = 20,000 agents.](fig1_exposure_distribution.svg){width=3.5in}

![**Figure 2.** Where exposure is picked up on the street network. (a) Total exposure accumulated on each street segment by everyone who walked it (65,136 segments with non-zero exposure). (b) Exposure of one person walking the segment (total divided by the number of distinct people), shown for segments walked by at least 5 people. Both directions of a street are combined. Light grey: segments walked but with no exposure above the threshold, and ward boundaries. Log colour scales. Place labels mark selected wards (CBD: Nairobi Central ward; Kibera: Laini Saba and Sarangombe wards; Dandora and Eastleigh: their wards combined).](fig2_segment_maps.svg){width=6.5in}

![**Figure 3.** (a) Mean daily exposure per resident, by home ward; wards with fewer than 15 simulated residents are hatched. (b) Morphological informality of each 100 m cell, the layer used to group agents by home informality in Figure 4b and Table 5; hatched: outside the layer's coverage. The least-exposed wards in (a) are the dense central ones where (b) shows medium and high informality. Both maps are clipped to the study area. Place labels mark selected wards (CBD: Nairobi Central ward; Kibera: Laini Saba and Sarangombe wards; Dandora and Eastleigh: their wards combined). Panel (b) is adapted from the IDEAMAPS Morphological Informality Modelled Dataset in Nairobi, Kenya, v2 (Hafner et al. 2026; doi:10.5281/zenodo.18313572), licensed under CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/); changes: reprojected and clipped to the study area.](fig3_ward_map.svg){width=6.5in}

![**Figure 4.** Mean daily exposure per person by (a) the Relative Wealth Index quintile and (b) the morphological informality of the agent's home location, for all agents and by outbound mode. Bars: 95% bootstrap confidence intervals (2,000 resamples).](fig4_wealth_informality.svg){width=6.5in}

## Tables

| Group | n | Zero exposure (%) | Mean per person [95% CI] | Median per person | 90th pct. per person |
|:---|---:|---:|---:|---:|---:|
| All agents | 20,000 | 3.6 | 269 [265–273] | 194 | 570 |
| *Outbound mode* | | | | | |
| Walked (outbound trip) | 8,351 | 5.0 | 275 [268–283] | 136 | 751 |
| Rode transit (outbound trip) | 11,649 | 2.5 | 264 [260–268] | 223 | 502 |
| *Age group* | | | | | |
| Child (0–14) | 5,424 | 0.0 | 312 [304–319] | 241 | 608 |
| Youth (15–19) | 1,759 | 5.7 | 252 [238–267] | 167 | 544 |
| Adult (20–59) | 12,395 | 4.9 | 252 [247–258] | 174 | 554 |
| Elderly (60+) | 422 | 2.6 | 284 [253–316] | 197 | 585 |
| *Gender* | | | | | |
| Female | 9,663 | 3.6 | 271 [265–277] | 194 | 575 |
| Male | 10,337 | 3.6 | 267 [261–272] | 194 | 565 |

Table: **Table 3.** Daily heat exposure per person (°C·min above 26 °C UTCI), overall and by group.

Note. Outbound mode is the mode of the trip from home; the trip home can differ (in a 3,000-agent check, 92% of agents used the same mode both ways). Age group and gender are drawn from WorldPop population grids at the home location. 95% confidence intervals of the mean are bootstrap percentile intervals.

| Destination type | n | Walked out (%) | Zero exposure (%) | Mean per person [95% CI] | Median per person | 90th pct. per person | Mean per person, walked | Mean per person, transit |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| Work | 5,787 | 38 | 0.2 | 223 [217–229] | 162 | 467 | 214 | 229 |
| School | 8,330 | 44 | 0.0 | 319 [313–325] | 244 | 633 | 312 | 325 |
| Market | 3,729 | 40 | 14.1 | 228 [218–239] | 125 | 551 | 271 | 199 |
| Other | 2,154 | 44 | 8.4 | 269 [255–285] | 176 | 622 | 283 | 259 |

Table: **Table 4.** Daily heat exposure per person (°C·min above 26 °C UTCI) by destination type (trip purpose).

Note. Destination types: Work: offices, shops, commercial and industrial buildings and banks, plus schools, markets and health facilities as workplaces; School: schools, colleges and universities; Market: supermarkets and marketplaces; Other: places of worship, community centres and libraries (OpenStreetMap). Each agent makes one round trip, to one destination of its trip purpose and back; destinations are chosen with weight distance^−1.5^. Walked out: share whose outbound trip was walked the whole way. Mean, walked / transit: mean exposure by outbound mode. Purposes are not stored in the model's GIS export; they were reproduced exactly from the run's random seed (see purposes.py).

| Home area | n | Mean per person [95% CI] | Median per person | 90th pct. per person | Mean per person, walked | Mean per person, transit |
|:---|---:|---:|---:|---:|---:|---:|
| *Relative Wealth Index quintile* | | | | | | |
| Q1 (poorest) | 4,005 | 305 [294–316] | 208 | 657 | 275 | 325 |
| Q2 | 4,369 | 263 [255–271] | 193 | 568 | 252 | 272 |
| Q3 | 3,639 | 282 [273–292] | 215 | 579 | 311 | 263 |
| Q4 | 4,000 | 250 [241–258] | 176 | 529 | 283 | 226 |
| Q5 (richest) | 3,978 | 245 [238–253] | 187 | 509 | 264 | 232 |
| *Morphological informality* | | | | | | |
| Low | 8,184 | 277 [271–284] | 207 | 579 | 306 | 259 |
| Medium | 9,764 | 256 [251–261] | 190 | 541 | 273 | 244 |
| High | 1,539 | 196 [184–208] | 124 | 431 | 180 | 221 |

Table: **Table 5.** Daily heat exposure per person (°C·min above 26 °C UTCI) by the wealth and informality of the home location.

Note. Relative Wealth Index (Chi et al. 2022; Data for Good at Meta, ~2.4 km tiles): quintiles over all agents. Morphological informality (IDEAMAPS; Hafner et al. 2026): class of the home's 100 m grid cell, from the form of buildings and roads (low: large, detached, regularly arranged buildings; high: small, close-together, irregularly arranged buildings with roads hard to see or absent). The layer covers Nairobi's built-up core; 513 agents outside the informality layer are excluded from the informality rows (and from Figure 4b).

| Street | Road class | Length (m) | People | Person-min | Total °C·min | °C·min per person |
|:---|---:|---:|---:|---:|---:|---:|
| Kangundo Road | trunk | 442 | 198 | 1,204 | 7,808 | 39.4 |
| Outer Ring Road | secondary | 596 | 131 | 1,088 | 6,651 | 50.8 |
| Mama Ng'endo Road | unclassified | 209 | 485 | 1,415 | 6,380 | 13.2 |
| Outer Ring Road | primary | 158 | 410 | 893 | 6,204 | 15.1 |
| Macharia Road | unclassified | 272 | 343 | 1,299 | 5,923 | 17.3 |
| (unnamed) | unclassified | 240 | 320 | 1,080 | 5,911 | 18.5 |
| (unnamed) | residential | 798 | 94 | 1,084 | 5,502 | 58.5 |
| Juja Road | secondary | 458 | 206 | 1,295 | 5,146 | 25.0 |
| Nderi road | unclassified | 166 | 389 | 915 | 4,894 | 12.6 |
| Quarry road | unclassified | 167 | 454 | 1,071 | 4,751 | 10.5 |

Table: **Table 6.** The ten street segments with the most total exposure.

Note. A segment is the stretch of street between two network nodes, both directions combined. People: distinct agents who walked it. Person-min: total minutes spent walking it.

| Stop | People waiting | Person-min waiting | Total °C·min | °C·min per person |
|:---|---:|---:|---:|---:|
| Olympic Primary School | 174 | 1,175 | 10,799 | 62.1 |
| Kangemi Terminus | 160 | 937 | 9,800 | 61.3 |
| Maziwa | 183 | 993 | 8,389 | 45.8 |
| Kenafric | 176 | 1,068 | 7,703 | 43.8 |
| Kwa DC | 163 | 988 | 6,578 | 40.4 |
| Mother Teresa Road | 119 | 716 | 6,543 | 55.0 |
| Tumaini/Tassia | 127 | 790 | 5,432 | 42.8 |
| Huruma Baptist | 108 | 606 | 5,294 | 49.0 |
| Mbagathi Highway | 171 | 860 | 4,836 | 28.3 |
| Mathare North Terminal | 155 | 866 | 4,682 | 30.2 |

Table: **Table 7.** The ten transit stops with the most exposure while waiting to board.

Note. Waiting at stops accounts for 11.9% of all exposure; walking accounts for the rest.

| Ward | Agents | Mean per resident | Median per resident | Mean RWI | Medium/high informality (%) |
|:---|---:|---:|---:|---:|---:|
| *Highest mean exposure* | | | | | |
| Oloosirkon/Sholinke | 23 | 1172 | 1008 | -0.05 | 0 |
| Kinanie | 16 | 921 | 770 | 0.03 | – |
| Muthwani | 93 | 916 | 736 | 0.44 | 9 |
| Ruai | 193 | 602 | 372 | 0.76 | 41 |
| Imara Daima | 54 | 595 | 394 | 0.65 | 39 |
| *Lowest mean exposure* | | | | | |
| Huruma | 171 | 123 | 82 | 0.93 | 78 |
| Mlango Kubwa | 109 | 120 | 71 | 1.34 | 72 |
| Sarangombe | 121 | 118 | 59 | 1.33 | 83 |
| Ngei | 178 | 105 | 44 | 0.83 | 63 |
| Mabatini | 85 | 103 | 70 | 0.82 | 81 |

Table: **Table 8.** Wards with the highest and lowest mean daily exposure per resident (°C·min above 26 °C UTCI).

Note. Wards with at least 15 simulated residents (118 of 128 wards in the study area). Mean RWI: mean Relative Wealth Index at residents' homes. Medium/high informality: share of residents whose home cell is classed medium or high.

# Behavioural sensitivity

## Method

Which behavioural assumptions drive the results? 17 behavioural factors (Table 9) were screened with the Morris method of elementary effects. Each of 10 trajectories starts at a random point on a 4-level grid over the factor ranges and changes one factor at a time by two-thirds of its range; μ\* is the mean absolute change in an outcome per such step. Each run simulates 3,000 agents making a round trip, with the model otherwise as in the main results: 180 Morris runs plus 5 baseline replicates.

## Results

At the baseline, mean exposure is 269 °C·min per person (seed-to-seed SD 3), with 57 minutes outdoors; 76% of exposure is picked up on the trip home. Across all runs, mean exposure ranged from 143 to 454 °C·min. 16 of the 17 factors have μ\* more than twice the seed SD. The most influential are walking-time weight (route choice) (77), walk-share shift (76), destination distance decay (76), mean walking speed (56) and work end time (41 °C·min; Figure 5, Table 11).

Factors act through one of two channels (Figure 6). Route and mode behaviour (destination distance decay, walk share, walking speed, boarding wait, walking-time weight) changes how long people are outdoors. Timing behaviour (morning departure peak, purpose-specific departure timing, work and school end times) barely changes minutes outdoors but shifts when in the day they fall, and so the UTCI experienced. Work end time (μ\* 41) acts almost entirely through temperature: a later end moves the trip home out of the afternoon heat. School end time acts the same way (μ\* 22); it matters because every child makes a school round trip and comes home in the mid-afternoon.

The top three factors are effectively tied: their μ\* values lie within 1 °C·min of each other and their bootstrap intervals overlap widely. The walking-time weight has the largest σ, so its effect depends most on the other factors. Wait tolerance has no measurable effect (μ\* 0.6, below the seed SD of 3). An agent who gives up waiting walks only when walking is faster than waiting and riding, so giving up seldom changes the trip.

The equity gaps (Figure 7) are most sensitive to walk share, destination distance decay and walking speed, that is, to how much people walk and how far they travel. They are noisy at the baseline (Table 10), so their rankings are less certain than those for the city-wide outcomes.

## Figures

![**Figure 5.** Behavioural factors ranked by their influence on mean daily exposure per person (Morris μ\*: the mean absolute change in the outcome when the factor moves two-thirds of its range, over 10 trajectories). Lines: 95% bootstrap intervals across trajectories. Arrows: ↑ raising the factor raises exposure, ↓ lowers it, ↕ mixed (|μ| < 0.8 μ\*). Dashed line: seed-to-seed SD of the outcome at the baseline (3 °C·min, 5 replicates). 3,000 agents per run.](../paper_nb02/fig5_morris_mean_exposure.svg){width=4.6in}

![**Figure 6.** Morris μ\* for the two parts of exposure: (a) minutes outdoors per person and (b) the mean UTCI experienced while outdoors (raw UTCI, no threshold). Factors in the order of Figure 5; arrows as in Figure 5, for that outcome. Dashed lines: seed-to-seed SD at the baseline.](../paper_nb02/fig6_duration_vs_temperature.svg){width=6.5in}

![**Figure 7.** Morris μ\* of each factor for each outcome, relative to the most influential factor for that outcome (1.00). The two right-hand columns are equity gaps: mean exposure of the poorest minus the richest Relative Wealth Index quintile, and of medium/high minus low informality. These are differences of group means and much noisier than the city-wide outcomes (Table 10). Share home by 20:00: share of travellers back home by the end of the simulated day.](../paper_nb02/fig7_outcome_heatmap.svg){width=6.5in}

## Tables

| Factor | Range | Baseline | Source of baseline / range |
|:---|---:|---:|---:|
| *Destination and route choice* | | | |
| Destination distance decay (exponent) | 1.1–1.9 | 1.5 | WRI rider survey Q11 median ride time (calibration.py) |
| Walking-time weight in route choice (x riding) | 2–6× | 5× | WRI rider survey Q8 access times (calibration.py); literature 1.5-2.5 |
| Walk share vs. JICA distance curves (+- pct points) | -15–15 pp | 0 pp | JICA 2014 Nairobi walk-split curves (2013 person-trip survey) |
| *Walking* | | | |
| Walking speed, mean (m/s) | 1–1.4 m/s | 1.2 m/s | literature default |
| Walking speed, SD between people (m/s) | 0.05–0.3 m/s | 0.15 m/s | assumption |
| *Waiting for transit* | | | |
| Mean boarding wait (min) | 4.5–7 min | 5.65 min | WRI rider survey Q15; bus 5.1, matatu 6.7, 06-09 4.8, 15-21 6.4 |
| Wait tolerance before walking instead (min) | 5–30 min | 15 min | assumption |
| *Outbound departure time* | | | |
| Morning outbound departure peak (hour) | 6.5–8.5 h | 7.4 h | assumption; refit for round trips (departure_fit.py) |
| Share of outbound trips in morning peak | 0.5–0.8 | 0.66 | assumption; refit for round trips (departure_fit.py) |
| Evening outbound departure peak (hour) | 15.75–18 h | 16.75 h | assumption; refit for round trips (departure_fit.py) |
| Share of outbound trips in evening peak | 0–0.3 | 0.14 | assumption; refit for round trips (departure_fit.py) |
| Purpose-specific departure timing (x survey tilt) | 0–1.5× | 1× | WRI rider survey Q9 (tilt = 1) |
| *Trip purpose and the trip home* | | | |
| Work share of trip purposes | 0.25–0.55 | 0.4 | assumption |
| Work end time, mean (hour) | 16–18.5 h | 17 h | assumption; Kenya public-service hours 08:00-17:00 |
| School end time, mean (hour) | 15–16.5 h | 15.5 h | assumption; Nairobi school day 08:00-15:30 |
| Shopping/market dwell time, median (min) | 20–120 min | 45 min | assumption |
| Other-purpose dwell time, median (min) | 20–180 min | 60 min | assumption (places of worship, community centres, libraries) |

Table: **Table 9.** Behavioural factors varied in the sensitivity analysis.

Note. Geography (street network, heat rasters, population, amenities) and the transit service (GTFS routes and frequencies) are held fixed. Ranges for survey-calibrated factors span the WRI rider survey's own sub-group fits; the others are assumptions around the model default. Not varied: trip rate (one round trip per agent), travel probability (scales who travels, not the exposure of those who do), minimum stay and dwell-time spread (their medians are varied instead), and demographic modifiers (neutral by default).

| Outcome | Mean | SD | CV |
|:---|---:|---:|---:|
| Mean exposure (°C·min) | 269 | 3 | 1.1% |
| Median exposure (°C·min) | 191 | 2 | 1.1% |
| 90th-percentile exposure (°C·min) | 572 | 14 | 2.4% |
| Minutes outdoors | 57.1 | 0.6 | 1.0% |
| Mean UTCI while outdoors (°C) | 28.99 | 0.05 | 0.2% |
| Share of trips using transit | 0.586 | 0.011 | 1.8% |
| Mean exposure, walk-only trips (°C·min) | 279 | 6 | 2.0% |
| Mean exposure, transit trips (°C·min) | 262 | 3 | 1.1% |
| Share of exposure on the trip home | 0.759 | 0.012 | 1.6% |
| Share home by 20:00 | 0.924 | 0.006 | 0.6% |
| Wealth gap, poorest − richest RWI quintile (°C·min) | 55 | 18 | 33.1% |
| Informality gap, medium/high − low (°C·min) | -23 | 11 | 49.3% |

Table: **Table 10.** Outcomes at the baseline parameters over 5 replicate runs with different random seeds.

Note. 3,000 agents per run. The SD is the sampling noise of a single run and the noise floor for the Morris indices. Elementary effects themselves are less noisy than this, because each step of a trajectory reuses the previous run's seed (common random numbers).

| Rank | Factor | Dir. | μ* (95% CI) | μ | σ | μ* minutes outdoors | μ* UTCI (°C) |
|:---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Walking-time weight in route choice (x riding) | ↓ | 77 (45–113) | -77 | 61 | 16.7 | 0.05 |
| 2 | Walk share vs. JICA distance curves (+- pct points) | ↑ | 76 (66–89) | 76 | 20 | 16.4 | 0.20 |
| 3 | Destination distance decay (exponent) | ↓ | 76 (56–98) | -76 | 36 | 16.7 | 0.11 |
| 4 | Walking speed, mean (m/s) | ↓ | 56 (43–70) | -56 | 24 | 12.9 | 0.08 |
| 5 | Work end time, mean (hour) | ↓ | 41 (30–52) | -41 | 18 | 1.6 | 0.59 |
| 6 | Mean boarding wait (min) | ↑ | 40 (23–59) | 40 | 31 | 8.6 | 0.05 |
| 7 | Evening outbound departure peak (hour) | ↓ | 30 (13–51) | -30 | 33 | 2.0 | 0.41 |
| 8 | Share of outbound trips in evening peak | ↓ | 29 (17–41) | -24 | 28 | 2.8 | 0.27 |
| 9 | Work share of trip purposes | ↕ | 25 (19–33) | -20 | 20 | 1.6 | 0.42 |
| 10 | Morning outbound departure peak (hour) | ↑ | 23 (18–27) | 23 | 8 | 0.1 | 0.85 |
| 11 | School end time, mean (hour) | ↓ | 22 (17–26) | -22 | 8 | 0.1 | 0.37 |
| 12 | Purpose-specific departure timing (x survey tilt) | ↑ | 21 (14–28) | 20 | 14 | 2.2 | 0.75 |
| 13 | Share of outbound trips in morning peak | ↓ | 20 (17–24) | -20 | 6 | 1.9 | 0.75 |
| 14 | Walking speed, SD between people (m/s) | ↑ | 15 (9–21) | 15 | 11 | 3.1 | 0.03 |
| 15 | Other-purpose dwell time, median (min) | ↕ | 7 (5–9) | 4 | 7 | 1.0 | 0.17 |
| 16 | Shopping/market dwell time, median (min) | ↕ | 7 (5–9) | 4 | 6 | 1.0 | 0.17 |
| 17 | Wait tolerance before walking instead (min) | ↑ | 1 (0–1) | 1 | 0 | 0.1 | 0.00 |

Table: **Table 11.** Morris sensitivity indices for mean daily exposure per person (°C·min above 26 °C UTCI) and for its two parts.

Note. μ\*: mean absolute elementary effect, with 95% bootstrap interval across trajectories; μ: signed mean; σ: standard deviation of the elementary effects (non-linearity or interaction with other factors). Dir.: ↑ / ↓ when |μ| ≥ 0.8 μ\*, otherwise ↕. Last two columns: μ\* for mean minutes outdoors and mean UTCI while outdoors. Indices for all twelve outcomes are in paper_nb02/table9_mu_star_all_outcomes.csv.
