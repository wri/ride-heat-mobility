from __future__ import annotations

import argparse
from pathlib import Path

import networkx as nx
import osmnx as ox


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

    G = ox.graph_from_bbox(
        north=bbox[2], south=bbox[0], east=bbox[3], west=bbox[1],
        network_type="walk",
        retain_all=False,
        clean_periphery=True,
    )
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    G = ox.project_graph(G, to_crs="EPSG:4326")

    nx.set_node_attributes(G, "intersection", name="node_type")

    if gtfs_path is not None:
        _integrate_gtfs(G, Path(gtfs_path))

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, filepath=cache_path)
    return G


def _integrate_gtfs(G: nx.MultiDiGraph, gtfs_path: Path) -> None:
    """
    Parse GTFS stops.txt and stop_times.txt/trips.txt.
    Inserts transit_stop nodes and transit/access_link edges into G in-place.
    """
    raise NotImplementedError


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
        G = build_graph(bbox, cache_path=cfg["paths"]["graph_cache"], force_rebuild=args.force)
        print(f"Graph built: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")
