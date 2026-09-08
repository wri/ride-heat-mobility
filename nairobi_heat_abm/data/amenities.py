from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import osmnx as ox

# Each category is a list of separate tag queries, fetched and merged independently (see
# build_amenity_index) rather than one combined multi-key query — a combined query (e.g. the
# old "shop": True catch-all) can be large/expensive enough to time out against the Overpass
# API, and a failure in one tag query would otherwise silently empty out the whole category.
AMENITY_TAGS: dict[str, list[dict]] = {
    "school": [{"amenity": ["school", "university", "college"]}],
    # Food shops only: supermarkets and open-air/public markets. Deliberately excludes
    # shop=convenience (too granular/ubiquitous to be a meaningful trip destination) and
    # restaurants/cafes (amenity=restaurant|fast_food|cafe -- food service, not food shopping).
    "food": [{"shop": ["supermarket"]}, {"amenity": ["marketplace"]}],
    "health": [{"amenity": ["hospital", "clinic", "pharmacy", "doctors"]}],
    "other": [{"amenity": ["place_of_worship", "community_centre", "library"]}],
    "work": [
        {"office": True},
        {"craft": True},
        {"landuse": ["commercial", "industrial"]},
        {"building": ["office", "commercial", "industrial", "warehouse"]},
        {"amenity": ["townhall", "courthouse", "bank"]},
        # All shops (not just the food-shop subset in "food" above) employ workers, so
        # they belong in "work" even though "food" only surfaces supermarkets/markets as
        # a *destination* category. shop=True doesn't cover amenity=marketplace, which is
        # why "food" is also merged in below via _WORK_OVERLAP_CATEGORIES.
        {"shop": True},
    ],
}

# Food shops, schools, and health facilities also employ workers (not just serve clients/
# students/patients), so they belong in the "work" destination pool too, on top of the
# work-specific tags above (which already include all shops via shop=True — this adds
# amenity=marketplace, the one food-shop type shop=True doesn't cover). Node IDs already
# present in "work" are not duplicated.
_WORK_OVERLAP_CATEGORIES = ("school", "food", "health")


def _add_work_overlap(result: dict[str, list[int]]) -> None:
    combined = list(result.get("work", []))
    seen = set(combined)
    for category in _WORK_OVERLAP_CATEGORIES:
        for node_id in result.get(category, []):
            if node_id not in seen:
                seen.add(node_id)
                combined.append(node_id)
    result["work"] = combined


def build_amenity_index(
    bbox: tuple[float, float, float, float],  # (south, west, north, east)
    G: nx.MultiDiGraph,
    cache_path: str | Path = "data/raw/amenities.json",
    force_rebuild: bool = False,
) -> dict[str, list[int]]:
    """
    Fetch OSM POIs for each category, snap to nearest graph node. Each category's tag
    queries (AMENITY_TAGS) are fetched and merged/deduped independently, so one query
    timing out or erroring only drops that query's contribution, not the whole category.
    Returns { "school": [node_id, ...], "food": [...], ... }
    """
    cache_path = Path(cache_path)
    if cache_path.exists() and not force_rebuild:
        return load_amenity_index(cache_path)

    south, west, north, east = bbox
    result: dict[str, list[int]] = {}

    for category, tag_queries in AMENITY_TAGS.items():
        seen: set[int] = set()
        node_ids: list[int] = []
        for tags in tag_queries:
            try:
                # osmnx 2.x bbox = (left, bottom, right, top) = (west, south, east, north)
                gdf = ox.features_from_bbox(
                    bbox=(west, south, east, north),
                    tags=tags,
                )
                if gdf.empty:
                    continue
                centroids = gdf.geometry.centroid
                lons = centroids.x.values
                lats = centroids.y.values
                snapped = ox.nearest_nodes(G, X=lons, Y=lats)
                for nid in snapped:
                    nid = int(nid)
                    if nid in seen or not G.has_node(nid):
                        continue
                    seen.add(nid)
                    G.nodes[nid]["node_type"] = "amenity"
                    G.nodes[nid].setdefault("amenity_type", category)
                    node_ids.append(nid)
            except Exception:
                pass
        result[category] = node_ids

    _add_work_overlap(result)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(result, f)

    return result


def load_amenity_index(
    cache_path: str | Path = "data/raw/amenities.json",
) -> dict[str, list[int]]:
    with open(cache_path) as f:
        return json.load(f)
