from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import osmnx as ox

AMENITY_TAGS: dict[str, dict] = {
    "school": {"amenity": ["school", "university", "college"]},
    "shop":   {"shop": True, "amenity": ["marketplace", "supermarket"]},
    "health": {"amenity": ["hospital", "clinic", "pharmacy", "doctors"]},
    "other":  {"amenity": ["place_of_worship", "community_centre", "library"]},
}


def build_amenity_index(
    bbox: tuple[float, float, float, float],  # (south, west, north, east)
    G: nx.MultiDiGraph,
    cache_path: str | Path = "data/raw/amenities.json",
    force_rebuild: bool = False,
) -> dict[str, list[int]]:
    """
    Fetch OSM POIs for each category, snap to nearest graph node.
    Returns { "school": [node_id, ...], "shop": [...], ... }
    """
    cache_path = Path(cache_path)
    if cache_path.exists() and not force_rebuild:
        return load_amenity_index(cache_path)

    south, west, north, east = bbox
    result: dict[str, list[int]] = {}

    for category, tags in AMENITY_TAGS.items():
        node_ids: list[int] = []
        try:
            # osmnx 2.x bbox = (left, bottom, right, top) = (west, south, east, north)
            gdf = ox.features_from_bbox(
                bbox=(west, south, east, north),
                tags=tags,
            )
            if not gdf.empty:
                centroids = gdf.geometry.centroid
                lons = centroids.x.values
                lats = centroids.y.values
                snapped = ox.nearest_nodes(G, X=lons, Y=lats)
                for nid in snapped:
                    if G.has_node(nid):
                        G.nodes[nid]["node_type"] = "amenity"
                        G.nodes[nid].setdefault("amenity_type", category)
                node_ids = [int(nid) for nid in snapped]
        except Exception:
            pass
        result[category] = node_ids

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(result, f)

    return result


def load_amenity_index(
    cache_path: str | Path = "data/raw/amenities.json",
) -> dict[str, list[int]]:
    with open(cache_path) as f:
        return json.load(f)
