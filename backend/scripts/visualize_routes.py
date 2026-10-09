from pathlib import Path
import json

import folium
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from matplotlib import cm, colors


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

DISTRICT = "sxr"
CONSTRUCTION = "road"

ROUTE_DIR = ROOT / "outputs" / "routes" / DISTRICT
COST_DIR = ROOT / "outputs" / "cost_surfaces" / DISTRICT

ROUTE_FILE = ROUTE_DIR / f"routes_{CONSTRUCTION}.geojson"
ROUTE_JSON = ROUTE_DIR / f"routes_{CONSTRUCTION}.json"

COST_FILE = COST_DIR / f"soft_cost_{CONSTRUCTION}.tif"
HARD_FILE = COST_DIR / f"hard_constraints_{CONSTRUCTION}.tif"

OUTPUT_FILE = ROUTE_DIR / f"routes_{CONSTRUCTION}_map.html"


# ============================================================
# CHECK FILES
# ============================================================

for path in [ROUTE_FILE, ROUTE_JSON, COST_FILE, HARD_FILE]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file:\n{path}")


# ============================================================
# LOAD ROUTES
# ============================================================

with open(ROUTE_FILE, "r", encoding="utf-8") as f:
    routes_geojson = json.load(f)

with open(ROUTE_JSON, "r", encoding="utf-8") as f:
    routes_data = json.load(f)


# ============================================================
# LOAD RASTER
# ============================================================

print("Loading environmental cost raster...")

with rasterio.open(COST_FILE) as src:

    # Downsample for browser visualization.
    # The actual raster remains at full resolution.
    max_dimension = 1200

    scale = max(src.width, src.height) / max_dimension

    if scale > 1:
        out_width = int(src.width / scale)
        out_height = int(src.height / scale)
    else:
        out_width = src.width
        out_height = src.height

    cost = src.read(
        1,
        out_shape=(out_height, out_width),
        resampling=Resampling.bilinear
    )

    cost_bounds = transform_bounds(
        src.crs,
        "EPSG:4326",
        *src.bounds
    )

    cost_nodata = src.nodata

print(f"Cost raster shape: {cost.shape}")


# ============================================================
# MASK NODATA
# ============================================================

cost = cost.astype(float)

if cost_nodata is not None:
    cost[cost == cost_nodata] = np.nan

cost[~np.isfinite(cost)] = np.nan


# ============================================================
# CLIP EXTREME VALUES
# ============================================================

valid = cost[np.isfinite(cost)]

if len(valid) == 0:
    raise ValueError("Environmental cost raster contains no valid pixels.")

low = np.percentile(valid, 1)
high = np.percentile(valid, 99)

print(f"Cost visualization range: {low:.2f} → {high:.2f}")

norm = colors.Normalize(
    vmin=low,
    vmax=high,
    clip=True
)


# ============================================================
# CREATE COST IMAGE
# ============================================================

# Yellow → orange → red
cmap = cm.get_cmap("RdYlGn_r")

rgba = cmap(norm(np.nan_to_num(cost, nan=low)))

# Make nodata transparent
rgba[..., 3] = np.where(
    np.isfinite(cost),
    0.55,
    0
)

cost_image = (rgba * 255).astype(np.uint8)


# ============================================================
# LOAD HARD CONSTRAINTS
# ============================================================

print("Loading hard constraint raster...")

with rasterio.open(HARD_FILE) as src:

    hard = src.read(
        1,
        out_shape=(out_height, out_width),
        resampling=Resampling.nearest
    )

    hard_bounds = transform_bounds(
        src.crs,
        "EPSG:4326",
        *src.bounds
    )

# 1 = forbidden
# 0 = allowed
# 255 = nodata

hard_mask = np.zeros(
    (*hard.shape, 4),
    dtype=np.uint8
)

forbidden = hard == 1

# Semi-transparent red for forbidden areas
hard_mask[forbidden] = [255, 0, 0, 100]

# Everything else transparent
hard_mask[~forbidden] = [0, 0, 0, 0]


# ============================================================
# FIND ROUTE CENTER
# ============================================================

all_coords = []

for feature in routes_geojson["features"]:

    geometry = feature["geometry"]

    if geometry["type"] == "LineString":
        all_coords.extend(geometry["coordinates"])

    elif geometry["type"] == "MultiLineString":
        for line in geometry["coordinates"]:
            all_coords.extend(line)


if not all_coords:
    raise ValueError("No route coordinates found.")


lons = [c[0] for c in all_coords]
lats = [c[1] for c in all_coords]

center = [
    (min(lats) + max(lats)) / 2,
    (min(lons) + max(lons)) / 2
]


# ============================================================
# CREATE MAP
# ============================================================

m = folium.Map(
    location=center,
    zoom_start=14,
    tiles=None,
    control_scale=True
)


# ============================================================
# BASEMAPS
# ============================================================

folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/"
        "ArcGIS/rest/services/World_Imagery/"
        "MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri World Imagery",
    name="Satellite",
    overlay=False,
    control=True
).add_to(m)


folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/"
        "ArcGIS/rest/services/World_Street_Map/"
        "MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri World Street Map",
    name="Street Map",
    overlay=False,
    control=True
).add_to(m)


# ============================================================
# ENVIRONMENTAL COST HEATMAP
# ============================================================

folium.raster_layers.ImageOverlay(
    image=cost_image,
    bounds=[
        [cost_bounds[1], cost_bounds[0]],
        [cost_bounds[3], cost_bounds[2]]
    ],
    opacity=0.55,
    interactive=True,
    cross_origin=False,
    zindex=2,
    name="Environmental Cost"
).add_to(m)


# ============================================================
# HARD CONSTRAINTS
# ============================================================

folium.raster_layers.ImageOverlay(
    image=hard_mask,
    bounds=[
        [hard_bounds[1], hard_bounds[0]],
        [hard_bounds[3], hard_bounds[2]]
    ],
    opacity=0.7,
    interactive=True,
    cross_origin=False,
    zindex=3,
    name="Hard Constraints"
).add_to(m)


# ============================================================
# ROUTE COLORS
# ============================================================

route_styles = {
    "A": {
        "color": "#17275f",
        "name": "Route A — Shortest"
    },
    "B": {
        "color": "#00897b",
        "name": "Route B — Balanced"
    },
    "C": {
        "color": "#f57c00",
        "name": "Route C — Lower Environmental Cost"
    }
}


# ============================================================
# DRAW ROUTES
# ============================================================

for feature in routes_geojson["features"]:

    props = feature.get("properties", {})
    route_id = str(props.get("route", ""))

    # Handle possible naming formats
    if route_id.startswith("Route "):
        route_id = route_id.replace("Route ", "").strip()[0]

    if route_id not in route_styles:
        continue

    style = route_styles[route_id]

    distance = props.get("distance_km", "N/A")
    env_cost = props.get("environmental_cost", "N/A")
    solver_cost = props.get("solver_cost", "N/A")

    popup_html = f"""
    <div style="font-family: Arial; width: 230px;">

        <h4 style="margin-bottom:8px;">
            {style["name"]}
        </h4>

        <b>Distance:</b>
        {distance} km
        <br><br>

        <b>Environmental Cost:</b>
        {env_cost}
        <br><br>

        <b>Solver Cost:</b>
        {solver_cost}

    </div>
    """

    folium.GeoJson(
        feature,
        name=style["name"],
        style_function=lambda x, color=style["color"]: {
            "color": color,
            "weight": 6,
            "opacity": 0.95
        },
        highlight_function=lambda x, color=style["color"]: {
            "color": color,
            "weight": 10,
            "opacity": 1
        },
        tooltip=style["name"],
        popup=folium.Popup(
            popup_html,
            max_width=300
        )
    ).add_to(m)


# ============================================================
# START / END MARKERS
# ============================================================

first_feature = routes_geojson["features"][0]

coords = first_feature["geometry"]["coordinates"]

start_lon, start_lat = coords[0]
end_lon, end_lat = coords[-1]


folium.Marker(
    [start_lat, start_lon],
    tooltip="Start",
    popup="Route Start",
    icon=folium.Icon(
        color="green",
        icon="play"
    )
).add_to(m)


folium.Marker(
    [end_lat, end_lon],
    tooltip="End",
    popup="Route Destination",
    icon=folium.Icon(
        color="red",
        icon="flag"
    )
).add_to(m)


# ============================================================
# LEGEND
# ============================================================

legend_html = """
<div style="
    position: fixed;
    bottom: 30px;
    left: 30px;
    width: 260px;
    z-index: 9999;
    background: white;
    padding: 15px;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25);
    font-family: Arial;
">

<h4 style="margin-top:0;">
Route Analysis
</h4>

<div>
<span style="
display:inline-block;
width:25px;
height:5px;
background:#17275f;
margin-right:8px;
"></span>
Route A — Shortest
</div>

<br>

<div>
<span style="
display:inline-block;
width:25px;
height:5px;
background:#00897b;
margin-right:8px;
"></span>
Route B — Balanced
</div>

<br>

<div>
<span style="
display:inline-block;
width:25px;
height:5px;
background:#f57c00;
margin-right:8px;
"></span>
Route C — Lower Environmental
</div>

<br>

<div>
<span style="
display:inline-block;
width:20px;
height:20px;
background:rgba(255,0,0,0.5);
margin-right:8px;
vertical-align:middle;
"></span>
Hard Constraint
</div>

</div>
"""

m.get_root().html.add_child(
    folium.Element(legend_html)
)


# ============================================================
# LAYER CONTROL
# ============================================================

folium.LayerControl(
    collapsed=False
).add_to(m)


# ============================================================
# FIT MAP TO ROUTES
# ============================================================

m.fit_bounds([
    [min(lats), min(lons)],
    [max(lats), max(lons)]
])


# ============================================================
# SAVE
# ============================================================

m.save(OUTPUT_FILE)

print()
print("=" * 60)
print("MAP CREATED")
print("=" * 60)
print(f"Output: {OUTPUT_FILE}")
print()
print("Layers:")
print("  Satellite")
print("  Street Map")
print("  Environmental Cost")
print("  Hard Constraints")
print("  Route A")
print("  Route B")
print("  Route C")
print("=" * 60)