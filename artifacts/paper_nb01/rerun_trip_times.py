"""
Re-run the notebook 01 main run (N_AGENTS agents, seed 42, default behaviour) to save the
per-agent times that the GeoPackage doesn't store: door-to-door minutes of the trip out and
the trip home, minutes riding, minutes outdoors. Same setup as notebook 01 cells 2-26, so the
run is identical (checked against the GeoPackage's exposure column).

Writes outputs/agent_times_<N_AGENTS>agents_seed42.csv.
Run from the repo root:  .venv/Scripts/python.exe artifacts/paper_nb01/rerun_trip_times.py
"""
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_rio = ROOT / ".venv" / "Lib" / "site-packages" / "rasterio"
if (_rio / "proj_data").exists():
    os.environ["PROJ_DATA"] = str(_rio / "proj_data"); os.environ.pop("PROJ_LIB", None)
    os.environ["GDAL_DATA"] = str(_rio / "gdal_data")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from nairobi_heat_abm.data.amenities import build_amenity_index  # noqa: E402
from nairobi_heat_abm.data.graph import build_graph  # noqa: E402
from nairobi_heat_abm.data.heat import load_heat_surface  # noqa: E402
from nairobi_heat_abm.model.agent import DemographicParams, TravelBehaviorParams  # noqa: E402
import nairobi_heat_abm.model.simulation as sim  # noqa: E402
from nairobi_heat_abm.model.simulation import SimulationParams, load_context, run  # noqa: E402
from run_config import N_AGENTS  # noqa: E402

# Outbound departure ticks aren't in SimulationResult; capture them where run() hands them to
# assign_routes (read-only pass-through, the run itself is unchanged).
_captured = {}
_assign_routes = sim.assign_routes


def _capture(pool, G, spawn_nodes, dest_nodes, departure_ticks, *args, **kwargs):
    _captured["departure_ticks"] = np.array(departure_ticks, copy=True)
    return _assign_routes(pool, G, spawn_nodes, dest_nodes, departure_ticks, *args, **kwargs)


sim.assign_routes = _capture

cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
b = cfg["bbox"]
BBOX = (b["south"], b["west"], b["north"], b["east"])
SIM, PATHS = cfg["simulation"], cfg["paths"]
GRAPH_CACHE, AMENITY_CACHE = ROOT / PATHS["graph_cache"], ROOT / PATHS["amenity_cache"]
GTFS = ROOT / PATHS["gtfs_path"]
WP_PATHS = {k: ROOT / p for k, p in PATHS["worldpop_tifs"].items()}

t0 = time.time()
G = build_graph(BBOX, gtfs_path=GTFS if GTFS.exists() else None, cache_path=GRAPH_CACHE, force_rebuild=False)
surface = load_heat_surface(ROOT / PATHS["heat_dir"], bbox=BBOX)
build_amenity_index(BBOX, G, cache_path=AMENITY_CACHE, force_rebuild=False)
params = SimulationParams(
    bbox=BBOX, n_agents=N_AGENTS, start_hour=SIM["start_hour"], end_hour=SIM["end_hour"],
    timestep_s=SIM["timestep_seconds"], seed=SIM["default_seed"], behavior=TravelBehaviorParams(),
    graph_cache_path=GRAPH_CACHE, amenity_cache_path=AMENITY_CACHE, worldpop_tif_path=WP_PATHS["total"],
    heat_surface=surface,
    demographics=DemographicParams(population_raster_paths=WP_PATHS, informal_settlement_path=None),
)
print(f"setup {time.time() - t0:.0f} s; running {N_AGENTS} agents, seed {params.seed}", flush=True)
r = run(params, context=load_context(params, G=G))
print(f"run {r.elapsed_seconds:.0f} s", flush=True)

out = pd.DataFrame({
    "agent_id": np.arange(N_AGENTS),
    "heat_degC_min": r.agent_exposure_degC_min,
    "trip_out_min": r.agent_trip_min,
    "trip_home_min": r.agent_return_trip_min,
    "returned": r.agent_returned,
    "depart_out_hour": params.start_hour + _captured["departure_ticks"] * params.timestep_s / 3600.0,
    "return_departure_hour": r.agent_return_departure_hour,
    "ride_min": r.agent_ride_min,
    "outdoor_min": r.agent_outdoor_min,
})
gp = gpd.read_file(ROOT / "outputs" / f"heat_exposure_heat_{N_AGENTS}agents_seed42.gpkg",
                   layer="agent_homes", ignore_geometry=True).sort_values("agent_id")
diff = np.abs(out["heat_degC_min"].to_numpy() - gp["heat_degC_min"].to_numpy()).max()
print(f"max |exposure - GeoPackage exposure| = {diff:.4f}  (0 => identical run)")
dest = ROOT / "outputs" / f"agent_times_{N_AGENTS}agents_seed42.csv"
out.to_csv(dest, index=False)
print(f"wrote {dest}")
