"""
Shuhul layer registry.

One description of every map layer: where its file lives, what it
measures, how it is drawn, where it came from and how far to trust it.
The tile builder, the map API, area analysis and the "how was this
calculated" panels all read from here, so a layer is added once.

Files are relative to processed/<district>/. A layer that has no file
for a district is simply not offered for that district.
"""

from pathlib import Path

try:
    from ..config import PROCESSED_ROOT
except ImportError:
    from config import PROCESSED_ROOT


# Single-hue ramps, light to dark, one per kind of quantity.
GREENS = ["#edf5e4", "#c3dfa4", "#8dc063", "#4f9a35", "#1f6b23"]
ORANGES = ["#fff3e3", "#fdd4a3", "#fb9d4f", "#e2600f", "#93330a"]
BLUES = ["#e4f0fa", "#a9cdea", "#5f9fd6", "#2a6fb3", "#0e3f78"]
PURPLES = ["#efedf7", "#c9c5e3", "#9a93cb", "#6a5aae", "#42317d"]
BROWNS = ["#f5eee4", "#dcc5a3", "#b89464", "#8a6234", "#55381a"]

# ESA WorldCover's own legend, which is what readers of land-cover maps expect.
LANDCOVER_CLASSES = {
    10: ("Tree cover", "#006400"),
    20: ("Shrubland", "#ffbb22"),
    30: ("Grassland", "#ffff4c"),
    40: ("Cropland", "#f096ff"),
    50: ("Built-up", "#fa0000"),
    60: ("Bare or sparse", "#b4b4b4"),
    70: ("Snow and ice", "#f0f0f0"),
    80: ("Water", "#0064c8"),
    90: ("Wetland", "#0096a0"),
    100: ("Moss and lichen", "#fae6a0"),
}

FLOOD_CLASSES = [
    (0.45, "Low", None),
    (0.65, "Moderate", "#9ec9e8"),
    (0.85, "High", "#3d85c6"),
    (1.01, "Very high", "#0b3c7a"),
]

LANDSAT = "Landsat 8/9 Collection 2, June to August clear-sky median"
SENTINEL = "Sentinel-2 composite, May to July, 2017 to 2025"
WORLDCOVER = "ESA WorldCover 2021, 10 m"
JRC = "JRC Global Surface Water, 1984 to 2021, 30 m"

LAYERS = {
    "lst": {
        "title": "Surface temperature",
        "group": "Heat",
        "file": "lst.tif",
        "kind": "continuous",
        "unit": "°C",
        "palette": ORANGES,
        "stretch": "percentile",
        "source": LANDSAT + ", latest three years",
        "resolution_m": 30,
        "confidence": "Medium",
        "note": (
            "Mid-morning surface temperature from a 100 m thermal sensor delivered at 30 m. "
            "Not air temperature and not a daily maximum."
        ),
        "stress": "high",
    },
    "heat_sensitivity": {
        "title": "Warming if paved",
        "group": "Heat",
        "file": "heat_sensitivity.tif",
        "kind": "continuous",
        "unit": "°C",
        "palette": ORANGES,
        "domain": [0, 2],
        "hide_below": 0.1,
        "source": "Shuhul thermal model: estimated rise in surface temperature if a cell alone were paved",
        "resolution_m": 30,
        "confidence": "Low",
        "note": "A modelled estimate that shows which land is doing the most cooling. Not a measurement.",
    },
    "ndvi": {
        "title": "Vegetation",
        "group": "Vegetation",
        "file": "ndvi.tif",
        "kind": "continuous",
        "unit": "NDVI",
        "palette": GREENS,
        "domain": [0.1, 0.85],
        "source": SENTINEL,
        "resolution_m": 10,
        "confidence": "High",
        "note": "Greenness index. Does not tell trees from crops or grass.",
        "stress": "low",
    },
    "tree_height": {
        "title": "Tree canopy",
        "group": "Vegetation",
        "file": "tree_height.tif",
        "kind": "continuous",
        "unit": "m",
        "palette": GREENS,
        "domain": [5, 30],
        "hide_below": 0.5,
        "source": "Canopy height layer, kept only where " + WORLDCOVER + " also shows tree cover",
        "resolution_m": 10,
        "confidence": "Medium",
        "note": "Lone trees inside built-up cells are missed. Not a tree count.",
        "stress": "low",
    },
    "landcover": {
        "title": "Land cover",
        "group": "Built-up",
        "file": "landcover.tif",
        "kind": "classes",
        "classes": LANDCOVER_CLASSES,
        "source": WORLDCOVER,
        "resolution_m": 10,
        "confidence": "Medium",
        "note": "Orchards and tall gardens are often mapped as tree cover.",
    },
    "buildings": {
        "title": "Building cover",
        "group": "Built-up",
        "file": "buildings.tif",
        "kind": "continuous",
        "unit": "share of cell under a roof",
        "palette": PURPLES,
        "domain": [0, 1],
        "hide_below": 0.05,
        "source": "Microsoft machine-detected footprints plus named OpenStreetMap buildings",
        "resolution_m": 10,
        "confidence": "Medium",
        "note": "Detected footprints have no names or uses. Named buildings are a small subset.",
        "stress": "high",
    },
    "water": {
        "title": "Water",
        "group": "Water",
        "file": "water.tif",
        "kind": "mask",
        "color": "#2a78c8",
        "source": "Processed water layer",
        "resolution_m": 10,
        "confidence": "High",
    },
    "ndwi": {
        "title": "Water index",
        "group": "Water",
        "file": "ndwi.tif",
        "kind": "continuous",
        "unit": "NDWI",
        "palette": BLUES,
        "domain": [-0.7, 0.2],
        "source": SENTINEL,
        "resolution_m": 10,
        "confidence": "High",
        "note": (
            "Wetness index. High over open water and wet ground, low over dry land and "
            "buildings. Water under weed or algae reads lower than open water."
        ),
    },
    "water_occurrence": {
        "title": "Water history",
        "group": "Water",
        "file": "water_occurrence.tif",
        "kind": "continuous",
        "unit": "% of satellite looks with water",
        "palette": BLUES,
        "domain": [1, 100],
        "hide_below": 1,
        "source": JRC,
        "resolution_m": 30,
        "confidence": "Medium",
        "note": "Low values are land that was under water only occasionally, including past floods.",
    },
    "water_lost": {
        "title": "Lost water",
        "group": "Water",
        "file": "water_lost.tif",
        "kind": "mask",
        "color": "#b0256f",
        "source": JRC + ", transition classes",
        "resolution_m": 30,
        "confidence": "Medium",
        "note": "Permanent or seasonal water that has become land since 1984. Earlier losses are not visible.",
    },
    "flood": {
        "title": "Flood susceptibility",
        "group": "Water",
        "file": "flood.tif",
        "kind": "thresholds",
        "thresholds": FLOOD_CLASSES,
        "source": "Shuhul screening index from water history, low ground, height above water and flatness",
        "resolution_m": 10,
        "confidence": "Low",
        "note": (
            "Screening only. The elevation data is 30 m and too coarse to resolve "
            "embankments or drains, and no flood depth is modelled."
        ),
        "stress": "high",
    },
    "slope": {
        "title": "Slope",
        "group": "Terrain",
        "file": "slope.tif",
        "kind": "continuous",
        "unit": "degrees",
        "palette": BROWNS,
        "domain": [0, 35],
        "source": "Derived from the 30 m elevation model, resampled to 10 m",
        "resolution_m": 30,
        "confidence": "Medium",
    },
    "forest": {
        "title": "Hill forest",
        "group": "Vegetation",
        "file": "forest.tif",
        "kind": "mask",
        "color": "#14532d",
        "source": "Tree canopy 10 m or taller, in patches of 5 ha or more, on slopes averaging 8 degrees or more",
        "resolution_m": 10,
        "confidence": "Low",
        "note": "A satellite-derived stand-in for forest. Not a legal forest boundary.",
    },
    "heritage": {
        "title": "Heritage buffer",
        "group": "Built-up",
        "file": "heritage.tif",
        "kind": "mask",
        "color": "#7b2cbf",
        "source": "OpenStreetMap heritage points with a 100 m planning buffer",
        "resolution_m": 10,
        "confidence": "Low",
        "note": "Most points are not notified monuments. A planning buffer, not a legal boundary.",
    },
}


def layer_path(district, name):
    return Path(PROCESSED_ROOT) / district / LAYERS[name]["file"]


def available_layers(district):
    """Layer names that have a file for this district, in registry order."""
    return [name for name in LAYERS if layer_path(district, name).exists()]


def describe(name):
    """What a planner needs to know about a layer, for legends and method panels."""
    layer = LAYERS[name]
    return {
        key: layer[key]
        for key in ("title", "group", "kind", "unit", "source", "resolution_m", "confidence", "note")
        if key in layer
    }
