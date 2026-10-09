"""
Shuhul — Visual Validation v3
=============================

Fixes:
1. Raster ImageOverlay now receives a NumPy RGBA array, not a PIL Image.
   This fixes: "Object of type Image is not JSON serializable".
2. Mitigation layers are built as complete GeoJSON FeatureCollections,
   one layer per intervention type, instead of one GeoJson object per row.
   This makes the Tree/Bush/Roof toggles reliable.
3. Invalid/empty mitigation geometries are removed and reported.
4. Initial map fits only to the routes.
5. Adds route/mitigation bounds to the terminal so we can diagnose
   spatial problems immediately.
6. Adds a small "validation info" panel to the map.

Run from:
    C:\E\hubble\Projects\Tsaay\backend

    python scripts\visual_validate_mitigation.py --district sxr --construction road

Output:
    outputs\validation\sxr\mitigation_validation_road.html
"""

from pathlib import Path
import argparse
import warnings

import geopandas as gpd
import folium
from folium import GeoJson, LayerControl
from folium.raster_layers import ImageOverlay
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from shapely.geometry import mapping

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
TARGET_CRS = "EPSG:32643"


def find_raster(folder, keywords):
    folder = Path(folder)
    files = sorted(list(folder.rglob("*.tif")) + list(folder.rglob("*.tiff")))
    for f in files:
        name = f.name.lower()
        if any(k.lower() in name for k in keywords):
            return f
    return None


def print_raster_info(path, label):
    if not path:
        print(f"{label:<10}: NOT FOUND")
        return
    try:
        with rasterio.open(path) as src:
            print(
                f"{label:<10}: {path.name} | "
                f"CRS={src.crs} | shape={src.height}x{src.width} | "
                f"res={src.res}"
            )
    except Exception as e:
        print(f"{label:<10}: {path} | ERROR: {e}")


def load_gdf(path):
    gdf = gpd.read_file(path)

    if gdf.crs is None:
        # Route/mitigation GeoJSON is expected to be WGS84 if CRS is absent.
        gdf = gdf.set_crs("EPSG:4326")

    gdf = gdf.to_crs("EPSG:4326")

    # Remove empty / null geometries.
    before = len(gdf)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    removed = before - len(gdf)

    # Attempt to repair invalid polygons.
    if len(gdf):
        invalid = ~gdf.geometry.is_valid
        if invalid.any():
            gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].buffer(0)

    return gdf, removed


def route_label(value):
    s = str(value).lower()

    if "route a" in s or s.strip() == "a" or "shortest" in s:
        return "Route A — Shortest"

    if "route b" in s or s.strip() == "b" or "balanced" in s:
        return "Route B — Balanced"

    if "route c" in s or s.strip() == "c" or "environmental" in s:
        return "Route C — Lower Environmental Impact"

    return str(value)


def get_value(row, keys):
    for key in keys:
        if key in row.index and row[key] not in [None, ""]:
            return row[key]
    return None


def get_route_name(row, fallback):
    return str(
        get_value(row, ["route", "route_name", "name", "label", "id"])
        or fallback
    )


def raster_rgba(path, crop_bounds_utm, kind, max_dim=1400):
    """
    Return:
        rgba_numpy_array, leaflet_bounds

    ImageOverlay cannot serialize a PIL.Image directly in some Folium
    versions, so this deliberately returns a NumPy RGBA array.
    """

    with rasterio.open(path) as src:
        minx, miny, maxx, maxy = crop_bounds_utm
        rb = src.bounds

        minx = max(minx, rb.left)
        miny = max(miny, rb.bottom)
        maxx = min(maxx, rb.right)
        maxy = min(maxy, rb.top)

        if minx >= maxx or miny >= maxy:
            raise ValueError("Route crop does not overlap raster.")

        window = rasterio.windows.from_bounds(
            minx, miny, maxx, maxy, transform=src.transform
        )

        window = window.round_offsets().round_lengths()

        scale = max(window.width, window.height) / max_dim

        if scale > 1:
            out_w = max(1, int(window.width / scale))
            out_h = max(1, int(window.height / scale))
        else:
            out_w = max(1, int(window.width))
            out_h = max(1, int(window.height))

        if kind in ("water", "canopy"):
            resampling = Resampling.nearest
        else:
            resampling = Resampling.bilinear

        data = src.read(
            1,
            window=window,
            out_shape=(out_h, out_w),
            resampling=resampling,
        ).astype("float32")

        nodata = src.nodata

        valid = np.isfinite(data)

        if nodata is not None:
            valid &= data != nodata

        win_transform = src.window_transform(window)

        left, bottom, right, top = rasterio.transform.array_bounds(
            data.shape[0],
            data.shape[1],
            win_transform,
        )

        wb = transform_bounds(
            src.crs,
            "EPSG:4326",
            left,
            bottom,
            right,
            top,
            densify_pts=21,
        )

        leaflet_bounds = [
            [wb[1], wb[0]],
            [wb[3], wb[2]],
        ]

        rgba = np.zeros(
            (data.shape[0], data.shape[1], 4),
            dtype=np.uint8,
        )

        if kind == "ndvi":

            # NDVI -1 to +1:
            # low vegetation -> reddish
            # high vegetation -> greenish
            clipped = np.clip((data + 1.0) / 2.0, 0, 1)

            rgba[..., 0] = (255 * (1 - clipped)).astype(np.uint8)
            rgba[..., 1] = (200 * clipped).astype(np.uint8)
            rgba[..., 2] = (80 * (1 - clipped)).astype(np.uint8)

            rgba[..., 3] = np.where(
                valid,
                155,
                0,
            ).astype(np.uint8)

        elif kind == "ndwi":

            # NDWI visualization:
            # only NDWI >= 0.20 is shown.
            mask = (data >= 0.20) & valid

            rgba[..., 0] = 30
            rgba[..., 1] = 120
            rgba[..., 2] = 255

            rgba[..., 3] = np.where(
                mask,
                180,
                0,
            ).astype(np.uint8)

        elif kind == "water":

            # Binary water mask.
            mask = (data > 0) & valid

            rgba[..., 0] = 20
            rgba[..., 1] = 100
            rgba[..., 2] = 255

            rgba[..., 3] = np.where(
                mask,
                190,
                0,
            ).astype(np.uint8)

        elif kind == "canopy":

            # Current project interpretation:
            # canopy > 0 is displayed.
            mask = (data > 0) & valid

            rgba[..., 0] = 20
            rgba[..., 1] = 170
            rgba[..., 2] = 70

            rgba[..., 3] = np.where(
                mask,
                120,
                0,
            ).astype(np.uint8)

        elif kind == "slope":

            finite = data[valid]

            if finite.size:

                lo = np.percentile(finite, 2)
                hi = np.percentile(finite, 98)

                norm = np.clip(
                    (data - lo) / max(hi - lo, 1e-6),
                    0,
                    1,
                )

            else:
                norm = np.zeros_like(data)

            rgba[..., 0] = 255
            rgba[..., 1] = (180 * (1 - norm)).astype(np.uint8)
            rgba[..., 2] = 40

            alpha = 35 + 130 * norm

            rgba[..., 3] = np.where(
                valid,
                alpha,
                0,
            ).astype(np.uint8)

        else:

            finite = data[valid]

            if finite.size:

                lo = np.percentile(finite, 2)
                hi = np.percentile(finite, 98)

                norm = np.clip(
                    (data - lo) / max(hi - lo, 1e-6),
                    0,
                    1,
                )

            else:
                norm = np.zeros_like(data)

            rgba[..., 0] = (255 * norm).astype(np.uint8)
            rgba[..., 1] = (180 * (1 - norm)).astype(np.uint8)
            rgba[..., 2] = 60

            rgba[..., 3] = np.where(
                valid,
                110,
                0,
            ).astype(np.uint8)

        # IMPORTANT:
        # Return ndarray, NOT PIL.Image.
        return rgba, leaflet_bounds


def add_raster_layer(
    m,
    path,
    label,
    kind,
    crop_bounds_utm,
    opacity=0.65,
):
    if not path:

        print(
            f"  {label:<24} NOT FOUND"
        )

        return False

    try:

        image, bounds = raster_rgba(
            path,
            crop_bounds_utm,
            kind,
        )

        ImageOverlay(
            image=image,
            bounds=bounds,
            opacity=opacity,
            interactive=True,
            cross_origin=False,
            zindex=2,
            name=label,
        ).add_to(m)

        print(
            f"  {label:<24} LOADED ({path.name})"
        )

        return True

    except Exception as e:

        print(
            f"  {label:<24} FAILED: {type(e).__name__}: {e}"
        )

        return False


def add_feature_collection_layer(
    m,
    gdf,
    layer_name,
    color,
    popup_rows,
    show=True,
):
    """
    Add an entire intervention category as ONE FeatureCollection.

    This is much more reliable than adding dozens of individual
    GeoJson objects to a Folium FeatureGroup.
    """

    if gdf.empty:

        print(
            f"  {layer_name:<32} EMPTY"
        )

        return False

    features = []

    for idx, row in gdf.iterrows():

        geom = row.geometry

        if geom is None or geom.is_empty:
            continue

        properties = {}

        for key in row.index:

            if key == "geometry":
                continue

            value = row[key]

            # Convert NumPy scalar values to native Python.
            if isinstance(value, np.integer):
                value = int(value)

            elif isinstance(value, np.floating):
                value = float(value)

            elif isinstance(value, np.bool_):
                value = bool(value)

            # Avoid complex/unserializable values.
            try:
                import json
                json.dumps(value)
            except Exception:
                value = str(value)

            properties[key] = value

        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": properties,
            }
        )

    if not features:

        print(
            f"  {layer_name:<32} NO VALID GEOMETRIES"
        )

        return False

    fc = {
        "type": "FeatureCollection",
        "features": features,
    }

    def style_function(feature, c=color):

        return {
            "fillColor": c,
            "color": c,
            "weight": 3,
            "fillOpacity": 0.38,
        }

    def highlight_function(feature, c=color):

        return {
            "fillColor": c,
            "color": c,
            "weight": 5,
            "fillOpacity": 0.60,
        }

    layer = GeoJson(
        data=fc,
        name=layer_name,
        style_function=style_function,
        highlight_function=highlight_function,
        show=show,
    )

    # Construct a simple tooltip from whatever metadata exists.
    tooltip_fields = []

    for key in [
        "intervention_type",
        "candidate_type",
        "route",
        "route_name",
        "capacity_m2",
        "area_m2",
        "distance_m",
        "distance_to_construction_m",
        "search_radius_m",
        "road_width_m",
    ]:

        if key in gdf.columns:
            tooltip_fields.append(key)

    if tooltip_fields:

        aliases = [
            key.replace("_", " ").title()
            for key in tooltip_fields
        ]

        try:

            layer.add_child(
                folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    aliases=aliases,
                    localize=True,
                    sticky=True,
                    labels=True,
                )
            )

        except Exception:
            pass

    # Popup content for each feature.
    popup = folium.GeoJsonPopup(
        fields=tooltip_fields,
        aliases=[
            key.replace("_", " ").title()
            for key in tooltip_fields
        ],
        localize=True,
        labels=True,
        max_width=450,
    )

    layer.add_child(popup)

    layer.add_to(m)

    print(
        f"  {layer_name:<32} LOADED ({len(features)} zones)"
    )

    return True


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--district",
        required=True,
    )

    parser.add_argument(
        "--construction",
        default="road",
    )

    parser.add_argument(
        "--width-m",
        type=float,
        default=20.0,
        help="Project construction width in metres.",
    )

    args = parser.parse_args()

    district = args.district
    construction = args.construction
    width_m = float(args.width_m)
    if width_m <= 0:
        raise ValueError("--width-m must be greater than 0")

    routes_path = (
        ROOT
        / "outputs"
        / "routes"
        / district
        / f"routes_{construction}.geojson"
    )

    mitigation_path = (
        ROOT
        / "outputs"
        / "mitigation"
        / district
        / f"mitigation_{construction}.geojson"
    )

    processed_dir = (
        ROOT
        / "processed"
        / district
    )

    output_dir = (
        ROOT
        / "outputs"
        / "validation"
        / district
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_html = (
        output_dir
        / f"mitigation_validation_{construction}.html"
    )

    if not routes_path.exists():
        raise FileNotFoundError(
            f"Routes file not found:\n{routes_path}"
        )

    if not mitigation_path.exists():
        raise FileNotFoundError(
            f"Mitigation file not found:\n{mitigation_path}"
        )

    routes, route_removed = load_gdf(routes_path)

    mitigation, mitigation_removed = load_gdf(
        mitigation_path
    )

    # ------------------------------------------------------------------
    # Route geometry / initial map extent
    # ------------------------------------------------------------------

    route_utm = routes.to_crs(
        TARGET_CRS
    )

    route_bounds = route_utm.total_bounds

    minx, miny, maxx, maxy = route_bounds

    # 500m context around route.
    crop_bounds_utm = (
        minx - 500,
        miny - 500,
        maxx + 500,
        maxy + 500,
    )

    center_geom = (
        route_utm.geometry
        .unary_union
        .centroid
    )

    center_wgs = (
        gpd.GeoSeries(
            [center_geom],
            crs=TARGET_CRS,
        )
        .to_crs("EPSG:4326")
        .iloc[0]
    )

    # ------------------------------------------------------------------
    # Map
    # ------------------------------------------------------------------

    m = folium.Map(
        location=[
            center_wgs.y,
            center_wgs.x,
        ],
        zoom_start=14,
        control_scale=True,
        tiles=None,
        prefer_canvas=True,
    )

    # Basemaps.
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/"
            "ArcGIS/rest/services/"
            "World_Imagery/MapServer/"
            "tile/{z}/{y}/{x}"
        ),
        attr="Esri World Imagery",
        name="Satellite",
        overlay=False,
        control=True,
    ).add_to(m)

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap",
        overlay=False,
        control=True,
    ).add_to(m)

    # ------------------------------------------------------------------
    # Rasters
    # ------------------------------------------------------------------

    ndvi = find_raster(
        processed_dir,
        ["ndvi"],
    )

    ndwi = find_raster(
        processed_dir,
        ["ndwi"],
    )

    water = find_raster(
        processed_dir,
        ["water"],
    )

    canopy = find_raster(
        processed_dir,
        ["canopy", "chm"],
    )

    slope = find_raster(
        processed_dir,
        ["slope"],
    )

    print("=" * 78)
    print("SHUHUL — VISUAL VALIDATION v3")
    print("=" * 78)
    print(f"District:       {district}")
    print(f"Construction:   {construction}")
    print(f"Width:          {width_m:g} m")
    print(f"Processed dir:  {processed_dir}")
    print()

    print("INPUT GEOMETRY")
    print(
        f"Routes:          {len(routes)} "
        f"(removed empty: {route_removed})"
    )

    print(
        f"Mitigation:      {len(mitigation)} "
        f"(removed empty: {mitigation_removed})"
    )

    print()

    print("ROUTE BOUNDS (UTM 43N)")
    print(
        f"  xmin={route_bounds[0]:.2f}, "
        f"ymin={route_bounds[1]:.2f}, "
        f"xmax={route_bounds[2]:.2f}, "
        f"ymax={route_bounds[3]:.2f}"
    )

    print()

    print("MITIGATION BOUNDS (UTM 43N)")

    mb = (
        mitigation
        .to_crs(TARGET_CRS)
        .total_bounds
    )

    print(
        f"  xmin={mb[0]:.2f}, "
        f"ymin={mb[1]:.2f}, "
        f"xmax={mb[2]:.2f}, "
        f"ymax={mb[3]:.2f}"
    )

    print()

    print("RASTER DISCOVERY")

    print_raster_info(
        ndvi,
        "NDVI",
    )

    print_raster_info(
        ndwi,
        "NDWI",
    )

    print_raster_info(
        water,
        "WATER",
    )

    print_raster_info(
        canopy,
        "CANOPY",
    )

    print_raster_info(
        slope,
        "SLOPE",
    )

    print()

    print("RASTER OVERLAYS")

    add_raster_layer(
        m,
        ndvi,
        "NDVI",
        "ndvi",
        crop_bounds_utm,
        opacity=0.65,
    )

    add_raster_layer(
        m,
        ndwi,
        "NDWI ≥ 0.20",
        "ndwi",
        crop_bounds_utm,
        opacity=0.70,
    )

    add_raster_layer(
        m,
        water,
        "Water mask",
        "water",
        crop_bounds_utm,
        opacity=0.75,
    )

    add_raster_layer(
        m,
        canopy,
        "Canopy / CHM > 0",
        "canopy",
        crop_bounds_utm,
        opacity=0.55,
    )

    add_raster_layer(
        m,
        slope,
        "Slope",
        "slope",
        crop_bounds_utm,
        opacity=0.45,
    )

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    route_group = folium.FeatureGroup(
        name="Routes A / B / C",
        show=True,
    )

    route_group.add_to(m)

    route_colors = {
        "a": "#ff3333",
        "b": "#ffd21f",
        "c": "#00d084",
    }

    for idx, row in routes.iterrows():

        raw = get_route_name(
            row,
            f"Route {idx + 1}",
        )

        label = route_label(raw)

        low = raw.lower()

        if "shortest" in low or "route a" in low:
            key = "a"

        elif "balanced" in low or "route b" in low:
            key = "b"

        elif (
            "environmental" in low
            or "route c" in low
        ):
            key = "c"

        else:
            key = "a"

        color = route_colors[key]

        popup = [
            f"<b>{label}</b>"
        ]

        for field in [
            "length_km",
            "distance_km",
            "environmental_cost",
            "environmental_cost_index",
            "mean_environmental_cost",
        ]:

            if (
                field in row.index
                and row[field] not in [None, ""]
            ):

                try:

                    popup.append(
                        f"{field.replace('_', ' ').title()}: "
                        f"{float(row[field]):,.3f}"
                    )

                except Exception:
                    pass

        GeoJson(
            data=mapping(row.geometry),

            style_function=lambda feature, c=color: {
                "color": c,
                "weight": 7,
                "opacity": 0.95,
            },

            highlight_function=lambda feature: {
                "weight": 11,
                "opacity": 1,
            },

            tooltip=label,

            popup=folium.Popup(
                "<br>".join(popup),
                max_width=350,
            ),
        ).add_to(route_group)

    # ------------------------------------------------------------------
    # Construction corridor
    # ------------------------------------------------------------------

    corridor_group = folium.FeatureGroup(
        name=f"{width_m:g} m Construction Corridors",
        show=False,
    )

    corridor_group.add_to(m)

    corridor_wgs = (
        route_utm.geometry
        .buffer(width_m / 2.0)
        .to_crs("EPSG:4326")
    )

    for geom in corridor_wgs:

        GeoJson(
            data=mapping(geom),

            style_function=lambda feature: {
                "fillColor": "#ff6600",
                "color": "#ff6600",
                "weight": 1,
                "fillOpacity": 0.18,
            },
        ).add_to(corridor_group)

    # ------------------------------------------------------------------
    # Mitigation categories
    # ------------------------------------------------------------------

    def intervention_type(row):

        value = get_value(
            row,
            [
                "intervention_type",
                "candidate_type",
                "type",
                "category",
                "intervention",
            ],
        )

        return str(value or "").lower()

    types = mitigation.apply(
        intervention_type,
        axis=1,
    )

    tree_gdf = mitigation[
        types.str.contains("tree", na=False)
    ].copy()

    bush_gdf = mitigation[
        types.str.contains(
            "bush|shrub",
            regex=True,
            na=False,
        )
    ].copy()

    roof_gdf = mitigation[
        types.str.contains(
            "roof",
            na=False,
        )
    ].copy()

    other_gdf = mitigation[
        ~types.str.contains(
            "tree|bush|shrub|roof",
            regex=True,
            na=False,
        )
    ].copy()

    print()
    print("MITIGATION CATEGORY COUNTS")
    print(
        f"  Tree restoration:       {len(tree_gdf)}"
    )
    print(
        f"  Bush restoration:       {len(bush_gdf)}"
    )
    print(
        f"  Green roof:             {len(roof_gdf)}"
    )
    print(
        f"  Other:                  {len(other_gdf)}"
    )

    print()

    add_feature_collection_layer(
        m,
        tree_gdf,
        "Tree Restoration Zones",
        "#1b7f3a",
        {},
        show=True,
    )

    add_feature_collection_layer(
        m,
        bush_gdf,
        "Bush / Shrub Restoration Zones",
        "#8bc34a",
        {},
        show=True,
    )

    add_feature_collection_layer(
        m,
        roof_gdf,
        "Green Roof Candidates",
        "#9c27b0",
        {},
        show=True,
    )

    add_feature_collection_layer(
        m,
        other_gdf,
        "Other Mitigation Candidates",
        "#607d8b",
        {},
        show=True,
    )

    # ------------------------------------------------------------------
    # Initial extent = routes ONLY
    # ------------------------------------------------------------------

    route_wgs = routes.to_crs(
        "EPSG:4326"
    )

    rb = route_wgs.total_bounds

    m.fit_bounds(
        [
            [rb[1], rb[0]],
            [rb[3], rb[2]],
        ],
        padding=(25, 25),
    )

    LayerControl(
        collapsed=False,
    ).add_to(m)

    # ------------------------------------------------------------------
    # Information panel
    # ------------------------------------------------------------------

    title = f"""
    <div style="
        position: fixed;
        top: 10px;
        left: 55px;
        z-index: 9999;
        background: rgba(255,255,255,.95);
        padding: 10px 14px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,.25);
        font-family: Arial;
        font-size: 13px;
        line-height: 1.45;
        max-width: 430px;
    ">
      <b>Shuhul — Mitigation Visual Validation v3</b><br>
      {district.upper()} · {construction}<br>
      <span style="color:#ff3333">●</span> Route A
      &nbsp;
      <span style="color:#ffd21f">●</span> Route B
      &nbsp;
      <span style="color:#00a86b">●</span> Route C<br>
      Initial extent is based only on the routes.
      Toggle mitigation layers after loading.
    </div>
    """

    m.get_root().html.add_child(
        folium.Element(title)
    )

    m.save(output_html)

    print()
    print("=" * 78)
    print("HTML CREATED")
    print("=" * 78)
    print(output_html)
    print("=" * 78)


if __name__ == "__main__":
    main()