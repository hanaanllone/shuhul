from pathlib import Path

import numpy as np
import rasterio
import geopandas as gpd


# ============================================================
# CONFIG
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIR = ROOT / "processed"

DISTRICTS = [
    "ant",
    "bdg",
    "bnd",
    "gnd",
    "klgm",
    "kpwr",
    "plwoam",
    "shpyn",
    "sxr",
    "sr-c",
    "var",
]

RASTER_LAYERS = [
    "ndvi",
    "ndwi",
    "water",
    "dem",
    "slope",
    "canopy",
]

VECTOR_LAYERS = [
    "buildings",
    "heritage",
    "roads",
]

EXPECTED_CRS = "EPSG:32643"
EXPECTED_RESOLUTION = (10.0, 10.0)


# ============================================================
# FORMATTING
# ============================================================

def yes_no(value):
    return "✓" if value else "✗"


def fmt(value, decimals=3):

    if value is None:
        return "N/A"

    return f"{value:.{decimals}f}"


def bounds_tuple(bounds):
    return (
        bounds.left,
        bounds.bottom,
        bounds.right,
        bounds.top,
    )


def bounds_match(a, b, tolerance=0.1):

    return np.allclose(
        bounds_tuple(a),
        bounds_tuple(b),
        atol=tolerance
    )


# ============================================================
# RASTER INSPECTION
# ============================================================

def inspect_raster(path):

    result = {
        "exists": False,
        "readable": False,
        "crs": None,
        "width": None,
        "height": None,
        "resolution": None,
        "bounds": None,
        "valid_percent": None,
        "min": None,
        "max": None,
        "mean": None,
        "unique_count": None,
    }

    if not path.exists():
        return result

    result["exists"] = True

    try:

        with rasterio.open(path) as src:

            result["readable"] = True
            result["crs"] = src.crs
            result["width"] = src.width
            result["height"] = src.height
            result["resolution"] = src.res
            result["bounds"] = src.bounds

            data = src.read(1, masked=True)

            valid = data.compressed()

            total = data.size
            valid_count = len(valid)

            if total > 0:

                result["valid_percent"] = (
                    valid_count / total * 100
                )

            if valid_count > 0:

                result["min"] = float(np.min(valid))
                result["max"] = float(np.max(valid))
                result["mean"] = float(np.mean(valid))

                # Only calculate unique count for reasonably
                # sized categorical-ish datasets.
                if valid_count < 20_000_000:
                    result["unique_count"] = len(
                        np.unique(valid)
                    )

    except Exception as e:

        result["error"] = str(e)

    return result


# ============================================================
# VECTOR INSPECTION
# ============================================================

def inspect_vector(path):

    result = {
        "exists": False,
        "readable": False,
        "crs": None,
        "feature_count": None,
        "bounds": None,
        "geometry_types": [],
        "empty": None,
    }

    if not path.exists():
        return result

    result["exists"] = True

    try:

        gdf = gpd.read_file(path)

        result["readable"] = True
        result["crs"] = gdf.crs
        result["feature_count"] = len(gdf)
        result["empty"] = gdf.empty

        if not gdf.empty:

            result["bounds"] = gdf.total_bounds

            result["geometry_types"] = sorted(
                gdf.geometry.geom_type.dropna().unique().tolist()
            )

    except Exception as e:

        result["error"] = str(e)

    return result


# ============================================================
# DISTRICT VALIDATION
# ============================================================

def validate_district(district):

    district_dir = PROCESSED_DIR / district

    print()
    print("=" * 90)
    print(f"DISTRICT: {district.upper()}")
    print("=" * 90)

    if not district_dir.exists():

        print(f"❌ Directory does not exist: {district_dir}")

        return None

    raster_results = {}
    vector_results = {}

    # --------------------------------------------------------
    # RASTERS
    # --------------------------------------------------------

    print()
    print("RASTERS")
    print("-" * 90)

    for layer in RASTER_LAYERS:

        path = district_dir / f"{layer}.tif"

        result = inspect_raster(path)

        raster_results[layer] = result

        if not result["exists"]:

            print(
                f"❌ {layer:<10} "
                f"FILE NOT FOUND"
            )
            continue

        if not result["readable"]:

            print(
                f"❌ {layer:<10} "
                f"COULD NOT READ"
            )
            continue

        print(
            f"✓ {layer:<10} "
            f"{result['width']:>5} x "
            f"{result['height']:<5} | "
            f"{result['resolution'][0]:>5.1f}m | "
            f"{result['crs']} | "
            f"valid {result['valid_percent']:>6.2f}%"
        )

    # --------------------------------------------------------
    # VECTOR DATA
    # --------------------------------------------------------

    print()
    print("VECTORS")
    print("-" * 90)

    for layer in VECTOR_LAYERS:

        path = district_dir / f"{layer}.gpkg"

        result = inspect_vector(path)

        vector_results[layer] = result

        if not result["exists"]:

            print(
                f"❌ {layer:<10} "
                f"FILE NOT FOUND"
            )
            continue

        if not result["readable"]:

            print(
                f"❌ {layer:<10} "
                f"COULD NOT READ"
            )
            continue

        print(
            f"✓ {layer:<10} "
            f"features={result['feature_count']:<8} | "
            f"CRS={result['crs']} | "
            f"empty={result['empty']}"
        )

    # ========================================================
    # COMMON GRID CHECK
    # ========================================================

    print()
    print("RASTER GRID CONSISTENCY")
    print("-" * 90)

    valid_rasters = {
        name: result
        for name, result in raster_results.items()
        if result["readable"]
    }

    grid_ok = True

    if not valid_rasters:

        print("❌ No readable rasters.")
        grid_ok = False

    else:

        reference_name = "ndvi"

        if reference_name not in valid_rasters:

            reference_name = next(
                iter(valid_rasters)
            )

        reference = valid_rasters[reference_name]

        print(
            f"Reference: {reference_name} "
            f"({reference['width']} x "
            f"{reference['height']})"
        )

        for name, result in valid_rasters.items():

            crs_ok = (
                str(result["crs"]) == EXPECTED_CRS
            )

            resolution_ok = np.allclose(
                result["resolution"],
                EXPECTED_RESOLUTION,
                atol=0.001
            )

            dimensions_ok = (
                result["width"] == reference["width"]
                and
                result["height"] == reference["height"]
            )

            bounds_ok = bounds_match(
                result["bounds"],
                reference["bounds"]
            )

            layer_ok = (
                crs_ok
                and resolution_ok
                and dimensions_ok
                and bounds_ok
            )

            if not layer_ok:
                grid_ok = False

            print(
                f"{yes_no(layer_ok)} "
                f"{name:<10} "
                f"CRS={yes_no(crs_ok)} "
                f"RES={yes_no(resolution_ok)} "
                f"DIM={yes_no(dimensions_ok)} "
                f"BOUNDS={yes_no(bounds_ok)}"
            )

    # ========================================================
    # VECTOR CRS CHECK
    # ========================================================

    print()
    print("VECTOR CRS CHECK")
    print("-" * 90)

    vector_crs_ok = True

    for name, result in vector_results.items():

        if not result["readable"]:
            vector_crs_ok = False

            print(
                f"❌ {name:<10} unavailable"
            )

            continue

        crs_ok = (
            str(result["crs"]) == EXPECTED_CRS
        )

        if not crs_ok:
            vector_crs_ok = False

        print(
            f"{yes_no(crs_ok)} "
            f"{name:<10} "
            f"{result['crs']}"
        )

    # ========================================================
    # WATER SANITY
    # ========================================================

    print()
    print("DATA SANITY")
    print("-" * 90)

    sanity_ok = True

    # --------------------------------------------------------
    # WATER
    # --------------------------------------------------------

    water = raster_results.get("water")

    if water and water["readable"]:

        path = district_dir / "water.tif"

        with rasterio.open(path) as src:

            data = src.read(1, masked=True)

            values = data.compressed()

            nonzero = np.count_nonzero(values)

            print(
                f"Water: "
                f"{nonzero:,} non-zero pixels"
            )

            if nonzero > 0:

                print("✓ Water contains non-zero pixels")

            else:

                print("❌ Water appears empty")

                sanity_ok = False

    else:

        print("❌ Water unavailable")
        sanity_ok = False

    # --------------------------------------------------------
    # NDVI
    # --------------------------------------------------------

    ndvi = raster_results.get("ndvi")

    if ndvi and ndvi["readable"]:

        print(
            f"NDVI: "
            f"{fmt(ndvi['min'])} → "
            f"{fmt(ndvi['max'])}"
        )

        if (
            ndvi["min"] >= -1.1
            and
            ndvi["max"] <= 1.1
        ):

            print("✓ NDVI range looks reasonable")

        else:

            print("⚠ NDVI range is unusual")

    # --------------------------------------------------------
    # SLOPE
    # --------------------------------------------------------

    slope = raster_results.get("slope")

    if slope and slope["readable"]:

        print(
            f"Slope: "
            f"{fmt(slope['min'])} → "
            f"{fmt(slope['max'])}"
        )

        if slope["min"] >= 0:

            print("✓ No negative slope values")

        else:

            print("⚠ Negative slope values detected")

    # --------------------------------------------------------
    # DEM
    # --------------------------------------------------------

    dem = raster_results.get("dem")

    if dem and dem["readable"]:

        print(
            f"DEM: "
            f"{fmt(dem['min'], 1)} → "
            f"{fmt(dem['max'], 1)}"
        )

        print("✓ DEM contains elevation values")

    # --------------------------------------------------------
    # CANOPY
    # --------------------------------------------------------

    canopy = raster_results.get("canopy")

    if canopy and canopy["readable"]:

        print(
            f"Canopy: "
            f"{fmt(canopy['min'], 2)} → "
            f"{fmt(canopy['max'], 2)}"
        )

        print(
            "✓ Canopy data available "
            "(CHM / canopy structure)"
        )

    # --------------------------------------------------------
    # VECTOR FEATURE COUNTS
    # --------------------------------------------------------

    for name in VECTOR_LAYERS:

        result = vector_results[name]

        if not result["readable"]:
            continue

        count = result["feature_count"]

        if count == 0:

            print(
                f"⚠ {name}: vector layer is EMPTY"
            )

        else:

            print(
                f"✓ {name}: "
                f"{count:,} features"
            )

    # ========================================================
    # DISTRICT RESULT
    # ========================================================

    complete = (
        len(valid_rasters) == len(RASTER_LAYERS)
        and
        all(
            result["readable"]
            for result in vector_results.values()
        )
    )

    district_ok = (
        complete
        and
        grid_ok
        and
        vector_crs_ok
        and
        sanity_ok
    )

    print()
    print("-" * 90)

    if district_ok:

        print(
            f"✓ {district.upper()} "
            f"PASSED VALIDATION"
        )

    else:

        print(
            f"⚠ {district.upper()} "
            f"NEEDS ATTENTION"
        )

    return {
        "district": district,
        "passed": district_ok,
        "grid_ok": grid_ok,
        "vector_crs_ok": vector_crs_ok,
        "sanity_ok": sanity_ok,
        "raster_results": raster_results,
        "vector_results": vector_results,
    }


# ============================================================
# MAIN
# ============================================================

print()
print("=" * 90)
print("TSAAY — ALL DISTRICT GIS VALIDATION")
print("=" * 90)

print(f"Project:     {ROOT}")
print(f"Processed:   {PROCESSED_DIR}")
print(f"Districts:   {len(DISTRICTS)}")

results = []

for district in DISTRICTS:

    result = validate_district(district)

    if result is not None:
        results.append(result)


# ============================================================
# FINAL SUMMARY
# ============================================================

print()
print()
print("=" * 90)
print("FINAL VALIDATION SUMMARY")
print("=" * 90)

print()

print(
    f"{'DISTRICT':<12}"
    f"{'RESULT':<12}"
    f"{'GRID':<10}"
    f"{'VECTOR CRS':<14}"
    f"{'SANITY':<10}"
)

print("-" * 90)

for result in results:

    print(
        f"{result['district']:<12}"
        f"{'PASS' if result['passed'] else 'CHECK':<12}"
        f"{'PASS' if result['grid_ok'] else 'CHECK':<10}"
        f"{'PASS' if result['vector_crs_ok'] else 'CHECK':<14}"
        f"{'PASS' if result['sanity_ok'] else 'CHECK':<10}"
    )


passed = sum(
    result["passed"]
    for result in results
)

print()
print(
    f"Districts passed: "
    f"{passed}/{len(results)}"
)

print("=" * 90)
print("VALIDATION COMPLETE")
print("=" * 90)