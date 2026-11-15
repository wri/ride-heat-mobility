# Nairobi pedestrian heat-exposure model

An agent-based model (ABM) of how much heat Nairobi residents are exposed to as they walk, wait for and ride matatus and buses on a hot day. Simulated travellers move over the OpenStreetMap street network and the DigitalMatatus GTFS network. Exposure is accumulated minute by minute from hourly 10 m Universal Thermal Climate Index (UTCI) rasters and reported in °C·min above 26 °C UTCI. Exposure is broken down by age group, gender, travel mode, trip purpose, street segment, matatu stage, home ward, and the wealth and informality of the home area.

The model is designed as a **low-data approach**. It is built almost entirely on free global datasets, and its travel behaviour is set from a small intercept survey of transit riders. A behavioural sensitivity analysis (Morris elementary effects) shows which local data would most improve the results when the model is applied elsewhere.

> [!WARNING]
> **This project is still in testing, and its results have not been validated.** Neither the heat model nor the travel model has been checked against observations in Nairobi, such as wearable-sensor measurements of pedestrians' exposure or detailed travel diaries. Treat the outputs as preliminary: suggestive patterns, and a demonstration of what a low-data approach can produce. Don't use them as measured exposure values. The code, parameters and outputs may change.

## Part of RIDE

This work is part of [Research on Infrastructure in Developing Economies (RIDE)](https://ride.transport-links.com/), which is funded by the UK Foreign, Commonwealth & Development Office. It is developed at the World Resources Institute's Ross Center for Sustainable Cities.

## Paper

A paper describing the method and first results has been prepared for the African Transport Research Conference 2027 (ATRC-2027):

> Wong, T., Engel, R., Tun, T.H. *Modeling person-scale heat-health hazards for pedestrians in Nairobi, Kenya.*

The draft is in [`papers/`](papers/). The scripts that produce its figures and tables are in [`artifacts/paper_nb01/`](artifacts/paper_nb01/) and [`artifacts/paper_nb02/`](artifacts/paper_nb02/).

## Repository layout

| Path | Contents |
|---|---|
| `nairobi_heat_abm/data/` | Loaders for the street graph, GTFS, WorldPop, amenities, UTCI rasters and the ward, wealth and informality layers |
| `nairobi_heat_abm/model/` | Agents, scheduling, walk and transit routing, segment-level exposure, the simulation runner |
| `nairobi_heat_abm/analysis/` | Exposure summaries and plots |
| `nairobi_heat_abm/rdm/` | Batch runs, sampling and the Morris sensitivity analysis |
| `nairobi_heat_abm/app/` | Interactive Panel app |
| `nairobi_heat_abm/calibration.py`, `departure_fit.py` | Fitting behaviour parameters to the WRI rider survey |
| `notebooks/01_nairobi_heat_abm.ipynb` | Main end-to-end run |
| `config.yaml` | Study area, simulation window, data paths, sensitivity-analysis settings |
| `docs/dev/` | Developer documentation: setup, architecture, testing |
| `docs/methodology/` | Methodology notes: exposure metric, data choices, travel behaviour, uncertainty |
| `tests/` | pytest suite |

## Getting started

Requires Python 3.10 or 3.11.

```bash
git clone https://github.com/wri/ride-heat-mobility.git
cd ride-heat-mobility
python -m venv .venv
.venv/Scripts/activate        # Windows; on macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

Raw data aren't tracked in git. Put them in `data/raw/` as listed in [`docs/dev/setup.md`](docs/dev/setup.md) and `config.yaml`. They are WorldPop population rasters, the DigitalMatatus GTFS feed, hourly UTCI rasters, and the ward, Relative Wealth Index and IDEAMAPS informality layers. `config.yaml` gives the source of each. Build the OpenStreetMap walking graph once with:

```bash
python -m nairobi_heat_abm.data.graph --build
```

Then:

```bash
pytest tests/ -m "not slow"                      # tests on synthetic fixtures
jupyter lab notebooks/01_nairobi_heat_abm.ipynb  # main model run (Jupyter not included in the dependencies)
python -m nairobi_heat_abm.app                   # interactive app (http://localhost:5006)
python -m nairobi_heat_abm.rdm.run_sensitivity   # Morris sensitivity analysis
```

On Windows machines with Anaconda installed, `PROJ_DATA` and `GDAL_DATA` can point rasterio at the wrong PROJ database. If you see a `DATABASE.LAYOUT.VERSION.MINOR` error, set both variables to the `proj_data` and `gdal_data` folders inside the installed `rasterio` package. The notebook and the sensitivity script already do this.

## Data sources

Street network and destinations: OpenStreetMap. Matatu network: DigitalMatatus GTFS. Population: WorldPop. Thermal comfort: UTCI modelled with SOLWEIG-GPU from open global inputs. Travel behaviour: a WRI survey of Nairobi bus and matatu riders and the 2013 JICA person-trip survey. Wealth: Meta Relative Wealth Index. Informality: IDEAMAPS morphological informality. Wards: geoBoundaries. See the paper and `config.yaml` for citations and licences. Some layers are licensed CC BY-NC.
