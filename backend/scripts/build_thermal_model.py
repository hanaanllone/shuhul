from pathlib import Path
import argparse
import json
import warnings

import joblib
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from scipy import ndimage
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold


# ============================================================
# SHUHUL - THERMAL MODEL
# ============================================================
#
# Fits a model of summer surface temperature from what covers the
# ground and what surrounds it, so that a change on the ground (trees
# removed, a road built, a site planted) can be turned into an
# estimated change in surface temperature.
#
# Input:
#
# processed/<district>/yearly/lst_current.tif   target, 30 m
# processed/<district>/yearly/ndvi_<year>.tif   latest three years
# processed/<district>/  tree_height.tif buildings.tif landcover.tif
#                        water.tif dem.tif slope.tif
#
# Output:
#
# processed/<district>/thermal/
#   features.tif     one band per feature, on the 30 m Landsat grid
#   model.joblib     fitted model
#   model.json       feature list, typical values, cross-validation error
#
# The model is statistical, not physical. Its error on held-out blocks
# of the district is saved in model.json and must travel with every
# estimate it produces.
#
# Usage:
#   python backend/scripts/build_thermal_model.py --district sxr
#
# ============================================================


# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_ROOT = PROJECT_ROOT / "processed"

CURRENT_YEARS = 3
WATER_DISTANCE_CAP_M = 2000.0

# Cooling and heating spill over to neighbours. Park studies put the
# reach at roughly 180-280 m, so the near window is about 150 m either
# side and the far window about 500 m.
NEAR_CELLS = 11
FAR_CELLS = 35

WC_TREE, WC_GRASS, WC_CROP, WC_BUILT, WC_WATER = 10, 30, 40, 50, 80

# Feature name -> direction the model is allowed to respond in.
# -1: more of it can only cool. +1: more of it can only warm. 0: free.
FEATURES = {
    "ndvi": -1,
    "canopy_share": -1,
    "canopy_height": -1,
    "roof_share": 1,
    "built_share": 1,
    "tree_share": -1,
    "crop_share": 0,
    "grass_share": 0,
    "water_share": -1,
    "water_distance": 1,
    "ndvi_near": -1,
    "built_near": 1,
    "canopy_near": -1,
    "ndvi_far": -1,
    "built_far": 1,
    "elevation": -1,
    "slope": 0,
    "eastness": 0,
    "southness": 0,
}

# Features a scenario changes directly, and the ones derived from them.
NEIGHBOURHOOD = {
    "ndvi_near": ("ndvi", NEAR_CELLS),
    "built_near": ("built_share", NEAR_CELLS),
    "canopy_near": ("canopy_share", NEAR_CELLS),
    "ndvi_far": ("ndvi", FAR_CELLS),
    "built_far": ("built_share", FAR_CELLS),
}

MAX_TRAINING_CELLS = 300_000
CV_BLOCK_CELLS = 100
CV_FOLDS = 5
RANDOM_SEED = 7

NODATA = -9999.0


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def log(message):
    print(message, flush=True)


def read_array(path):
    with rasterio.open(path) as src:
        array = src.read(1).astype("float32")
        if src.nodata is not None:
            array[array == src.nodata] = np.nan
        return array, src.transform, src.crs


def to_thermal_grid(array, transform, crs, grid):
    """Average a finer layer onto the 30 m thermal grid."""
    out = np.full((grid["height"], grid["width"]), np.nan, dtype="float32")

    reproject(
        source=array,
        destination=out,
        src_transform=transform,
        src_crs=crs,
        src_nodata=np.nan,
        dst_transform=grid["transform"],
        dst_crs=grid["crs"],
        dst_nodata=np.nan,
        resampling=Resampling.average,
    )
    return out


def neighbourhood_mean(array, cells):
    """Mean of the surrounding window, ignoring missing cells."""
    valid = np.isfinite(array)
    total = ndimage.uniform_filter(np.where(valid, array, 0.0), cells, mode="nearest")
    weight = ndimage.uniform_filter(valid.astype("float32"), cells, mode="nearest")

    with np.errstate(divide="ignore", invalid="ignore"):
        out = total / weight
    out[weight < 0.05] = np.nan
    return out.astype("float32")


def terrain_aspect(elevation, cell_size):
    """Return (eastness, southness): how strongly a slope faces east and south."""
    filled = np.where(np.isfinite(elevation), elevation, np.nanmean(elevation))
    d_row, d_col = np.gradient(filled, cell_size)

    # Row index grows southwards, so +d_row means the ground rises to the south.
    steepness = np.sqrt(d_row ** 2 + d_col ** 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        eastness = np.where(steepness > 0, -d_col / steepness, 0.0)
        southness = np.where(steepness > 0, d_row / steepness, 0.0)

    gradient = np.clip(steepness, 0, 1)
    return (eastness * gradient).astype("float32"), (southness * gradient).astype("float32")


# ------------------------------------------------------------
# FEATURES
# ------------------------------------------------------------

def build_features(district):
    base = PROCESSED_ROOT / district
    yearly = base / "yearly"

    target, transform, crs = read_array(yearly / "lst_current.tif")
    grid = {
        "transform": transform,
        "crs": crs,
        "height": target.shape[0],
        "width": target.shape[1],
    }
    cell_size = abs(transform.a)

    years = sorted(
        int(path.stem.split("_")[1]) for path in yearly.glob("ndvi_*.tif")
    )[-CURRENT_YEARS:]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        ndvi = np.nanmedian(
            np.stack([read_array(yearly / f"ndvi_{year}.tif")[0] for year in years]),
            axis=0,
        )

    def fine(name):
        array, src_transform, src_crs = read_array(base / f"{name}.tif")
        return array, src_transform, src_crs

    def averaged(array, src_transform, src_crs):
        return to_thermal_grid(array.astype("float32"), src_transform, src_crs, grid)

    tree_height, t, c = fine("tree_height")
    canopy_height = averaged(tree_height, t, c)
    canopy_share = averaged(
        np.where(np.isfinite(tree_height), (tree_height > 0).astype("float32"), np.nan), t, c
    )

    roofs, t, c = fine("buildings")
    roof_share = averaged(roofs, t, c)

    landcover, t, c = fine("landcover")

    def cover_share(code):
        return averaged(
            np.where(np.isfinite(landcover), (landcover == code).astype("float32"), np.nan), t, c
        )

    built_share = cover_share(WC_BUILT)
    tree_share = cover_share(WC_TREE)
    crop_share = cover_share(WC_CROP)
    grass_share = cover_share(WC_GRASS)

    water, tw, cw = fine("water")
    water_share = np.fmax(
        averaged(np.where(np.isfinite(water), (water > 0).astype("float32"), np.nan), tw, cw),
        cover_share(WC_WATER),
    )

    water_distance = ndimage.distance_transform_edt(
        ~(np.nan_to_num(water_share, nan=0.0) >= 0.5), sampling=cell_size
    )
    water_distance = np.clip(water_distance, 0, WATER_DISTANCE_CAP_M).astype("float32")

    dem, t, c = fine("dem")
    elevation = averaged(dem, t, c)
    slope_fine, t, c = fine("slope")
    slope = averaged(slope_fine, t, c)
    eastness, southness = terrain_aspect(elevation, cell_size)

    features = {
        "ndvi": ndvi,
        "canopy_share": canopy_share,
        "canopy_height": canopy_height,
        "roof_share": roof_share,
        "built_share": built_share,
        "tree_share": tree_share,
        "crop_share": crop_share,
        "grass_share": grass_share,
        "water_share": water_share,
        "water_distance": water_distance,
        "elevation": elevation,
        "slope": slope,
        "eastness": eastness,
        "southness": southness,
    }

    for name, (source, cells) in NEIGHBOURHOOD.items():
        features[name] = neighbourhood_mean(features[source], cells)

    # A cell is usable when it lies inside the district and was observed.
    inside = np.isfinite(built_share) & np.isfinite(elevation)
    return features, target, inside, grid


def write_features(path, features, inside, grid):
    path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        dtype="float32",
        count=len(FEATURES),
        width=grid["width"],
        height=grid["height"],
        crs=grid["crs"],
        transform=grid["transform"],
        nodata=NODATA,
        compress="deflate",
        predictor=3,
        tiled=True,
    ) as dst:
        for index, name in enumerate(FEATURES, start=1):
            band = np.where(inside & np.isfinite(features[name]), features[name], NODATA)
            dst.write(band.astype("float32"), index)
            dst.set_band_description(index, name)


# ------------------------------------------------------------
# MODEL
# ------------------------------------------------------------

def new_model():
    return HistGradientBoostingRegressor(
        max_iter=300,
        learning_rate=0.08,
        max_leaf_nodes=31,
        min_samples_leaf=60,
        l2_regularization=1.0,
        monotonic_cst=list(FEATURES.values()),
        random_state=RANDOM_SEED,
    )


def typical_values(features, inside):
    """Median feature values of real cells of each surface type in this district."""
    surfaces = {
        "paved": (features["built_share"] >= 0.8) & (features["roof_share"] < 0.15),
        "built": features["roof_share"] >= 0.5,
        "tree": features["canopy_share"] >= 0.8,
        "shrub": (features["grass_share"] >= 0.8) & (features["canopy_share"] < 0.2),
        "crop": features["crop_share"] >= 0.8,
        "green_roof": (features["roof_share"] >= 0.3) & (features["ndvi"] >= 0.45),
    }

    direct = [name for name in FEATURES if name not in NEIGHBOURHOOD]
    surface_features = [
        "ndvi", "canopy_share", "canopy_height", "roof_share",
        "built_share", "tree_share", "crop_share", "grass_share",
    ]

    typical = {}
    for surface, mask in surfaces.items():
        mask = mask & inside
        if int(mask.sum()) < 200:
            continue
        typical[surface] = {
            name: round(float(np.nanmedian(features[name][mask])), 4)
            for name in surface_features
        }
        typical[surface]["cells"] = int(mask.sum())

    # A new road has no real counterpart at 30 m, where every paved cell
    # is mixed with yards and verges. Use the barest tenth of built-up
    # cells for its greenness and set the rest by definition.
    built_up = (features["built_share"] >= 0.8) & inside
    if int(built_up.sum()) >= 200:
        typical["road"] = {
            "ndvi": round(float(np.nanpercentile(features["ndvi"][built_up], 10)), 4),
            "canopy_share": 0.0,
            "canopy_height": 0.0,
            "roof_share": 0.0,
            "built_share": 1.0,
            "tree_share": 0.0,
            "crop_share": 0.0,
            "grass_share": 0.0,
            "cells": int(built_up.sum()),
        }

    return typical, direct


def fit(district):
    features, target, inside, grid = build_features(district)
    output_dir = PROCESSED_ROOT / district / "thermal"

    log("=" * 70)
    log(f"THERMAL MODEL - {district}")
    log("=" * 70)

    write_features(output_dir / "features.tif", features, inside, grid)

    usable = inside & np.isfinite(target)
    rows, cols = np.nonzero(usable)

    rng = np.random.default_rng(RANDOM_SEED)
    if rows.size > MAX_TRAINING_CELLS:
        pick = rng.choice(rows.size, MAX_TRAINING_CELLS, replace=False)
        rows, cols = rows[pick], cols[pick]

    X = np.column_stack([features[name][rows, cols] for name in FEATURES])
    y = target[rows, cols]
    blocks = (rows // CV_BLOCK_CELLS) * 10_000 + (cols // CV_BLOCK_CELLS)

    log(f"Usable cells:   {int(usable.sum()):,}")
    log(f"Training cells: {rows.size:,}")

    # Hold out whole 3 km blocks, so the score reflects places the model
    # has not seen rather than neighbours of its training cells.
    predicted = np.full(y.shape, np.nan, dtype="float32")
    for train, test in GroupKFold(CV_FOLDS).split(X, y, blocks):
        model = new_model().fit(X[train], y[train])
        predicted[test] = model.predict(X[test])

    metrics = {
        "rmse_c": round(float(np.sqrt(mean_squared_error(y, predicted))), 2),
        "mae_c": round(float(mean_absolute_error(y, predicted)), 2),
        "r2": round(float(r2_score(y, predicted)), 3),
        "validation": f"{CV_FOLDS}-fold, whole {CV_BLOCK_CELLS * 30 // 1000} km blocks held out",
        "training_cells": int(rows.size),
    }

    model = new_model().fit(X, y)
    joblib.dump(model, output_dir / "model.joblib")

    typical, direct = typical_values(features, inside)

    summary = {
        "district": district,
        "target": "Median clear-sky summer surface temperature, latest three years, deg C",
        "features": list(FEATURES),
        "directions": FEATURES,
        "neighbourhood": {name: list(spec) for name, spec in NEIGHBOURHOOD.items()},
        "direct_features": direct,
        "typical_surfaces": typical,
        "metrics": metrics,
        "cell_size_m": abs(grid["transform"].a),
    }
    (output_dir / "model.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    log(f"Held-out error: RMSE {metrics['rmse_c']} C | MAE {metrics['mae_c']} C | R2 {metrics['r2']}")
    for surface, values in typical.items():
        log(f"  typical {surface:6s} ndvi {values['ndvi']:.2f} canopy {values['canopy_share']:.2f} built {values['built_share']:.2f} ({values['cells']:,} cells)")
    log(f"Saved: {output_dir}")

    return model, features, target, inside, summary


def main():
    parser = argparse.ArgumentParser(description="Fit the district thermal model.")
    parser.add_argument("--district", default="sxr")
    args = parser.parse_args()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit(args.district)


if __name__ == "__main__":
    main()
