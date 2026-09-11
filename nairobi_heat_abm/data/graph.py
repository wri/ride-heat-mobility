from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd

# Synthetic node IDs for GTFS stops start well above any real OSM node ID for this bbox
# (observed max ~1.4e10 for the Nairobi graph) so the two ID spaces never collide.
TRANSIT_STOP_ID_OFFSET = 10**13


def build_graph(
    bbox: tuple[float, float, float, float],  # (south, west, north, east)
    gtfs_path: str | Path | None = None,
    cache_path: str | Path = "data/raw/graph.graphml",
    force_rebuild: bool = False,
) -> nx.MultiDiGraph:
    """Build and cache the walkable OSM graph, optionally augmented with GTFS transit."""
    cache_path = Path(cache_path)
    if cache_path.exists() and not force_rebuild:
        return ox.load_graphml(cache_path)

    # osmnx 2.x bbox = (left, bottom, right, top) = (west, south, east, north)
    G = ox.graph_from_bbox(
        bbox=(bbox[1], bbox[0], bbox[3], bbox[2]),
        network_type="walk",
        retain_all=False,
    )
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    G = ox.project_graph(G, to_crs="EPSG:4326")

    nx.set_node_attributes(G, "intersection", name="node_type")

    if gtfs_path is not None:
        _integrate_gtfs(G, Path(gtfs_path), bbox)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, filepath=cache_path)
    return G


def _read_gtfs_table(gtfs_path: Path, name: str) -> pd.DataFrame:
    """Read one GTFS CSV table from either a directory of .txt files or a .zip feed
    (e.g. DigitalMatatus's GTFS_FEED_2019.zip, which stores the files at its root)."""
    if gtfs_path.is_dir():
        return pd.read_csv(gtfs_path / name)
    with zipfile.ZipFile(gtfs_path) as zf, zf.open(name) as f:
        return pd.read_csv(f)


def _gtfs_time_to_seconds(t: str) -> int:
    """GTFS HH:MM:SS; hours may exceed 23 for a trip that runs past midnight."""
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6_371_000.0
    lon1r, lat1r, lon2r, lat2r = np.radians([lon1, lat1, lon2, lat2])
    dlon, dlat = lon2r - lon1r, lat2r - lat1r
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2
    return float(R * 2.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0))))


def _integrate_gtfs(
    G: nx.MultiDiGraph, gtfs_path: Path, bbox: tuple[float, float, float, float],
) -> None:
    """
    Parse a DigitalMatatus-style GTFS feed (a directory of .txt files, or a .zip
    containing them at its root) and mutate G in-place:
      - one "transit_stop" node per stop_id inside the study bbox, with bidirectional
        walk "access_link" edges to the nearest existing walk-network node
      - one directed "transit" edge per consecutive stop-pair actually ridden on some
        trip, weighted by that trip's own stop_times.txt travel time between the two

    This feed is frequency-based, not a literal timetable: every trip in stop_times.txt
    is a single reference run (all starting at the same nominal clock time — 6:00:20 in
    the 2019 Nairobi feed), and real service frequency lives entirely in
    frequencies.txt, as headway bands per trip. So each transit edge carries its trip's
    frequency bands directly (`frequencies`: a list of [start_s, end_s, headway_secs]
    triples, seconds since midnight) rather than a fixed departure_time — see
    model/routing.py::route_transit(), which looks up the headway applying at an
    agent's actual departure time instead of matching a single literal timestamp.
    Trips with no frequencies.txt entry (a small minority) contribute no transit
    edges — there's no way to know how often they actually run.
    """
    stops = _read_gtfs_table(gtfs_path, "stops.txt")
    trips = _read_gtfs_table(gtfs_path, "trips.txt")
    stop_times = _read_gtfs_table(gtfs_path, "stop_times.txt")
    try:
        frequencies = _read_gtfs_table(gtfs_path, "frequencies.txt")
    except (FileNotFoundError, KeyError):
        frequencies = pd.DataFrame(columns=["trip_id", "start_time", "end_time", "headway_secs"])

    # The DigitalMatatus feed covers a wider area than the walk network's bbox. A stop
    # outside the bbox has no nearby walk node, so ox.nearest_nodes would snap it to
    # whichever boundary node happens to be closest -- however far away that really is --
    # producing long straight access_link edges that fan out from the network's edge.
    south, west, north, east = bbox
    in_bbox = (
        stops["stop_lat"].between(south, north) & stops["stop_lon"].between(west, east)
    )
    n_dropped = int((~in_bbox).sum())
    if n_dropped:
        print(f"Dropping {n_dropped:,}/{len(stops):,} GTFS stops outside the study bbox.")
    stops = stops.loc[in_bbox].reset_index(drop=True)

    # --- Stops: one node per stop_id ---
    stop_ids = sorted(stops["stop_id"].unique())
    stop_node_id = {stop_id: TRANSIT_STOP_ID_OFFSET + i for i, stop_id in enumerate(stop_ids)}
    for row in stops.itertuples():
        G.add_node(
            stop_node_id[row.stop_id],
            x=float(row.stop_lon), y=float(row.stop_lat),
            node_type="transit_stop", stop_id=row.stop_id,
            stop_name=getattr(row, "stop_name", ""),
        )

    # --- Access links: bidirectional walk edges from each stop to the nearest walk-network node ---
    walk_node_ids = [n for n, d in G.nodes(data=True) if d.get("node_type") != "transit_stop"]
    walk_subgraph = G.subgraph(walk_node_ids)
    nearest_walk_nodes = ox.nearest_nodes(
        walk_subgraph, X=stops["stop_lon"].to_numpy(), Y=stops["stop_lat"].to_numpy(),
    )
    for row, nearest_node in zip(stops.itertuples(), nearest_walk_nodes):
        stop_nid = stop_node_id[row.stop_id]
        nearest_node = int(nearest_node)
        length = max(_haversine_m(
            row.stop_lon, row.stop_lat, G.nodes[nearest_node]["x"], G.nodes[nearest_node]["y"],
        ), 1.0)
        travel_time = length / 1.2  # default walk speed
        G.add_edge(stop_nid, nearest_node, length=length, travel_time=travel_time, edge_type="access_link")
        G.add_edge(nearest_node, stop_nid, length=length, travel_time=travel_time, edge_type="access_link")

    # --- Frequency bands per trip: [[start_s, end_s, headway_secs], ...] ---
    freq_by_trip: dict[str, list[list[int]]] = {
        trip_id: [
            [_gtfs_time_to_seconds(r.start_time), _gtfs_time_to_seconds(r.end_time), int(r.headway_secs)]
            for r in grp.itertuples()
        ]
        for trip_id, grp in frequencies.groupby("trip_id")
    }
    trip_route = dict(zip(trips["trip_id"], trips["route_id"]))

    # --- Transit edges: consecutive stop-pairs per trip, weighted by real ride time ---
    stop_times = stop_times.sort_values(["trip_id", "stop_sequence"]).copy()
    stop_times["arr_s"] = stop_times["arrival_time"].map(_gtfs_time_to_seconds)
    stop_times["dep_s"] = stop_times["departure_time"].map(_gtfs_time_to_seconds)

    for trip_id, grp in stop_times.groupby("trip_id"):
        bands = freq_by_trip.get(trip_id)
        if not bands:
            continue  # no frequency info for this trip -> no way to model real service
        rows = list(grp.itertuples())
        for prev, cur in zip(rows[:-1], rows[1:]):
            u = stop_node_id.get(prev.stop_id)
            v = stop_node_id.get(cur.stop_id)
            if u is None or v is None or u == v:
                continue
            ride_secs = cur.arr_s - prev.dep_s
            if ride_secs <= 0:
                continue
            length = max(_haversine_m(
                G.nodes[u]["x"], G.nodes[u]["y"], G.nodes[v]["x"], G.nodes[v]["y"],
            ), 1.0)
            G.add_edge(
                u, v,
                length=length, travel_time=float(ride_secs),
                edge_type="transit", route_id=trip_route.get(trip_id, ""), trip_id=trip_id,
                frequencies=bands,
            )


if __name__ == "__main__":
    import yaml

    parser = argparse.ArgumentParser(description="Build and cache the Nairobi OSM graph")
    parser.add_argument("--build", action="store_true", help="Download and cache the graph")
    parser.add_argument("--force", action="store_true", help="Rebuild even if cache exists")
    args = parser.parse_args()

    if args.build:
        with open("config.yaml") as f:
            cfg = yaml.safe_load(f)
        b = cfg["bbox"]
        bbox = (b["south"], b["west"], b["north"], b["east"])
        gtfs_path = cfg["paths"].get("gtfs_path")
        if gtfs_path is not None and not Path(gtfs_path).exists():
            gtfs_path = None
        G = build_graph(bbox, gtfs_path=gtfs_path, cache_path=cfg["paths"]["graph_cache"], force_rebuild=args.force)
        n_transit_stops = sum(1 for _, d in G.nodes(data=True) if d.get("node_type") == "transit_stop")
        print(f"Graph built: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges "
              f"({n_transit_stops:,} transit stops)")
