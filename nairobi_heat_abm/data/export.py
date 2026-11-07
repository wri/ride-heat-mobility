"""
GIS export of simulation results: street segments and transit stops coloured by the
total heat exposure (°C·min of UTCI above 26 °C) of everyone who walked or waited there, written to a
GeoPackage with an embedded QGIS style so the layers open already symbolised.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from xml.sax.saxutils import quoteattr

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

CRS = "EPSG:4326"

# ColorBrewer YlOrRd, the 7 darkest of its 9-class ramp, light -> dark (the palest
# yellows vanish against white or light basemaps).
_YLORRD = ["#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#bd0026", "#800026"]

# GeoPackage 1.2 rather than GDAL's newest default (1.4), so older GDAL builds (e.g.
# QGIS 3.30's) open the file without "may only be partially supported" warnings.
_GPKG_VERSION = "1.2"


def _attr_str(value) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(v) for v in value)
    return str(value)


def segment_layer(G: nx.MultiDiGraph, segment_exposure: pd.DataFrame) -> gpd.GeoDataFrame:
    """
    One line feature per street segment that anyone walked, with both travel directions
    combined (the walk graph stores each street as a u->v and a v->u edge with the same
    geometry; a map wants one line per street).

    Columns: u, v, key, name, highway, edge_type, length_m, heat_degC_min (total over all
    agents), person_min, mean_heat_degC (= heat_degC_min / person_min, the average
    UTCI excess above the threshold people experienced there), heat_degC_min_per_100m (length-normalised,
    so long segments don't dominate just by being long), and, when segment_exposure has
    n_persons: n_persons (people who walked the segment; the two directions are added,
    so someone who walked it both ways counts twice), heat_degC_min_per_person (the
    exposure one person picked up walking it) and min_per_person.
    """
    if segment_exposure.empty:
        return gpd.GeoDataFrame(geometry=[], crs=CRS)

    df = segment_exposure.copy()
    df["a"] = np.minimum(df["u"], df["v"])
    df["b"] = np.maximum(df["u"], df["v"])
    has_persons = "n_persons" in df.columns and df["n_persons"].notna().all()
    sums = {"heat_degC_min": ("heat_degC_min", "sum"), "person_min": ("person_min", "sum")}
    if has_persons:
        sums["n_persons"] = ("n_persons", "sum")
    agg = df.groupby(["a", "b", "key"], as_index=False).agg(**sums, u=("u", "first"), v=("v", "first"))

    rows, geoms = [], []
    for r in agg.itertuples(index=False):
        u, v, k = int(r.u), int(r.v), int(r.key)
        data = G[u][v][k] if G.has_edge(u, v, k) else {}
        geom = data.get("geometry")
        if geom is None:
            geom = LineString([(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])])
        length = float(data.get("length", geom.length * 111_320.0))
        rows.append({
            "u": u, "v": v, "key": k,
            "name": _attr_str(data.get("name")),
            "highway": _attr_str(data.get("highway")),
            "edge_type": _attr_str(data.get("edge_type")) or "street",
            "length_m": length,
            "heat_degC_min": r.heat_degC_min,
            "person_min": r.person_min,
            **({"n_persons": int(r.n_persons)} if has_persons else {}),
        })
        geoms.append(geom)

    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)
    gdf["mean_heat_degC"] = gdf["heat_degC_min"] / gdf["person_min"]
    gdf["heat_degC_min_per_100m"] = gdf["heat_degC_min"] / gdf["length_m"].clip(lower=1.0) * 100.0
    if has_persons:
        _add_per_person(gdf)
    return gdf.sort_values("heat_degC_min").reset_index(drop=True)


def _add_per_person(gdf: gpd.GeoDataFrame) -> None:
    n = gdf["n_persons"].where(gdf["n_persons"] > 0)
    gdf["heat_degC_min_per_person"] = gdf["heat_degC_min"] / n
    gdf["min_per_person"] = gdf["person_min"] / n


def stop_layer(G: nx.MultiDiGraph, stop_exposure: pd.DataFrame) -> gpd.GeoDataFrame:
    """One point per transit stop where agents waited to board, with the heat they took
    on waiting (and per waiting person, when stop_exposure has n_persons)."""
    if stop_exposure.empty:
        return gpd.GeoDataFrame(geometry=[], crs=CRS)
    has_persons = "n_persons" in stop_exposure.columns and stop_exposure["n_persons"].notna().all()
    rows, geoms = [], []
    for r in stop_exposure.itertuples(index=False):
        n = int(r.node)
        data = G.nodes[n]
        rows.append({
            "node": n,
            "stop_name": _attr_str(data.get("stop_name") or data.get("name")),
            "heat_degC_min": r.heat_degC_min,
            "person_min": r.person_min,
            **({"n_persons": int(r.n_persons)} if has_persons else {}),
        })
        geoms.append(Point(data["x"], data["y"]))
    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)
    gdf["mean_heat_degC"] = gdf["heat_degC_min"] / gdf["person_min"]
    if has_persons:
        _add_per_person(gdf)
    return gdf.sort_values("heat_degC_min").reset_index(drop=True)


def quantile_breaks(values: pd.Series, n_classes: int = 7) -> list[float]:
    """Class edges at quantiles of `values`, de-duplicated (so heavily tied data gets
    fewer classes); always at least two edges, i.e. one class, if there is any data."""
    if values.empty:
        return []
    qs = np.quantile(values.to_numpy(dtype=float), np.linspace(0, 1, n_classes + 1))
    breaks = sorted(set(np.round(qs, 1).tolist()))
    return breaks if len(breaks) >= 2 else [breaks[0], breaks[0]]


def _fmt(x: float) -> str:
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.1f}"


def graduated_qml(
    attr: str,
    breaks: list[float],
    geometry: str,
    colors: list[str] = _YLORRD,
    widths_mm: tuple[float, float] = (0.25, 1.6),
    sizes_mm: tuple[float, float] = (1.2, 4.0),
    unit_label: str = "°C·min",
) -> str:
    """
    QGIS (3.26+) layer style: graduated colour on `attr` with the given class `breaks`,
    lines getting wider / points getting bigger with each class, and symbol levels so
    hotter features draw on top of cooler ones.
    """
    n = len(breaks) - 1
    pick = np.linspace(0, len(colors) - 1, n).round().astype(int)
    ranges, symbols = [], []
    for i in range(n):
        lo, hi = breaks[i], breaks[i + 1]
        r, g, b = (int(colors[pick[i]][j:j + 2], 16) for j in (1, 3, 5))
        frac = i / max(n - 1, 1)
        label = f"{_fmt(lo)} – {_fmt(hi)} {unit_label}"
        ranges.append(
            f'<range lower="{lo}" upper="{hi}" symbol="{i}" label={quoteattr(label)} render="true"/>'
        )
        if geometry == "line":
            width = widths_mm[0] + frac * (widths_mm[1] - widths_mm[0])
            layer = (
                f'<layer class="SimpleLine" pass="{i}" locked="0" enabled="1"><Option type="Map">'
                f'<Option name="line_color" type="QString" value="{r},{g},{b},255"/>'
                f'<Option name="line_width" type="QString" value="{width:.2f}"/>'
                f'<Option name="line_width_unit" type="QString" value="MM"/>'
                f'<Option name="line_style" type="QString" value="solid"/>'
                f'<Option name="capstyle" type="QString" value="round"/>'
                f'<Option name="joinstyle" type="QString" value="round"/>'
                f'</Option></layer>'
            )
        elif geometry == "polygon":
            layer = (
                f'<layer class="SimpleFill" pass="{i}" locked="0" enabled="1"><Option type="Map">'
                f'<Option name="color" type="QString" value="{r},{g},{b},210"/>'
                f'<Option name="style" type="QString" value="solid"/>'
                f'<Option name="outline_color" type="QString" value="90,90,90,255"/>'
                f'<Option name="outline_width" type="QString" value="0.2"/>'
                f'<Option name="outline_width_unit" type="QString" value="MM"/>'
                f'<Option name="outline_style" type="QString" value="solid"/>'
                f'</Option></layer>'
            )
        else:
            size = sizes_mm[0] + frac * (sizes_mm[1] - sizes_mm[0])
            layer = (
                f'<layer class="SimpleMarker" pass="{i}" locked="0" enabled="1"><Option type="Map">'
                f'<Option name="name" type="QString" value="circle"/>'
                f'<Option name="color" type="QString" value="{r},{g},{b},255"/>'
                f'<Option name="outline_color" type="QString" value="35,35,35,255"/>'
                f'<Option name="outline_width" type="QString" value="0.2"/>'
                f'<Option name="outline_width_unit" type="QString" value="MM"/>'
                f'<Option name="size" type="QString" value="{size:.2f}"/>'
                f'<Option name="size_unit" type="QString" value="MM"/>'
                f'</Option></layer>'
            )
        symbol_type = {"line": "line", "polygon": "fill"}.get(geometry, "marker")
        symbols.append(
            f'<symbol type="{symbol_type}" name="{i}" alpha="1" '
            f'clip_to_extent="1" force_rhr="0">{layer}</symbol>'
        )
    return (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        '<qgis version="3.30.0" styleCategories="Symbology">'
        f'<renderer-v2 type="graduatedSymbol" attr="{attr}" graduatedMethod="GraduatedColor" '
        'symbollevels="1" enableorderby="0" forceraster="0" referencescale="-1">'
        f'<ranges>{"".join(ranges)}</ranges>'
        f'<symbols>{"".join(symbols)}</symbols>'
        '</renderer-v2></qgis>'
    )


def _embed_default_styles(gpkg_path: Path, styles: dict[str, tuple[str, str]]) -> None:
    """Store QML styles in the GeoPackage's `layer_styles` table (the table QGIS itself
    uses), flagged useAsDefault so QGIS applies them when the layers are opened."""
    con = sqlite3.connect(gpkg_path)
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS layer_styles (
                id INTEGER PRIMARY KEY AUTOINCREMENT, f_table_catalog TEXT(256),
                f_table_schema TEXT(256), f_table_name TEXT(256), f_geometry_column TEXT(256),
                styleName TEXT(30), styleQML TEXT, styleSLD TEXT, useAsDefault BOOLEAN,
                description TEXT, owner TEXT(30), ui TEXT(30),
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP)"""
        )
        con.execute(
            "INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier) "
            "VALUES ('layer_styles', 'attributes', 'layer_styles')"
        )
        geom_cols = dict(con.execute("SELECT table_name, column_name FROM gpkg_geometry_columns"))
        for layer, (attr, qml) in styles.items():
            con.execute("DELETE FROM layer_styles WHERE f_table_name = ?", (layer,))
            con.execute(
                "INSERT INTO layer_styles (f_table_catalog, f_table_schema, f_table_name, "
                "f_geometry_column, styleName, styleQML, styleSLD, useAsDefault, description, owner, "
                "update_time) VALUES ('', '', ?, ?, ?, ?, '', 1, ?, '', "
                "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",  # GeoPackage DATETIME format
                (layer, geom_cols.get(layer, "geom"), layer, qml,
                 f"Graduated by {attr} (nairobi_heat_abm)"),
            )
        con.commit()
    finally:
        con.close()


def write_exposure_gpkg(
    path: str | Path,
    layers: dict[str, gpd.GeoDataFrame],
    style_attrs: dict[str, str] | None = None,
    n_classes: int = 7,
) -> Path:
    """
    Write each non-empty GeoDataFrame in `layers` as a GeoPackage layer, overwriting
    `path`. Each layer gets an embedded default QGIS style — graduated colour by quantile
    classes of one column (wider lines / bigger circles / darker fills = more exposure) —
    on `style_attrs[layer]` if given, else on `heat_degC_min` if the layer has it.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    style_attrs = style_attrs or {}

    styles: dict[str, tuple[str, str]] = {}
    for name, gdf in layers.items():
        if gdf.empty:
            continue
        gdf.to_file(path, layer=name, driver="GPKG", VERSION=_GPKG_VERSION)
        attr = style_attrs.get(name, "heat_degC_min")
        if attr not in gdf.columns:
            continue
        geom_type = gdf.geom_type.iloc[0]
        kind = ("line" if "LineString" in geom_type else "point" if "Point" in geom_type
                else "polygon" if "Polygon" in geom_type else None)
        if kind is None:
            continue
        breaks = quantile_breaks(gdf[attr].dropna(), n_classes)
        if len(breaks) >= 2:
            unit = ("°C·min/person" if attr.endswith("_per_person") else "°C·min" if "degC_min" in attr
                    else "°C" if attr.endswith("degC") else "")
            # Per-person values are largely set by segment length; widening the hot classes
            # would let long segments swamp the map, so colour alone carries the value.
            widths = (0.35, 0.35) if attr.endswith("_per_person") else (0.25, 1.6)
            styles[name] = (attr, graduated_qml(attr, breaks, kind, widths_mm=widths, unit_label=unit))

    if styles:
        _embed_default_styles(path, styles)
    return path
