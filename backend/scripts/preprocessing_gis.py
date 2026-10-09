from pathlib import Path
import math
import shutil

import numpy as np
import rasterio
from rasterio.warp import (
    calculate_default_transform,
    reproject,
    Resampling,
    transform_bounds,
)
from rasterio.transform import from_origin
import geopandas as gpd


# ============================================================
# SHUHUL - GIS PREPROCESSING
# ============================================================
#
# Raw structure:
#
# rawdata/
#   ndvi/
#   ndwi/
#   water/
#   DEM/
#   slope/
#   buildings/
#   heritage/
#   roads/
#
# Output:
#
# processed/
#   district/
#       ndvi.tif
#       ndwi.tif
#       water.tif
#       dem.tif
#       slope.tif
#       buildings.gpkg
#       heritage.gpkg
#       roads.gpkg
#
# Target CRS:
#   EPSG:32643
#
# Target resolution:
#   10 metres
#
# ============================================================


# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = PROJECT_ROOT / "rawdata"
PROCESSED_DIR = PROJECT_ROOT / "processed"

TARGET_CRS = "EPSG:32643"
TARGET_RESOLUTION = 10.0

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


# ------------------------------------------------------------
# FILE FINDING
# ------------------------------------------------------------

def find_file(folder, district, keywords=None):
    """
    Find a district-specific file inside a folder.

    Handles variations such as:
        sxr.tif
        sxr.tiff
        sxr_GL030.tif
        sxr_SLOPE.tif
        sxr_buildings.gpkg
        sxr_roads.gpkg
        sxr-heritage.gpkg
    """

    folder = Path(folder)

    if not folder.exists():
        return None

    files = list(folder.iterdir())

    # Exact district filename first
    exact_names = [
        district,
        district.lower(),
        district.upper(),
    ]

    for ext in [".tif", ".tiff", ".tifff", ".gpkg"]:
        for name in exact_names:
            candidate = folder / f"{name}{ext}"
            if candidate.exists():
                return candidate

    # Search by district name
    district_lower = district.lower()

    candidates = []

    for file in files:
        if not file.is_file():
            continue

        if file.suffix.lower() not in [
            ".tif",
            ".tiff",
            ".tifff",
            ".gpkg",
        ]:
            continue

        if district_lower in file.stem.lower():
            candidates.append(file)

    # Prefer keyword matches if supplied
    if keywords and candidates:
        keyword_matches = []

        for file in candidates:
            filename = file.stem.lower()

            if all(keyword.lower() in filename for keyword in keywords):
                keyword_matches.append(file)

        if keyword_matches:
            return keyword_matches[0]

    if candidates:
        return candidates[0]

    return None


# ------------------------------------------------------------
# RASTER BOUNDS
# ------------------------------------------------------------

def get_target_bounds(raster_paths):
    """
    Calculate the union of all raster bounds in TARGET_CRS.
    """

    bounds = []

    for path in raster_paths:

        if path is None:
            continue

        with rasterio.open(path) as src:

            if src.crs is None:
                raise ValueError(
                    f"Raster has no CRS: {path}"
                )

            transformed = transform_bounds(
                src.crs,
                TARGET_CRS,
                *src.bounds,
                densify_pts=21,
            )

            bounds.append(transformed)

    if not bounds:
        raise ValueError(
            "No raster data available to construct the processing grid."
        )

    left = min(b[0] for b in bounds)
    bottom = min(b[1] for b in bounds)
    right = max(b[2] for b in bounds)
    top = max(b[3] for b in bounds)

    return left, bottom, right, top


# ------------------------------------------------------------
# SNAP GRID TO 10 METRES
# ------------------------------------------------------------

def create_grid(bounds, resolution):
    """
    Create a stable 10m raster grid.
    """

    left, bottom, right, top = bounds

    left = math.floor(left / resolution) * resolution
    bottom = math.floor(bottom / resolution) * resolution
    right = math.ceil(right / resolution) * resolution
    top = math.ceil(top / resolution) * resolution

    width = int(round((right - left) / resolution))
    height = int(round((top - bottom) / resolution))

    transform = from_origin(
        left,
        top,
        resolution,
        resolution,
    )

    return transform, width, height


# ------------------------------------------------------------
# RASTER REPROJECTION
# ------------------------------------------------------------

def reproject_raster(
    source_path,
    output_path,
    target_transform,
    target_width,
    target_height,
    resampling,
    dst_dtype=None,
    dst_nodata=None,
):
    """
    Reproject a raster onto the Shuhul master grid.
    """

    if source_path is None:
        return

    print(f"      Raster: {source_path.name}")

    with rasterio.open(source_path) as src:

        if dst_dtype is None:
            dst_dtype = src.dtypes[0]

        if dst_nodata is None:

            if src.nodata is not None:
                dst_nodata = src.nodata

            elif np.issubdtype(
                np.dtype(dst_dtype),
                np.floating
            ):
                dst_nodata = -9999

            else:
                dst_nodata = 0

        profile = src.profile.copy()

        profile.update(
            {
                "driver": "GTiff",
                "crs": TARGET_CRS,
                "transform": target_transform,
                "width": target_width,
                "height": target_height,
                "dtype": dst_dtype,
                "nodata": dst_nodata,
                "compress": "deflate",
                "predictor": 2,
                "tiled": True,
                "BIGTIFF": "IF_SAFER",
            }
        )

        with rasterio.open(output_path, "w", **profile) as dst:

            for band in range(1, src.count + 1):

                source = src.read(band)

                destination = np.full(
                    (target_height, target_width),
                    dst_nodata,
                    dtype=dst_dtype,
                )

                reproject(
                    source=source,
                    destination=destination,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    src_nodata=src.nodata,
                    dst_transform=target_transform,
                    dst_crs=TARGET_CRS,
                    dst_nodata=dst_nodata,
                    resampling=resampling,
                )

                dst.write(
                    destination,
                    band,
                )

            # Preserve band descriptions where possible
            if src.descriptions:
                dst.descriptions = src.descriptions


# ------------------------------------------------------------
# VECTOR REPROJECTION
# ------------------------------------------------------------

def reproject_vector(
    source_path,
    output_path,
):
    """
    Reproject GeoPackage into TARGET_CRS.
    """

    if source_path is None:
        return

    print(f"      Vector: {source_path.name}")

    gdf = gpd.read_file(source_path)
    
    if gdf.crs is None:
        raise ValueError(
            f"Vector has no CRS: {source_path}"
        )
    
    if gdf.empty:
        print(
            "      WARNING: vector layer is empty. "
            "Creating empty processed layer."
        )
    
    # Reproject even if empty so the output has the
    # correct CRS metadata.
    gdf = gdf.to_crs(TARGET_CRS)
    
    gdf.to_file(
        output_path,
        driver="GPKG"
    )

# ------------------------------------------------------------
# PROCESS ONE DISTRICT
# ------------------------------------------------------------

def process_district(district):

    print()
    print("=" * 70)
    print(f"PROCESSING DISTRICT: {district.upper()}")
    print("=" * 70)

    output_dir = PROCESSED_DIR / district
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # LOCATE INPUT DATA
    # --------------------------------------------------------

    ndvi = find_file(
        RAW_DIR / "ndvi",
        district,
    )

    ndwi = find_file(
        RAW_DIR / "ndwi",
        district,
    )

    water = find_file(
        RAW_DIR / "water",
        district,
    )

    dem = find_file(
        RAW_DIR / "DEM",
        district,
    )

    slope = find_file(
        RAW_DIR / "slope",
        district,
    )

    buildings = find_file(
        RAW_DIR / "buildings",
        district,
        keywords=["building"],
    )

    heritage = find_file(
        RAW_DIR / "heritage",
        district,
        keywords=["heritage"],
    )

    roads = find_file(
        RAW_DIR / "roads",
        district,
        keywords=["road"],
    )

    # Optional future datasets
    forest = find_file(
        RAW_DIR / "forest",
        district,
    )

    canopy = find_file(
        RAW_DIR / "canopy",
        district,
    )

    # --------------------------------------------------------
    # REPORT INPUTS
    # --------------------------------------------------------

    inputs = {
        "NDVI": ndvi,
        "NDWI": ndwi,
        "Water": water,
        "DEM": dem,
        "Slope": slope,
        "Buildings": buildings,
        "Heritage": heritage,
        "Roads": roads,
        "Forest": forest,
        "Canopy": canopy,
    }

    print("\nINPUT DATA:")

    for name, path in inputs.items():

        if path:
            print(f"  ✓ {name:<12} {path.name}")
        else:
            print(f"  - {name:<12} NOT FOUND")

    # --------------------------------------------------------
    # REQUIRED RASTERS
    # --------------------------------------------------------

    raster_inputs = [
        ndvi,
        ndwi,
        water,
        dem,
        slope,
    ]

    available_rasters = [
        p for p in raster_inputs if p is not None
    ]

    if not available_rasters:
        print(
            "\nERROR: No raster data found for district."
        )
        return

    # --------------------------------------------------------
    # CREATE MASTER GRID
    # --------------------------------------------------------

    bounds = get_target_bounds(
        available_rasters
    )

    transform, width, height = create_grid(
        bounds,
        TARGET_RESOLUTION,
    )

    print("\nMASTER GRID:")
    print(f"  CRS:        {TARGET_CRS}")
    print(f"  Resolution: {TARGET_RESOLUTION} m")
    print(f"  Width:      {width}")
    print(f"  Height:     {height}")
    print(
        f"  Size:       {width * height:,} pixels"
    )

    # --------------------------------------------------------
    # PROCESS RASTERS
    # --------------------------------------------------------

    print("\nPROCESSING RASTERS:")

    if ndvi:

        reproject_raster(
            ndvi,
            output_dir / "ndvi.tif",
            transform,
            width,
            height,
            Resampling.bilinear,
            dst_dtype="float32",
            dst_nodata=-9999,
        )

    if ndwi:

        reproject_raster(
            ndwi,
            output_dir / "ndwi.tif",
            transform,
            width,
            height,
            Resampling.bilinear,
            dst_dtype="float32",
            dst_nodata=-9999,
        )

    if water:

        reproject_raster(
            water,
            output_dir / "water.tif",
            transform,
            width,
            height,
            Resampling.nearest,
            dst_dtype="uint8",
            dst_nodata=255,
        )

    if dem:

        reproject_raster(
            dem,
            output_dir / "dem.tif",
            transform,
            width,
            height,
            Resampling.bilinear,
            dst_dtype="float32",
            dst_nodata=-9999,
        )

    if slope:

        reproject_raster(
            slope,
            output_dir / "slope.tif",
            transform,
            width,
            height,
            Resampling.bilinear,
            dst_dtype="float32",
            dst_nodata=-9999,
        )

    # --------------------------------------------------------
    # OPTIONAL FOREST
    # --------------------------------------------------------

    if forest:

        print("\n      Processing FOREST layer...")

        reproject_raster(
            forest,
            output_dir / "forest.tif",
            transform,
            width,
            height,
            Resampling.nearest,
        )

    # --------------------------------------------------------
    # OPTIONAL CANOPY
    # --------------------------------------------------------

    if canopy:

        print("\n      Processing CANOPY layer...")

        reproject_raster(
            canopy,
            output_dir / "canopy.tif",
            transform,
            width,
            height,
            Resampling.bilinear,
            dst_dtype="float32",
            dst_nodata=-9999,
        )

    # --------------------------------------------------------
    # PROCESS VECTORS
    # --------------------------------------------------------

    print("\nPROCESSING VECTORS:")

    if buildings:

        reproject_vector(
            buildings,
            output_dir / "buildings.gpkg",
        )

    if heritage:

        reproject_vector(
            heritage,
            output_dir / "heritage.gpkg",
        )

    if roads:

        reproject_vector(
            roads,
            output_dir / "roads.gpkg",
        )

    # --------------------------------------------------------
    # VERIFY OUTPUT
    # --------------------------------------------------------

    print("\nVERIFYING OUTPUT RASTERS:")

    output_rasters = [
        output_dir / "ndvi.tif",
        output_dir / "ndwi.tif",
        output_dir / "water.tif",
        output_dir / "dem.tif",
        output_dir / "slope.tif",
    ]

    reference = None

    for path in output_rasters:

        if not path.exists():
            continue

        with rasterio.open(path) as src:

            print(
                f"  {path.name:<12}"
                f" {src.width} x {src.height}"
                f" | {src.crs}"
                f" | {src.res}"
            )

            current = (
                src.width,
                src.height,
                src.transform,
                src.crs,
            )

            if reference is None:

                reference = current

            else:

                same_grid = (
                    src.width == reference[0]
                    and
                    src.height == reference[1]
                    and
                    src.transform == reference[2]
                    and
                    src.crs == reference[3]
                )

                if not same_grid:

                    raise RuntimeError(
                        f"GRID MISMATCH DETECTED: {path}"
                    )

    print("\n✓ DISTRICT COMPLETE")


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():

    print()
    print("=" * 70)
    print("SHUHUL GIS PREPROCESSING PIPELINE")
    print("=" * 70)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Raw data:     {RAW_DIR}")
    print(f"Output:       {PROCESSED_DIR}")
    print(f"CRS:          {TARGET_CRS}")
    print(f"Resolution:   {TARGET_RESOLUTION} m")
    print("=" * 70)

    if not RAW_DIR.exists():

        raise FileNotFoundError(
            f"rawdata directory not found:\n{RAW_DIR}"
        )

    PROCESSED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    successful = []
    failed = []

    for district in DISTRICTS:

        try:

            process_district(district)

            successful.append(district)

        except Exception as e:

            failed.append(
                (district, str(e))
            )

            print()
            print(
                f"!!! ERROR PROCESSING {district.upper()}"
            )
            print(e)

    # --------------------------------------------------------
    # FINAL SUMMARY
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("SHUHUL PREPROCESSING SUMMARY")
    print("=" * 70)

    print(
        f"\nSuccessful: {len(successful)}/{len(DISTRICTS)}"
    )

    for district in successful:
        print(f"  ✓ {district}")

    if failed:

        print("\nFailed:")

        for district, error in failed:

            print(
                f"  ✗ {district}: {error}"
            )

    print()
    print("Output directory:")
    print(PROCESSED_DIR)

    print()
    print("Done.")


if __name__ == "__main__":
    main()