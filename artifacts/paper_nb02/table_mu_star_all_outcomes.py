"""
Word table of Morris mu* for every factor and every outcome of the sensitivity batch, split into
(a) exposure outcomes and equity gaps and (b) the outcomes that show how factors act.
Reads morris_indices.csv and table8_baseline_replicates.csv (seed-to-seed SD, the noise floor)
and writes table_mu_star_all_outcomes.{md,docx} via pandoc.

Run from the repo root:  python artifacts/paper_nb02/table_mu_star_all_outcomes.py
"""
import ast
import subprocess
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
src = (HERE / "make_figures.py").read_text(encoding="utf-8")
start = src.index("SHORT = {")
SHORT = ast.literal_eval(src[start + len("SHORT = "): src.index("}", start) + 1])

idx = pd.read_csv(HERE / "morris_indices.csv")
noise = pd.read_csv(HERE / "table8_baseline_replicates.csv").set_index("outcome")["std"]
mu = idx.pivot(index="factor", columns="outcome", values="mu_star")
order = idx[idx.outcome == "mean_exposure"].sort_values("mu_star", ascending=False)["factor"].tolist()

# (key, column header, scale, decimals); shares shown in percentage points
A = [("mean_exposure", "Mean", 1, 0), ("median_exposure", "Median", 1, 0), ("p90_exposure", "90th pct.", 1, 0),
     ("walk_trip_mean_exposure", "Mean, walked out", 1, 0), ("transit_trip_mean_exposure", "Mean, rode transit", 1, 0),
     ("rwi_gap", "Wealth gap (Q1 − Q5)", 1, 0), ("informality_gap", "Informality gap (med./high − low)", 1, 0)]
B = [("mean_outdoor_min", "Minutes outdoors (min)", 1, 1), ("mean_temp_experienced", "UTCI while outdoors (°C)", 1, 2),
     ("transit_trip_share", "Transit trip share (pp)", 100, 1),
     ("return_exposure_share", "Share of exposure on trip home (pp)", 100, 1),
     ("returned_share", "Share home by 20:00 (pp)", 100, 1)]


def table(cols) -> str:
    head = "| Rank | Factor | " + " | ".join(h for _, h, _, _ in cols) + " |"
    sep = "|---:|:---|" + "---:|" * len(cols)
    rows = [f"| {i} | {SHORT[f]} | " + " | ".join(f"{mu.loc[f, k] * s:,.{d}f}" for k, _, s, d in cols) + " |"
            for i, f in enumerate(order, start=1)]
    rows.append("| | *Seed-to-seed SD at baseline* | " +
                " | ".join(f"*{noise[k] * s:,.{d}f}*" for k, _, s, d in cols) + " |")
    return "\n".join([head, sep, *rows])


md = f"""**Table X.** Morris μ\\* of each behavioural factor for every outcome of the sensitivity analysis: the mean absolute change in the outcome when the factor moves two-thirds of its range, over 10 trajectories (3,000 agents per run). Factors ranked by μ\\* for mean exposure (as in Figure 5). Last row: seed-to-seed SD of the outcome at the baseline parameters (5 replicate runs), the noise floor; a μ\\* below about twice this value cannot be told apart from noise. Bootstrap intervals for mean exposure are in Table 11.

*(a) Exposure (°C·min per person per day above 26 °C UTCI) and equity gaps.* Mean, walked out / rode transit: mean exposure of agents whose outbound trip was walked / rode transit. Wealth gap: mean exposure of the poorest minus the richest Relative Wealth Index quintile. Informality gap: mean exposure of agents with medium/high minus low informality at home.

{table(A)}

*(b) How factors act.* Minutes outdoors per person; mean UTCI experienced while outdoors (raw UTCI, no threshold); share of outbound trips that ride transit; share of exposure picked up on the trip home; share of travellers back home by the end of the simulated day. Shares in percentage points.

{table(B)}
"""
(HERE / "table_mu_star_all_outcomes.md").write_text(md, encoding="utf-8")
subprocess.run(["pandoc", "table_mu_star_all_outcomes.md", "-o", "table_mu_star_all_outcomes.docx"], cwd=HERE, check=True)
print(md)
