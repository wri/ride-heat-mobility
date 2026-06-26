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
    raise NotImplementedError


def load_amenity_index(
    cache_path: str | Path = "data/raw/amenities.json",
) -> dict[str, list[int]]:
    with open(cache_path) as f:
        return json.load(f)
