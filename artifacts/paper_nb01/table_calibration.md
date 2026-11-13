**Table X.** Parameters estimated from the WRI Nairobi rider survey.

| Parameter | Value | Data | Method | Fit |
|---|---|---|---|---|
| Mean boarding wait | 5.65 min | Q15, bus + matatu riders, N = 1,484 | Maximum-likelihood exponential | By period: 4.8 min (06–09), 5.4 (09–15), 6.4 (15–21) |
| Destination distance decay β | 1.5 | Q11 time on board, N = 1,482 | Median matching on a β × weight grid (2 seeds × 3,000 agents per cell) | Median 22.7 min, as surveyed |
| Walking-time weight in route choice | 5 | Q8 access walk, N = 1,227 | Where the Q8 fit stops improving | Median access walk 8.6 min vs. 7.6 surveyed |
| Purpose tilt by hour | per band (Table X+1) | Q9 purpose, local time from timestamps | P(purpose \| hour) / P(purpose) | Used as given |

**Table X+1.** Purpose tilt: multiplier on the departure profile, by purpose and time band (local time).

| Purpose | 06–09 | 09–11 | 11–13 | 13–15 | 15–17 | 17–20 |
|---|---|---|---|---|---|---|
| Work | 1.49 | 1.22 | 0.96 | 0.83 | 0.88 | 0.83 |
| School | 0.85 | 1.00 | 1.10 | 1.07 | 0.97 | 0.75 |
| Market | 0.40 | 0.69 | 0.94 | 1.22 | 1.19 | 1.50 |
| Other | 0.23 | 0.62 | 1.09 | 1.26 | 1.22 | 1.27 |

1.0 = as often as the overall departure profile predicts. Adult transit riders only; children's school trips follow a separate rule (depart before 08:00).
