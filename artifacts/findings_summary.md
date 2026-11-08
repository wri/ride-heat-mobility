# Heat exposure of travellers in Nairobi: summary of findings

Agent-based model of pedestrian heat exposure, notebooks 01 (main results) and 02 (behavioural sensitivity).
Figures and tables: `paper_nb01/` and `paper_nb02/`; assembled in `paper_nb01/heat_exposure_main_results.docx`.
Updated 2026-11-08: children (0–14) now make only school trips; main results rerun with 20,000 agents. Main
and sensitivity results below are both from runs with this rule.

## Model in brief

- One simulated weekday, 06:00–20:00, 60-second steps. Agents live at locations drawn from WorldPop population
  density. Each makes one round trip: home → destination (work, school, market or other) → stay → home.
- Each trip is walked the whole way or ridden by matatu/bus. Walk shares follow JICA 2014 Nairobi distance curves;
  destination choice (distance decay exponent 1.5) and route choice (walking time weighted 5× riding time) are
  calibrated to the WRI Nairobi rider survey (2023). The resulting 43% walk share matches Tatah et al. (2023).
- Age group and sex are drawn from WorldPop at each home. Age sets two rules, both for children (0–14): they make
  only school trips, and they leave for school before 08:00. Sex sets none. Everyone over 14 shares the same
  purpose mix (work 40%, school 20%, market 25%, other 15%), and mode choice, walking speed and waiting are the
  same for all ages and both sexes. Overall, 41% of agents make school trips. Full parameter table: Table 1 of the
  Word document.
- **Exposure** = sum over every outdoor minute (walking or waiting at a stop) of the degrees by which UTCI at the
  agent's position exceeds 26 °C (the lower bound of "moderate heat stress"), in °C·min. Riding inside a vehicle
  adds nothing. UTCI: 10 m hourly rasters for 14 March 2025.

## Main results (notebook 01: 20,000 agents, seed 42)

**Overall**
- Mean daily exposure is **309 °C·min per person** (95% CI 304–314); median 199; 90th percentile 693.
- 3.6% of agents have zero exposure (all their outdoor minutes were at UTCI ≤ 26 °C).
- Walking accounts for 92% of all exposure; waiting at transit stops for 8%.
- Most exposure is picked up on the trip home, which falls in the afternoon heat (73% in the 3,000-agent
  baseline replicates of the sensitivity batch).

**By mode of the outbound trip**
- People who walked out have higher mean exposure (323) than transit riders (297), and a much longer tail
  (90th percentile 869 vs 561). Their median is lower (153 vs 224): many walks are short, but long walks are
  very exposed.

**By trip purpose**
- School trips are the most exposed (mean 365; nobody at zero), then other purposes (309), market (268) and work
  (254).
- Market trips show the largest gap by mode: walkers 325 vs transit riders 224.

**By person**
- **Children are the most exposed group**: mean 361 (95% CI 351–372), median 244, and none at zero, against 287
  for adults (20–59) and 295 for youth (15–19). Every child makes a school trip, the most exposed purpose, and
  heads home around 15:30. The elderly are also high (325), but the group is small (n = 422) and the interval
  wide (288–365).
- Sex makes little difference: women 315, men 304.

**By wealth and informality of the home**
- Poorer areas are more exposed: mean 351 in the poorest Relative Wealth Index quintile vs 282 in the richest
  (24% higher), though small next to individual variation (0.18 SD; rank correlation −0.06). The poorest
  quintile has more very high days (16% vs 10% above 600 °C·min).
- Informality runs the other way: low-informality homes 319, medium 294, high **215**. High-informality
  settlements are dense and central, so trips are short; the most exposed people live on the periphery.

**Where**
- Ward means range from ~100 to 1,200 °C·min per resident. The highest are peripheral (Oloosirkon/Sholinke 1,204
  and Kinanie 1,096, both with fewer than 25 simulated residents; Muthwani 1,016, Ruai 755, Mwihoko 690); the
  lowest are dense inner wards (Mabatini 103, Ngei 110, Sarangombe 122, Mlango Kubwa 128).
- The most-exposing street segments are on major roads used by many walkers: Outer Ring Road, Juja Road, Koma
  Rock Road, Kangundo Road, Mombasa Road, Jogoo Road. Per walker, trunk roads are the worst (Thika Road 89,
  Mombasa Road 70 °C·min per segment among the top ten).
- The stops with the most waiting exposure include Olympic Primary School, Kangemi Terminus, Maziwa and Kenafric.

## Behavioural sensitivity (notebook 02: Morris elementary effects)

**Design**
- 17 behavioural factors varied over plausible ranges. Geography (network, heat, population, amenities) and the
  transit service are held fixed.
- 10 Morris trajectories (180 runs) + 5 baseline replicates, 3,000 agents per run. Children make only school
  trips, as in the main results (batch: outputs/sensitivity_children_school/).
- Baseline: mean 311 °C·min; seed-to-seed SD 6; 65 min outdoors; 73% of exposure on the trip home; 91% of
  travellers home by 20:00.

**What drives mean exposure** (μ\* = average change in mean exposure when a factor moves two-thirds of its range)

| Rank | Factor | μ\* (°C·min) | Direction |
|---|---|---|---|
| 1 | Wait tolerance before walking instead | 163 | higher tolerance → less exposure |
| 2 | Destination distance decay | 133 | stronger decay (closer destinations) → less |
| 3 | Walk-share shift (±15 pp) | 103 | more walking → more |
| 4 | Mean walking speed | 87 | faster → less |
| 5 | Mean boarding wait | 71 | longer → more |
| 6 | Walking-time weight in route choice | 58 | higher → less |
| 7 | Work end time | 54 | later → less |

- 15 of 17 factors have μ\* more than twice the seed SD; only market and other-purpose dwell times (μ\* 6–7) do
  not.
- Mean exposure ranged from 161 to 860 °C·min across all runs.
- Compared with the batch before children were limited to school trips: the top four are unchanged; work end
  time drops from 5th (μ\* 74) to 7th (54), because fewer agents make work trips; school end time rises from
  15th (11) to 12th (29), because every child now comes home from school.

**Two channels**
- Route and mode behaviour (wait tolerance, distance decay, walk share, walking speed, boarding wait,
  walking-time weight) changes **how long** people are outdoors.
- Timing behaviour (morning departure peak hour and share, purpose-specific departure timing, work and school
  end times) barely changes time outdoors but changes **when**, and so the UTCI experienced. Work and school end
  times act almost entirely through this channel: a later finish moves the trip home out of the afternoon heat.

**The wait-tolerance threshold**
- The wait-tolerance effect is a threshold, not a gradient. At 5 min tolerance (just under the 5.65 min mean
  wait), runs average 561 °C·min and 119 min outdoors, because most would-be riders walk. From 13 to 30 min the
  result is nearly flat (282–312 °C·min). The 5–30 min range was kept deliberately; this threshold is the finding
  to report.

**Equity gaps**
- The wealth gap (poorest − richest quintile) and informality gap respond most to wait tolerance, walk share and
  destination distance decay, i.e. to whether people ride and how far they travel. Both gaps are noisy even at
  the baseline (SD 34 and 14 °C·min), so their rankings are less certain than those for city-wide outcomes.

## Limitations

- One weekday of heat (14 March 2025); UTCI rasters cover 08:00–18:00 hourly.
- One round trip per agent: no trip chains or second trips.
- Behaviour varies by age only for children (school only, before 08:00) and not at all by sex: the calibration
  data (WRI rider survey of adult transit riders; JICA curves by purpose) give no age or sex breakdowns. Walking
  speed is the same at every age.
- The outbound departure-time profile is an assumption (no Nairobi hourly person-trip data in our sources),
  refit for round trips; the purpose-specific departure tilt was not refit for round trips.
- Walking speed does not respond to heat; transfer waits between transit routes are not modelled.
- The route-choice walking-time weight (5) is high relative to the literature (1.5–2.5); it likely stands in for
  hail-anywhere matatu boarding.
- Morris is a screening method: it ranks factors but does not decompose variance. A Sobol analysis on the top
  three or four factors would quantify their shares and interactions.
