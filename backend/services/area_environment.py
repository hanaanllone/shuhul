"""
Shuhul area environment.

What the map layers say about one area: a whole district, or a shape
drawn inside it. Heat, tree canopy, buildings, land cover, flood and
water history, and how vegetation, built-up cover and surface
temperature have moved year by year.

    POST /api/area/environment   {"district": "sxr", "geometry": <GeoJSON, optional>}
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask
from shapely.geometry import shape

from ..config import PROCESSED_ROOT, PROJECT_ROOT

LANDCOVER_NAMES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare or sparse",
    70: "Snow and ice",
    80: "Water",
    90: "Wetland",
    100: "Moss and lichen",
}

FLOOD_CLASSES = [("Low", 0.45), ("Moderate", 0.65), ("High", 0.85), ("Very high", float("inf"))]

# Yearly layers, and how each is summarised over an area.
YEARLY = {
    "ndvi": "Vegetation index",
    "ndbi": "Built-up index",
    "lst_rel": "Temperature against the valley floor, °C",
}


class AreaError(Exception):
    """The area could not be read: unknown district or a shape outside it."""


def _district_shape(district, crs):
    path = Path(PROJECT_ROOT) / "districts-geojson" / f"{district}.geojson"
    if not path.exists():
        raise AreaError(f"Unknown district: {district}")

    frame = gpd.read_file(path)
    if frame.crs is None:
        frame = frame.set_crs("EPSG:4326")
    return frame.to_crs(crs).geometry.union_all()


def _area_shape(district, geometry, crs):
    """The area to summarise, in the district CRS."""
    if not geometry:
        return _district_shape(district, crs)

    if geometry.get("type") == "Feature":
        geometry = geometry.get("geometry")

    drawn = gpd.GeoSeries([shape(geometry)], crs="EPSG:4326").to_crs(crs).iloc[0]
    if drawn.is_empty or drawn.area <= 0:
        raise AreaError("The drawn area is empty.")
    return drawn


def _values(path, area):
    """Cells of a raster inside the area, without no-data, and the cell area in m²."""
    if not path.exists():
        return None, 0.0

    with rasterio.open(path) as src:
        try:
            data, _ = mask(src, [area], crop=True, filled=False)
        except ValueError:
            return None, 0.0

        values = data[0].compressed().astype("float32")
        values = values[np.isfinite(values)]
        return values, abs(src.transform.a * src.transform.e)


def _yearly_folder(district, area):
    """
    The folder of yearly composites that covers the area. A district
    nested inside another reads the larger district's composites.
    """
    candidates = [Path(PROCESSED_ROOT) / district] + sorted(Path(PROCESSED_ROOT).glob("*"))

    for folder in candidates:
        probe = folder / "yearly" / "lst_current.tif"
        if not probe.exists():
            continue
        with rasterio.open(probe) as src:
            left, bottom, right, top = src.bounds
            minx, miny, maxx, maxy = area.bounds
            if left <= minx and bottom <= miny and right >= maxx and top >= maxy:
                return folder / "yearly"
    return None


def _round(value, digits=2):
    return None if value is None or not np.isfinite(value) else round(float(value), digits)


def summarise(district, geometry=None):
    folder = Path(PROCESSED_ROOT) / district
    master = folder / "ndvi.tif"
    if not master.exists():
        raise AreaError(f"No data for district: {district}")

    with rasterio.open(master) as src:
        crs = src.crs

    area = _area_shape(district, geometry, crs)
    reference, cell_m2 = _values(master, area)

    if reference is None or reference.size == 0:
        raise AreaError("The area is outside this district's data.")

    area_m2 = float(reference.size) * cell_m2
    result = {
        "district": district,
        "scope": "drawn area" if geometry else "district",
        "area_km2": round(area_m2 / 1e6, 2),
        "vegetation": {"mean_ndvi": _round(reference.mean(), 3)},
    }

    # ---------- Heat ----------
    lst, _ = _values(folder / "lst.tif", area)
    if lst is not None and lst.size:
        result["heat"] = {
            "mean_lst_c": _round(lst.mean(), 1),
            "p90_lst_c": _round(np.percentile(lst, 90), 1),
            "max_lst_c": _round(lst.max(), 1),
            "note": "Mid-morning summer surface temperature, latest three years. Not air temperature.",
        }

    sensitivity, _ = _values(folder / "heat_sensitivity.tif", area)
    if sensitivity is not None and sensitivity.size:
        result.setdefault("heat", {})["mean_warming_if_paved_c"] = _round(sensitivity.mean(), 2)

    # ---------- Trees and buildings ----------
    trees, tree_cell = _values(folder / "tree_height.tif", area)
    if trees is not None and trees.size:
        canopy = trees > 0
        result["trees"] = {
            "canopy_pct": _round(100 * canopy.mean(), 1),
            "canopy_km2": _round(canopy.sum() * tree_cell / 1e6, 2),
            "mean_height_m": _round(trees[canopy].mean(), 1) if canopy.any() else None,
        }

    roofs, _ = _values(folder / "buildings.tif", area)
    if roofs is not None and roofs.size:
        result["buildings"] = {
            "roof_cover_pct": _round(100 * roofs.mean(), 1),
            "note": "Share of the area under a detected roof.",
        }

    # ---------- Land cover ----------
    cover, _ = _values(folder / "landcover.tif", area)
    if cover is not None and cover.size:
        codes, counts = np.unique(cover.astype("int32"), return_counts=True)
        shares = sorted(
            (
                {"name": LANDCOVER_NAMES.get(int(code), str(code)), "pct": round(100 * count / cover.size, 1)}
                for code, count in zip(codes, counts)
                if code != 0
            ),
            key=lambda item: -item["pct"],
        )
        result["landcover"] = [item for item in shares if item["pct"] >= 0.5]

    # ---------- Water and flood ----------
    flood, flood_cell = _values(folder / "flood.tif", area)
    if flood is not None and flood.size:
        classes = []
        lower = -float("inf")
        for name, upper in FLOOD_CLASSES:
            classes.append({
                "name": name,
                "pct": round(100 * float(((flood >= lower) & (flood < upper)).mean()), 1),
            })
            lower = upper

        result["flood"] = {
            "classes": classes,
            "flood_prone_pct": round(classes[2]["pct"] + classes[3]["pct"], 1),
            "note": "Screening index. Flood-prone means the high and very high classes.",
        }

    lost, lost_cell = _values(folder / "water_lost.tif", area)
    occurrence, occurrence_cell = _values(folder / "water_occurrence.tif", area)
    if lost is not None and occurrence is not None:
        result["water"] = {
            "recorded_water_km2": _round((occurrence > 0).sum() * occurrence_cell / 1e6, 2),
            "lost_water_km2": _round((lost > 0).sum() * lost_cell / 1e6, 2),
            "note": "Recorded since 1984. Lost water is water that has become land.",
        }

    # ---------- Change over time ----------
    yearly = _yearly_folder(district, area)
    if yearly is not None:
        years = sorted(int(path.stem.split("_")[1]) for path in yearly.glob("ndvi_*.tif"))
        series = []

        for year in years:
            row = {"year": year}
            for key in YEARLY:
                values, _ = _values(yearly / f"{key}_{year}.tif", area)
                row[key] = _round(values.mean(), 3) if values is not None and values.size else None

            looks, _ = _values(yearly / f"looks_{year}.tif", area)
            row["clear_looks"] = _round(looks.mean(), 1) if looks is not None and looks.size else None
            series.append(row)

        result["change"] = {
            "years": series,
            "labels": YEARLY,
            "note": (
                "Each year is one summer composite at 30 m. A year built from few clear looks "
                "is less reliable; the count is shown with it."
            ),
        }

    return result


def register_area_routes(app):
    """Register POST /api/area/environment."""
    from flask import jsonify, request

    @app.post("/api/area/environment")
    def area_environment():
        payload = request.get_json(silent=True) or {}
        district = str(payload.get("district", "")).strip()

        if not district:
            return jsonify({"error": "District is required."}), 400

        try:
            return jsonify(summarise(district, payload.get("geometry")))
        except AreaError as exc:
            return jsonify({"error": str(exc)}), 400
