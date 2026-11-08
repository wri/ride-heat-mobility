"""
Assemble the figures (SVG) and tables made by make_figures.py into a Word document,
heat_exposure_main_results.docx, next to this script.

Pandoc writes the document and embeds each SVG, but without the PNG fallback that Word
versions before 2016, Google Docs and some viewers need. This script then adds the PNG
render of each figure as that fallback (the standard Office structure: <a:blip> points at
the PNG, its svgBlip extension at the SVG).

Tables 1-2 (model parameters) come from behaviour_tables.json, written by behaviour_tables.py.

Run from the repo root, after make_figures.py, behaviour_tables.py:
    .venv/Scripts/python.exe artifacts/paper_nb01/build_doc.py
"""
from __future__ import annotations

import json
import re
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "heat_exposure_main_results.docx"
T = json.loads((HERE / "tables.json").read_text(encoding="utf-8"))
N = T["numbers"]

FIGS = [  # (file stem, width, caption)
    ("fig1_exposure_distribution", "3.5in",
     "**Figure 1.** Distribution of daily heat exposure per person, by the mode of the outbound trip. "
     "Exposure is the sum over outdoor minutes (walking and waiting at stops) of the degrees by which UTCI exceeds "
     "26 °C, over the outbound trip and the trip home. Dashed lines: medians. Bins of 25 °C·min; the last bin "
     "includes all values ≥ 1,475 °C·min. n = 10,000 agents."),
    ("fig2_segment_maps", "6.5in",
     "**Figure 2.** Where exposure is picked up on the street network. (a) Total exposure accumulated on each "
     f"street segment by everyone who walked it ({N['n_segments']:,} segments with non-zero exposure). "
     "(b) Exposure of one person walking the segment (total divided by the number of distinct people), shown for "
     "segments walked by at least 5 people. Both directions of a street are combined. Light grey: segments walked "
     "but with no exposure above the threshold, and ward boundaries. Log colour scales. Place labels mark selected wards (CBD: Nairobi Central ward; Kibera: Laini Saba and Sarangombe wards; Dandora and Eastleigh: their wards combined)."),
    ("fig3_ward_map", "3.5in",
     "**Figure 3.** Mean daily exposure per resident, by home ward. Wards with fewer than 15 simulated residents "
     "are hatched. The map is clipped to the study area. Place labels mark selected wards (CBD: Nairobi Central ward; Kibera: Laini Saba and Sarangombe wards; Dandora and Eastleigh: their wards combined)."),
    ("fig4_wealth_informality", "6.5in",
     "**Figure 4.** Mean daily exposure per person by (a) the Relative Wealth Index quintile and (b) the morphological "
     "informality of the agent's home location, for all agents and by outbound mode. Bars: 95% bootstrap "
     "confidence intervals (2,000 resamples)."),
]

TABLES = [
    ("table1", "**Table 3.** Daily heat exposure per person (°C·min above 26 °C UTCI), overall and by group.",
     "Note. Outbound mode is the mode of the trip from home; the trip home can differ (in a 3,000-agent check, "
     "92% of agents used the same mode both ways). Age group and gender are drawn from WorldPop population grids at "
     "the home location. 95% confidence intervals of the mean are bootstrap percentile intervals."),
    ("table_purpose", "**Table 4.** Daily heat exposure per person (°C·min above 26 °C UTCI) by destination type (trip purpose).",
     "Note. Destination types: Work: offices, shops, commercial and industrial buildings and banks, plus schools, "
     "markets and health facilities as workplaces; School: schools, colleges and universities; Market: supermarkets "
     "and marketplaces; Other: places of worship, community centres and libraries (OpenStreetMap). "
     "Each agent makes one round trip, to one destination of its trip purpose and back; destinations are chosen with "
     "weight distance^−1.5^. Walked out: share whose outbound trip was walked the whole way. Mean, walked / transit: "
     "mean exposure by outbound mode. Purposes are not stored in the model's GIS export; they were reproduced "
     "exactly from the run's random seed (see purposes.py)."),
    ("table2", "**Table 5.** Daily heat exposure per person (°C·min above 26 °C UTCI) by the wealth and informality of the home location.",
     "Note. Relative Wealth Index (Chi et al. 2022; Data for Good at Meta, ~2.4 km tiles): quintiles over all agents. "
     "Morphological informality (IDEAMAPS; Hafner et al. 2026): class of the home's 100 m grid cell, from the form "
     "of buildings and roads (low: large, detached, regularly arranged buildings; high: small, close-together, "
     "irregularly arranged buildings with roads hard to see or absent). The layer covers Nairobi's built-up core; 261 agents outside the informality layer are "
     "excluded from the informality rows (and from Figure 4b)."),
    ("table3", "**Table 6.** The ten street segments with the most total exposure.",
     "Note. A segment is the stretch of street between two network nodes, both directions combined. "
     "People: distinct agents who walked it. Person-min: total minutes spent walking it."),
    ("table4", "**Table 7.** The ten transit stops with the most exposure while waiting to board.",
     f"Note. Waiting at stops accounts for {N['stop_share_pct']:.1f}% of all exposure; walking accounts for the rest."),
    ("table5", "**Table 8.** Wards with the highest and lowest mean daily exposure per resident (°C·min above 26 °C UTCI).",
     f"Note. Wards with at least 15 simulated residents ({T['table5']['n_wards']} of {T['table5']['n_wards_all']} "
     "wards in the study area). Mean RWI: mean Relative Wealth Index at residents' homes. "
     "Medium/high informality: share of residents whose home cell is classed medium or high."),
]


B = json.loads((HERE / "behaviour_tables.json").read_text(encoding="utf-8"))  # from behaviour_tables.py
BTABLES = [
    ("table_behaviour", "**Table 1.** Agent behaviour as modelled in the main run.",
     "Note. Differs by: the agent attributes a rule depends on; — = the same for every agent. Age changes only "
     "children's trips (school only, leaving before 08:00); sex changes nothing. Where a rule depends on purpose, it "
     "applies equally to every age and sex (for example, adult students and children both head home from school at 15:30). Calibrated: "
     "destination distance decay and the walking-time weight were fitted jointly to the WRI Nairobi rider survey "
     "(2023), and with the JICA curves they give a 43% walk share, as reported by Tatah et al. (2023). WRI rider "
     "survey: adults 18 and over, bus and matatu riders, weekdays."),
    ("table_population", "**Table 2.** Simulated population by age group and sex, and its trip purposes "
     "(% of each group).",
     "Note. Age group and sex come from the WorldPop rasters at each agent's home; youth (15–19) is the "
     "residual of total minus children and adults 20+. Children make only school trips; agents over 14 share "
     "the population purpose weights, so their school trips stand for secondary-school, college and university "
     f"students. Overall, {B['numbers']['all_school_pct']:.0f}% of agents make school trips. Purposes are not stored in the model's GIS export; they were reproduced exactly from the "
     "run's random seed (see purposes.py)."),
]


def md_table(t: dict) -> str:
    header = t["header"]
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join([":---"] + ["---:"] * (len(header) - 1)) + "|"]
    sections = {int(k): v for k, v in t.get("section_rows", {}).items()}
    for i, row in enumerate(t["rows"]):
        if i in sections:
            lines.append("| *" + sections[i] + "* |" + " |" * (len(header) - 1))
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


md = [
    "---",
    'title: "Heat exposure of travellers in Nairobi: main results"',
    'subtitle: "Figures and tables from the agent-based model (notebook 01; behavioural sensitivity: notebook 02)"'
    if (HERE.parent / "paper_nb02" / "tables.json").exists()
    else 'subtitle: "Figures and tables from the agent-based model (notebook 01)"',
    "---",
    "",
    "## Model run",
    "",
    "10,000 agents on one simulated weekday, 06:00–20:00, in 60-second steps (random seed 42). Each agent lives at a "
    "location drawn from WorldPop population density and makes a round trip: out from home to a destination chosen "
    "by trip purpose (work, school, market, other), a stay at the destination, and back. Each trip is walked the "
    "whole way or ridden by matatu or bus, by distance-based walk shares (JICA 2014) and a route choice calibrated "
    "to the WRI Nairobi rider survey (2023). Heat exposure is the sum, over every minute spent outdoors (walking or "
    "waiting at a stop), of the degrees by which the Universal Thermal Climate Index (UTCI) at the agent's position "
    "exceeds 26 °C, the lower bound of UTCI's moderate heat stress category; minutes riding inside a vehicle add "
    "nothing. UTCI comes from 10 m hourly rasters for 14 March 2025.",
    "",
    f"Across all agents, mean daily exposure is {N['mean']:.0f} °C·min (median {N['median']:.0f}; 90th percentile "
    f"{N['p90']:.0f}). {N['zero_pct']:.1f}% of agents have zero exposure: all their outdoor minutes were at UTCI of "
    "26 °C or below.",
    "",
    "## Model parameters",
    "",
    "Table 1 lists every behavioural rule and parameter of the main run, which agent attributes it depends on, and "
    "its source. Age group and sex are assigned to each agent from WorldPop at its home location. Age sets two "
    "rules, both for children (0–14): they make only school trips, and they leave for school before 08:00. Sex sets "
    "none. Purpose shares of everyone over 14, mode choice, walking speed and waiting behaviour are the same for all "
    "ages and both sexes: the calibration uses no age or sex breakdowns, "
    "the WRI rider survey interviewed only adults (18+) riding buses and matatus, and the JICA walk-share curves "
    "are given by trip purpose only. Wealth (RWI) "
    "and informality are used only to group results, not to set behaviour. Table 2 gives the resulting composition "
    "of the simulated population and its mix of trip purposes.",
    "",
]
for key, cap, note in BTABLES:
    md += [md_table(B[key]), "", f"Table: {cap}", "", note, ""]
md += [
    "## Figures",
    "",
]
for stem, width, cap in FIGS:
    md += [f"![{cap}]({stem}.svg){{width={width}}}", ""]
md += ["## Tables", ""]
for key, cap, note in TABLES:
    md += [md_table(T[key]), "", f"Table: {cap}", "", note, ""]

# ---- Part 2: behavioural sensitivity (notebook 02) ---------------------------------------------
NB02 = HERE.parent / "paper_nb02"
if (NB02 / "tables.json").exists():
    T2 = json.loads((NB02 / "tables.json").read_text(encoding="utf-8"))
    N2 = T2["numbers"]
    top = N2["top"]
    import csv
    with open(NB02 / "morris_indices.csv", encoding="utf-8") as f:
        _mi = {r["factor"]: float(r["mu_star"]) for r in csv.DictReader(f) if r["outcome"] == "mean_exposure"}
    mu_of = _mi.__getitem__
    MU = "μ\\*"  # escaped for pandoc markdown
    FIGS2 = [
        ("../paper_nb02/fig5_morris_mean_exposure", "4.6in",
         f"**Figure 5.** Behavioural factors ranked by their influence on mean daily exposure per person (Morris {MU}: "
         "the mean absolute change in the outcome when the factor moves two-thirds of its range, over "
         f"{N2['trajectories']} trajectories). Lines: 95% bootstrap intervals across trajectories. Arrows: ↑ raising "
         f"the factor raises exposure, ↓ lowers it, ↕ mixed (|μ| < 0.8 {MU}). Dashed line: seed-to-seed SD of the "
         f"outcome at the baseline ({N2['base_sd']:.0f} °C·min, {N2['n_baseline']} replicates). "
         f"{N2['n_agents']:,} agents per run."),
        ("../paper_nb02/fig6_duration_vs_temperature", "6.5in",
         f"**Figure 6.** Morris {MU} for the two parts of exposure: (a) minutes outdoors per person and (b) the mean "
         "UTCI experienced while outdoors (raw UTCI, no threshold). Factors in the order of Figure 5; arrows as in "
         "Figure 5, for that outcome. Dashed lines: seed-to-seed SD at the baseline."),
        ("../paper_nb02/fig7_outcome_heatmap", "6.5in",
         f"**Figure 7.** Morris {MU} of each factor for each outcome, relative to the most influential factor for that "
         "outcome (1.00). The two right-hand columns are equity gaps: mean exposure of the poorest minus the richest "
         "Relative Wealth Index quintile, and of medium/high minus low informality. These are differences of group "
         "means and much noisier than the city-wide outcomes (Table 10). Share home by 20:00: share of travellers "
         "back home by the end of the simulated day."),
        ("../paper_nb02/fig8_wait_tolerance", "4.8in",
         "**Figure 8.** The wait-tolerance threshold. (a) Mean daily exposure and (b) minutes outdoors per person in "
         "every Morris run, by the run's wait tolerance (the longest wait for a vehicle an agent accepts before "
         "walking instead). Points: runs (jittered horizontally); line: mean over runs at each level, all other "
         "factors varying. Dashed line: the baseline mean boarding wait (5.65 min)."),
    ]
    TABLES2 = [
        ("table7", "**Table 9.** Behavioural factors varied in the sensitivity analysis.",
         "Note. Geography (street network, heat rasters, population, amenities) and the transit service (GTFS routes "
         "and frequencies) are held fixed. Ranges for survey-calibrated factors span the WRI rider survey's own "
         "sub-group fits; the others are assumptions around the model default. Not varied: trip rate (one round "
         "trip per agent), travel probability (scales who travels, not the exposure of those who do), minimum stay "
         "and dwell-time spread (their medians are varied instead), and demographic modifiers (neutral by default)."),
        ("table8", f"**Table 10.** Outcomes at the baseline parameters over {N2['n_baseline']} replicate runs "
         "with different random seeds.",
         f"Note. {N2['n_agents']:,} agents per run. The SD is the sampling noise of a single run and the noise floor "
         "for the Morris indices. Elementary effects themselves are less noisy than this, because each step of a "
         "trajectory reuses the previous run's seed (common random numbers)."),
        ("table9", f"**Table 11.** Morris sensitivity indices for mean daily exposure per person (°C·min above 26 °C "
         "UTCI) and for its two parts.",
         f"Note. {MU}: mean absolute elementary effect, with 95% bootstrap interval across trajectories; μ: signed "
         "mean; σ: standard deviation of the elementary effects (non-linearity or interaction with other factors). "
         f"Dir.: ↑ / ↓ when |μ| ≥ 0.8 {MU}, otherwise ↕. Last two columns: {MU} for mean minutes outdoors and mean "
         "UTCI while outdoors. Indices for all twelve outcomes are in paper_nb02/table9_mu_star_all_outcomes.csv."),
    ]
    FIGS = FIGS + FIGS2
    md += [
        "# Behavioural sensitivity",
        "",
        "## Method",
        "",
        f"Which behavioural assumptions drive the results? {N2['n_factors']} behavioural factors (Table 9) were "
        "screened with the Morris method of elementary effects. Each of "
        f"{N2['trajectories']} trajectories starts at a random point on a 4-level grid over the factor ranges and "
        f"changes one factor at a time by two-thirds of its range; {MU} is the mean absolute change in an outcome "
        f"per such step. Each run simulates {N2['n_agents']:,} agents making a round trip, with the model otherwise "
        f"as in the main results: {N2['n_morris']} Morris runs plus {N2['n_baseline']} baseline replicates.",
        "",
        "## Results",
        "",
        f"At the baseline, mean exposure is {N2['base_mean']:.0f} °C·min per person (seed-to-seed SD "
        f"{N2['base_sd']:.0f}), with {N2['base_outdoor']:.0f} minutes outdoors; {N2['base_return_share']:.0f}% "
        "of exposure is picked up on the trip home. Across all runs, mean exposure ranged from "
        f"{N2['range_min']:.0f} to {N2['range_max']:.0f} °C·min. {N2['n_above_noise']} of the "
        f"{N2['n_factors']} factors have {MU} more than twice the seed SD. The most influential are "
        + ", ".join(f"{n.lower()} ({v:.0f})" for n, v in top[:4])
        + f" and {top[4][0].lower()} ({top[4][1]:.0f} °C·min; Figure 5, Table 11).",
        "",
        "Factors act through one of two channels (Figure 6). Route and mode behaviour (wait tolerance, destination "
        "distance decay, walk share, walking speed, boarding wait, walking-time weight) changes how long people are "
        "outdoors. Timing behaviour (morning departure peak, purpose-specific departure timing, work and school end "
        "times) barely changes minutes outdoors but shifts when in the day they fall, and so the UTCI experienced. "
        f"Work end time ({MU} {mu_of('work_end_hour_mean'):.0f}) acts almost entirely through temperature: a later "
        "end moves the trip home out of the afternoon heat. School end time acts the same way "
        f"({MU} {mu_of('school_end_hour_mean'):.0f}); it matters because every child makes a school round trip and "
        "comes home in the mid-afternoon.",
        "",
        "The wait-tolerance effect is a threshold, not a gradient (Figure 8). At a tolerance of 5 minutes, below the "
        f"5.65-minute mean boarding wait, mean exposure averaged {N2['wait_tol_5']:.0f} °C·min and "
        f"{N2['wait_tol_5_out']:.0f} minutes outdoors across runs, because most would-be riders walk instead; from "
        f"13 to 30 minutes it was nearly flat ({N2['wait_tol_ge13_lo']:.0f}–{N2['wait_tol_ge13_hi']:.0f} °C·min). "
        f"Its large {MU} and σ come almost entirely from steps to or from the 5-minute level.",
        "",
        "The equity gaps (Figure 7) are most sensitive to wait tolerance, walk share and destination distance decay, "
        "that is, to whether people ride and how far they travel. They are noisy at the baseline (Table 10), so their rankings "
        "are less certain than those for the city-wide outcomes.",
        "",
        "## Figures",
        "",
    ]
    for stem, width, cap in FIGS2:
        md += [f"![{cap}]({stem}.svg){{width={width}}}", ""]
    md += ["## Tables", ""]
    for key, cap, note in TABLES2:
        md += [md_table(T2[key]), "", f"Table: {cap}", "", note, ""]
    TABLES = TABLES + TABLES2

src =HERE / "heat_exposure_main_results.md"
src.write_text("\n".join(md), encoding="utf-8")
subprocess.run(["pandoc", src.name, "-o", OUT.name, "--resource-path=."], cwd=HERE, check=True)

# ---- Add PNG fallbacks for the SVG figures ----------------------------------------------------
with zipfile.ZipFile(OUT) as z:
    files = {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
doc = files["word/document.xml"].decode("utf-8")
rels = files["word/_rels/document.xml.rels"].decode("utf-8")
ctypes = files["[Content_Types].xml"].decode("utf-8")

blip_re = re.compile(r'<a:blip>(<a:extLst>.*?<asvg:svgBlip[^>]*r:embed="(rId\d+)"[^>]*/>.*?</a:extLst>)</a:blip>', re.S)
matches = list(blip_re.finditer(doc))
assert len(matches) == len(FIGS), (len(matches), len(FIGS))
for (stem, _, _), m in zip(FIGS, matches):
    svg_rid = m.group(2)
    png_rid = f"{svg_rid}png"
    name = Path(stem).name  # stem may carry a folder (../paper_nb02/...)
    png_name = f"media/{name}.png"
    files[f"word/{png_name}"] = (HERE / f"{stem}.png").read_bytes()
    # Point the SVG relationship at a plainly named .svg file.
    old_target = re.search(rf'Id="{svg_rid}" Target="([^"]+)"', rels).group(1)
    files[f"word/media/{name}.svg"] = files.pop(f"word/{old_target}")
    rels = rels.replace(f'Id="{svg_rid}" Target="{old_target}"', f'Id="{svg_rid}" Target="media/{name}.svg"')
    rels = rels.replace("</Relationships>",
                        f'<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                        f'Id="{png_rid}" Target="{png_name}" /></Relationships>')
    doc = doc.replace(m.group(0), f'<a:blip r:embed="{png_rid}">{m.group(1)}</a:blip>', 1)

for ext, ct in (("png", "image/png"), ("svg", "image/svg+xml")):
    if f'Extension="{ext}"' not in ctypes:
        ctypes = ctypes.replace("<Default ", f'<Default Extension="{ext}" ContentType="{ct}" /><Default ', 1)

files["word/document.xml"] = doc.encode("utf-8")
files["word/_rels/document.xml.rels"] = rels.encode("utf-8")
files["[Content_Types].xml"] = ctypes.encode("utf-8")
order = ["[Content_Types].xml"] + [n for n in files if n != "[Content_Types].xml"]
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for n in order:
        z.writestr(n, files[n])
print(f"Wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB): {len(FIGS)} figures, {len(BTABLES) + len(TABLES)} tables")
