from pathlib import Path
import argparse
import json
import warnings

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling


# ============================================================
# SHUHUL - YEARLY LANDSAT LAYERS
# ============================================================
#
# Turns the raw Landsat windows from fetch_open_data.py into one
# summer composite per year.
#
# Input:
#
# rawdata/landsat/<district>/<scene_id>/*.tif
# rawdata/landsat/<district>/scenes.json
#
# Output (30 m, Landsat grid, EPSG:32643):
#
# processed/<district>/yearly/
#   lst_<year>.tif         median surface temperature, deg C
#   lst_rel_<year>.tif     median temperature relative to the valley floor, deg C
#   ndvi_<year>.tif        vegetation index
#   ndwi_<year>.tif        water index (green / near infrared)
#   mndwi_<year>.tif       water index (green / shortwave infrared)
#   ndbi_<year>.tif        built-up index
#   looks_<year>.tif       number of clear observations per pixel
#   lst_current.tif        median of the latest three yearly composites
#   summary.json
#
# processed/<district>/lst.tif   lst_current on the district's 10 m grid
#
# The thermal band is sensed at 100 m and delivered resampled to 30 m.
# Landsat passes at about 10:50 local time, so this is mid-morning
# surface temperature, not air temperature and not a daily maximum.
#
# Usage:
#   python backend/scripts/build_landsat_layers.py --district sxr
#   python backend/scripts/build_landsat_layers.py --district sxr --publish-only sxr sr-c
#
# ============================================================


# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_ROOT = PROJECT_ROOT / "processed"
RAW_ROOT = PROJECT_ROOT / "rawdata"

SEASON_MONTHS = (6, 7, 8)
CURRENT_YEARS = 3

# QA_PIXEL bits: 0 fill, 1 dilated cloud, 2 cirrus, 3 cloud, 4 cloud shadow.
QA_REJECT_MASK = 0b11111

SR_SCALE, SR_OFFSET = 0.0000275, -0.2
ST_SCALE, ST_OFFSET = 0.00341802, 149.0
KELVIN = 273.15

# Scenes are compared against the valley floor so that a hot or cool day
# does not masquerade as a hot or cool place.
REFERENCE_MAX_ELEVATION_M = 1700.0
REFERENCE_MIN_CLEAR_SHARE = 0.30

NODATA = -9999.0
LAYERS = ["lst", "lst_rel", "ndvi", "ndwi", "mndwi", "ndbi"]


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def log(message):
    print(message, flush=True)


def parse_years(text):
    if "-" in text:
        first, last = text.split("-", 1)
        return list(range(int(first), int(last) + 1))
    return [int(part) for part in text.split(",")]


def target_grid(scenes, raw_dir):
    """Use the grid of a full-coverage scene so most scenes need no resampling."""
    reference = max(scenes, key=lambda scene: scene["coverage"])

    with rasterio.open(raw_dir / reference["id"] / "qa_pixel.tif") as src:
        return {
            "crs": src.crs,
            "transform": src.transform,
            "width": src.width,
            "height": src.height,
        }


def to_grid(array, src, grid, resampling):
    """Place a scene band on the target grid."""
    if (
        src.crs == grid["crs"]
        and src.transform == grid["transform"]
        and src.width == grid["width"]
        and src.height == grid["height"]
    ):
        return array

    fill = np.nan if array.dtype.kind == "f" else 0
    out = np.full((grid["height"], grid["width"]), fill, dtype=array.dtype)

    reproject(
        source=array,
        destination=out,
        src_transform=src.transform,
        src_crs=src.crs,
        src_nodata=fill,
        dst_transform=grid["transform"],
        dst_crs=grid["crs"],
        dst_nodata=fill,
        resampling=resampling,
    )
    return out


def read_band(scene_dir, name, grid, resampling=Resampling.bilinear, as_float=True):
    with rasterio.open(scene_dir / f"{name}.tif") as src:
        array = src.read(1)

        if as_float:
            array = array.astype("float32")
            array[array == 0] = np.nan

        return to_grid(array, src, grid, resampling)


def ratio(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / (a + b)
    out[~np.isfinite(out)] = np.nan
    return np.clip(out, -1, 1)


def reference_mask(district, grid):
    """Valley-floor pixels, used as the common reference for every scene."""
    dem_path = PROCESSED_ROOT / district / "dem.tif"
    elevation = np.full((grid["height"], grid["width"]), np.nan, dtype="float32")

    with rasterio.open(dem_path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=elevation,
            dst_transform=grid["transform"],
            dst_crs=grid["crs"],
            dst_nodata=np.nan,
            resampling=Resampling.average,
        )

    return np.isfinite(elevation) & (elevation < REFERENCE_MAX_ELEVATION_M)


def load_scene(scene_dir, grid, reference):
    """Return masked, scaled layers for one scene on the target grid."""
    qa = read_band(scene_dir, "qa_pixel", grid, Resampling.nearest, as_float=False)
    clear = (qa != 0) & ((qa & QA_REJECT_MASK) == 0)

    bands = {}
    for name in ("red", "nir08", "green", "swir16"):
        band = read_band(scene_dir, name, grid) * SR_SCALE + SR_OFFSET
        band[(band <= 0) | (band > 1)] = np.nan
        bands[name] = band

    lst = read_band(scene_dir, "lwir11", grid) * ST_SCALE + ST_OFFSET - KELVIN

    layers = {
        "lst": lst,
        "ndvi": ratio(bands["nir08"], bands["red"]),
        "ndwi": ratio(bands["green"], bands["nir08"]),
        "mndwi": ratio(bands["green"], bands["swir16"]),
        "ndbi": ratio(bands["swir16"], bands["nir08"]),
    }

    for layer in layers.values():
        layer[~clear] = np.nan

    # Temperature relative to the valley floor on the same pass.
    in_reference = reference & np.isfinite(layers["lst"])
    if in_reference.sum() >= REFERENCE_MIN_CLEAR_SHARE * reference.sum():
        layers["lst_rel"] = layers["lst"] - np.nanmedian(layers["lst"][in_reference])
    else:
        layers["lst_rel"] = np.full_like(lst, np.nan)

    return layers, clear


def write_layer(path, array, grid, dtype="float32", nodata=NODATA):
    data = np.where(np.isfinite(array), array, nodata).astype(dtype)
    path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        dtype=dtype,
        count=1,
        width=grid["width"],
        height=grid["height"],
        crs=grid["crs"],
        transform=grid["transform"],
        nodata=nodata,
        compress="deflate",
        predictor=3 if dtype == "float32" else 2,
        tiled=True,
    ) as dst:
        dst.write(data, 1)
        dst.build_overviews([2, 4, 8], Resampling.average)


# ------------------------------------------------------------
# COMPOSITES
# ------------------------------------------------------------

def build_year(year, scenes, raw_dir, grid, reference, output_dir):
    stacks = {layer: [] for layer in LAYERS}
    looks = np.zeros((grid["height"], grid["width"]), dtype="uint8")
    dates = set()

    for scene in scenes:
        layers, clear = load_scene(raw_dir / scene["id"], grid, reference)
        looks += clear.astype("uint8")
        dates.add(scene["datetime"][:10])

        for layer in LAYERS:
            stacks[layer].append(layers[layer])

    medians = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        for layer in LAYERS:
            medians[layer] = np.nanmedian(np.stack(stacks[layer]), axis=0)
            write_layer(output_dir / f"{layer}_{year}.tif", medians[layer], grid)

    write_layer(output_dir / f"looks_{year}.tif", looks, grid, dtype="uint8", nodata=255)

    valley = reference & np.isfinite(medians["lst"])
    return medians, {
        "year": year,
        "scenes": len(scenes),
        "dates": len(dates),
        "pixels_with_data_pct": round(100 * float(np.isfinite(medians["lst"]).mean()), 1),
        "pixels_with_3_looks_pct": round(100 * float((looks >= 3).mean()), 1),
        "valley_median_lst_c": round(float(np.nanmedian(medians["lst"][valley])), 2),
        "valley_p95_lst_c": round(float(np.nanpercentile(medians["lst"][valley], 95)), 2),
        "valley_mean_ndvi": round(float(np.nanmean(medians["ndvi"][valley])), 3),
        "valley_mean_ndbi": round(float(np.nanmean(medians["ndbi"][valley])), 3),
    }


def build(district, years):
    raw_dir = RAW_ROOT / "landsat" / district
    output_dir = PROCESSED_ROOT / district / "yearly"

    manifest = json.loads((raw_dir / "scenes.json").read_text(encoding="utf-8"))
    used = [scene for scene in manifest if scene["used"]]
    grid = target_grid(used, raw_dir)
    reference = reference_mask(district, grid)

    log("=" * 70)
    log(f"YEARLY LANDSAT LAYERS - {district}")
    log("=" * 70)
    log(f"Grid:   {grid['width']} x {grid['height']} at 30 m")
    log(f"Season: months {SEASON_MONTHS}")
    log(f"Valley-floor reference pixels: {int(reference.sum()):,}")

    summary = []
    yearly_lst = {}

    for year in years:
        scenes = [
            scene for scene in used
            if scene["datetime"].startswith(str(year))
            and int(scene["datetime"][5:7]) in SEASON_MONTHS
        ]

        if not scenes:
            log(f"  {year}: no scenes in season")
            continue

        medians, stats = build_year(year, scenes, raw_dir, grid, reference, output_dir)
        yearly_lst[year] = medians["lst"]
        summary.append(stats)

        log(
            f"  {year}: {stats['dates']:2d} dates | "
            f"data {stats['pixels_with_data_pct']:5.1f}% | "
            f"3+ looks {stats['pixels_with_3_looks_pct']:5.1f}% | "
            f"valley LST {stats['valley_median_lst_c']:.1f} C"
        )

    (output_dir / "summary.json").write_text(
        json.dumps(
            {"district": district, "season_months": SEASON_MONTHS, "years": summary},
            indent=2,
        ),
        encoding="utf-8",
    )

    latest = sorted(yearly_lst)[-CURRENT_YEARS:]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        current = np.nanmedian(np.stack([yearly_lst[year] for year in latest]), axis=0)

    current_path = output_dir / "lst_current.tif"
    write_layer(current_path, current, grid)
    log(f"Current LST ({latest[0]}-{latest[-1]}): {current_path}")


def publish(source_district, district):
    """
    Write the current temperature layer on a district's own 10 m grid, so
    the modules that need every layer on one grid can read it. A district
    that lies inside the source district reuses its composites.
    """
    source = PROCESSED_ROOT / source_district / "yearly" / "lst_current.tif"
    target = PROCESSED_ROOT / district / "lst.tif"

    with rasterio.open(PROCESSED_ROOT / district / "ndvi.tif") as master:
        reference = master.read(1)
        inside = np.isfinite(reference) & (reference != master.nodata)
        grid = {
            "crs": master.crs,
            "transform": master.transform,
            "width": master.width,
            "height": master.height,
        }

    out = np.full((grid["height"], grid["width"]), np.nan, dtype="float32")
    with rasterio.open(source) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            dst_transform=grid["transform"],
            dst_crs=grid["crs"],
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

    out[~inside] = np.nan
    write_layer(target, out, grid)
    log(f"Published {target}")


def main():
    parser = argparse.ArgumentParser(description="Build yearly Landsat composites.")
    parser.add_argument("--district", default="sxr")
    parser.add_argument("--years", default="2017-2025")
    parser.add_argument(
        "--publish-only",
        nargs="+",
        metavar="DISTRICT",
        help="Skip compositing and write lst.tif for these districts from --district.",
    )
    args = parser.parse_args()

    if args.publish_only:
        for district in args.publish_only:
            publish(args.district, district)
        return

    build(args.district, parse_years(args.years))
    publish(args.district, args.district)


if __name__ == "__main__":
    main()
