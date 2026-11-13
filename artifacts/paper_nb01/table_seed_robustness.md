**Table X.** Seed-to-seed variation of the main results. The main run (20,000 agents) repeated with four seeds (42–45); each seed draws new homes, destinations and behaviour. Exposure in °C·min per person per day above 26 °C UTCI. SD and range across the four seeds.

| Outcome | Main run (seed 42) | Mean ± SD across seeds | Range across seeds | Reading |
|:---|---:|---:|---:|:---|
| *Averages* | | | | |
| Mean exposure | 269 | 267 ± 2 | 265–270 | Stable |
| Median exposure | 194 | 195 ± 2 | 193–197 | Stable |
| 90th percentile | 570 | 565 ± 3 | 562–570 | Stable |
| Walked out (%) | 41.8 | 41.5 ± 0.2 | 41.2–41.8 | Stable |
| Waiting at stops (% of exposure) | 11.9 | 12.0 ± 0.1 | 11.9–12.1 | Stable |
| Children (0–14) | 312 | 311 ± 4 | 308–316 | Stable |
| *Group contrasts* | | | | |
| Informality gap (high − low) | −81 | −82 ± 2 | −84 to −79 | Stable |
| Wealth gap (poorest − richest RWI quintile) | 59 | 60 ± 15 | 39–72 | Unstable, though always positive; report as a range (about 40–70) |
| *Small groups* | | | | |
| Elderly (60+; about 420 agents per run) | 284 | 265 ± 15 | 248–284 | Noisy |
| Youth (15–19) | 252 | 249 ± 9 | 237–258 | Noisy |

The wealth gap varies about twice as much across seeds as the main run's bootstrap intervals imply (Q1 305 [294–316] vs. Q5 245 [238–253]). RWI comes in 2.4 km tiles, so agents in a quintile share places and routes and are not independent draws; agent-level bootstrap intervals understate the uncertainty. Source: `artifacts/paper_nb01/seed_replicates.py`.

**Table X+1.** Stability of place rankings across the four seeds.

| Places | Agreement between seeds | Reading |
|:---|:---|:---|
| Ward means | Spearman 0.82–0.90 between seeds | Broadly stable |
| Top 10 wards | 7–8 of 10 recur | Mostly stable |
| Top 10 matatu stands (Table 4) | 8–9 of 10 recur | Mostly stable |
| Top 10 street segments (Table 3) | 5–8 of 10 recur | Indicative only |

Tables 3–4 and the ward table (Table 6) should be read as indicative.
