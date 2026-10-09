from pathlib import Path
import argparse
import json
import numpy as np
import rasterio


# ============================================================
# SHUHUL - COST SURFACE
#
# Produces:
#   soft_cost_<construction>.tif
#       Continuous 0-100 planning/environmental cost.
#
#   hard_constraints_<construction>.tif
#       0 = allowed
#       1 = forbidden
#       255 = nodata
#
#   config_<construction>.json
#       Exact project settings used.
#
# IMPORTANT:
# - Soft preferences influence the soft environmental cost.
# - Hard constraints are NEVER just weighted penalties.
# - shortest/construction priorities are saved for route_planner.py.
# ============================================================


DEFAULT_WEIGHTS = {
    "slope": 0.15,
    "ndvi": 0.20,
    "water": 0.15,
    "canopy": 0.20,
    "buildings": 0.15,
    "roads": 0.05,
    "heritage": 0.10,
    "heat": 0.10,
    "flood": 0.10,
}


# Planning-level modifiers.
# These are NOT engineering or exact monetary construction models.
CONSTRUCTION = {
    "road": {
        "water": 1.50,
        "building": 1.25,
        "heritage": 1.00,
        "slope": 1.00,
        "canopy": 1.00,
        "flood": 1.00,
    },
    "bridge": {
        "water": 0.35,
        "building": 1.10,
        "heritage": 1.00,
        "slope": 0.90,
        "canopy": 0.85,
        "flood": 0.50,
    },
    "flyover": {
        "water": 0.60,
        "building": 0.70,
        "heritage": 1.15,
        "slope": 0.90,
        "canopy": 0.75,
        "flood": 0.50,
    },
}


# Estimated warming, in deg C, that counts as the highest heat cost.
HEAT_SENSITIVITY_MAX_C = 2.0

# Flood susceptibility index: cost starts at the moderate class, and the
# very high class is what a hard flood constraint forbids.
FLOOD_MODERATE = 0.45
FLOOD_VERY_HIGH = 0.85

# Slope a hard steep-terrain constraint forbids, in degrees.
STEEP_SLOPE_DEG = 30.0


# ============================================================
# FILE HELPERS
# ============================================================

def find_raster(folder, names, required=False):
    """
    Find a raster using exact, case-insensitive filenames.

    Example:
        names=["ndvi"]
    matches:
        ndvi.tif
    """

    files = {
        p.name.lower(): p
        for p in folder.glob("*.tif")
    }

    for name in names:

        candidates = [
            name,
            f"{name}.tif",
        ]

        for candidate in candidates:

            path = files.get(candidate.lower())

            if path is not None:
                return path

    if required:
        raise FileNotFoundError(
            f"Missing required raster in {folder}: {names}"
        )

    return None


def read(path, reference=None):
    """
    Read a raster and convert nodata/non-finite values to NaN.

    If reference is supplied, the raster must have exactly the same
    dimensions, CRS and transform.
    """

    with rasterio.open(path) as src:

        if reference is not None:

            same_grid = (
                src.width == reference.width
                and src.height == reference.height
                and src.crs == reference.crs
                and src.transform == reference.transform
            )

            if not same_grid:

                raise ValueError(
                    f"Grid mismatch: {path.name}\n"
                    f"Expected: {reference.width} x "
                    f"{reference.height}, "
                    f"{reference.crs}, "
                    f"{reference.transform}\n"
                    f"Found: {src.width} x "
                    f"{src.height}, "
                    f"{src.crs}, "
                    f"{src.transform}"
                )

        array = src.read(1).astype("float32")

        if src.nodata is not None:
            array[array == src.nodata] = np.nan

        array[~np.isfinite(array)] = np.nan

        return array


# ============================================================
# RASTER TRANSFORMATIONS
# ============================================================

def normalize(array, low=None, high=None):
    """
    Normalize continuous values to 0-1.

    0 = relatively low cost
    1 = relatively high cost
    """

    output = np.zeros_like(array, dtype="float32")

    valid = np.isfinite(array)

    if not valid.any():
        return output

    if low is None:
        low = np.nanpercentile(array, 2)

    if high is None:
        high = np.nanpercentile(array, 98)

    if high <= low:
        return output

    output[valid] = np.clip(
        (array[valid] - low) / (high - low),
        0,
        1,
    )

    return output


def presence(array):
    """
    Convert a raster into a binary presence mask.

    > 0 = present
    <= 0 = absent
    """

    return np.where(
        np.isfinite(array) & (array > 0),
        1.0,
        0.0,
    ).astype("float32")


# ============================================================
# SOFT WEIGHTS
# ============================================================

def build_weights(
    tree_priority,
    greenery_priority,
    water_priority,
    heat_priority=0.5,
    flood_priority=0.5,
):
    """
    Turn user-facing 0-1 priorities into environmental weights.

    shortest_priority and construction_priority intentionally do NOT
    modify this raster. They belong to route_planner.py because they
    describe the route objective rather than spatial environmental
    sensitivity.
    """

    weights = DEFAULT_WEIGHTS.copy()

    # Tree priority influences both NDVI and canopy.
    tree_scale = 0.25 + tree_priority

    weights["ndvi"] *= tree_scale
    weights["canopy"] *= tree_scale

    # Greenery priority increases vegetation sensitivity.
    greenery_scale = 0.25 + greenery_priority

    weights["ndvi"] *= greenery_scale

    # Water priority controls water sensitivity.
    water_scale = 0.25 + water_priority

    weights["water"] *= water_scale

    # Heat and flood priorities control their own factors.
    weights["heat"] *= 0.25 + heat_priority
    weights["flood"] *= 0.25 + flood_priority

    total = sum(weights.values())

    if total <= 0:
        raise ValueError(
            "Environmental weights cannot all be zero."
        )

    return {
        key: value / total
        for key, value in weights.items()
    }


# ============================================================
# BUILD COST SURFACE
# ============================================================

def build_cost_surface(
    district_dir,
    output_soft,
    output_hard,
    construction="road",

    tree_priority=0.5,
    greenery_priority=0.5,
    water_priority=0.5,

    shortest_priority=0.5,
    construction_priority=0.5,

    hard_heritage=False,
    hard_water=False,
    hard_forest=False,

    heat_priority=0.5,
    flood_priority=0.5,

    hard_flood=False,
    hard_steep=False,
):

    district_dir = Path(district_dir)

    if construction not in CONSTRUCTION:

        raise ValueError(
            f"Unknown construction type: {construction}"
        )

    # --------------------------------------------------------
    # Reference raster
    # --------------------------------------------------------

    ndvi_path = find_raster(
        district_dir,
        ["ndvi"],
        required=True,
    )

    with rasterio.open(ndvi_path) as reference:

        ndvi = read(ndvi_path)

        profile = reference.profile.copy()

        def layer(names):

            path = find_raster(
                district_dir,
                names,
            )

            if path is None:
                return None

            return read(
                path,
                reference,
            )

        slope = layer(["slope"])
        water = layer(["water"])
        ndwi = layer(["ndwi"])
        buildings = layer([
            "buildings",
            "building",
        ])
        roads = layer([
            "roads",
            "road",
        ])
        canopy = layer([
            "tree_height",
            "canopy",
            "chm",
            "CHM",
        ])
        heritage = layer([
            "heritage",
            "HERITAGE",
        ])
        forest = layer([
            "forest",
            "forests",
        ])
        heat = layer(["heat_sensitivity"])
        flood = layer(["flood"])

    modifier = CONSTRUCTION[construction]

    # --------------------------------------------------------
    # SOFT COST COMPONENTS
    # --------------------------------------------------------

    # Higher NDVI = greater vegetation sensitivity.
    ndvi_cost = normalize(
        ndvi,
        -0.1,
        0.9,
    )

    # CHM / canopy height.
    canopy_cost = (
        normalize(
            canopy,
            0,
            30,
        )
        if canopy is not None
        else np.zeros_like(ndvi)
    )

    # Steeper terrain = greater planning difficulty.
    slope_cost = (
        normalize(
            slope,
            0,
            30,
        )
        if slope is not None
        else np.zeros_like(ndvi)
    )

    # --------------------------------------------------------
    # WATER
    # --------------------------------------------------------

    if water is not None:

        water_cost = presence(water)

    elif ndwi is not None:

        water_cost = normalize(
            ndwi,
            -0.5,
            0.5,
        )

    else:

        water_cost = np.zeros_like(ndvi)

    # --------------------------------------------------------
    # BUILDINGS
    # --------------------------------------------------------

    building_cost = (
        normalize(buildings, 0, 1)
        if buildings is not None
        else np.zeros_like(ndvi)
    )

    # --------------------------------------------------------
    # EXISTING ROADS
    #
    # Existing road = lower additional planning cost.
    # Non-road = slightly higher cost.
    # --------------------------------------------------------

    if roads is not None:

        road_cost = (
            1.0 - presence(roads)
        )

    else:

        road_cost = np.zeros_like(ndvi)

    # --------------------------------------------------------
    # HERITAGE
    #
    # It is represented in BOTH:
    #   - soft cost
    #   - optional hard mask
    #
    # If hard_heritage=True, the route planner will later treat
    # these pixels as forbidden.
    # --------------------------------------------------------

    heritage_cost = (
        presence(heritage)
        if heritage is not None
        else np.zeros_like(ndvi)
    )

    # --------------------------------------------------------
    # HEAT
    #
    # Estimated warming if the cell were paved. Green land that is
    # cooling its surroundings costs the most; land that is already
    # built costs almost nothing.
    # --------------------------------------------------------

    heat_cost = (
        normalize(
            heat,
            0,
            HEAT_SENSITIVITY_MAX_C,
        )
        if heat is not None
        else np.zeros_like(ndvi)
    )

    # --------------------------------------------------------
    # FLOOD
    # --------------------------------------------------------

    flood_cost = (
        normalize(
            flood,
            FLOOD_MODERATE,
            FLOOD_VERY_HIGH,
        )
        if flood is not None
        else np.zeros_like(ndvi)
    )

    # --------------------------------------------------------
    # CONSTRUCTION MODIFIERS
    # --------------------------------------------------------

    flood_cost *= modifier["flood"]
    water_cost *= modifier["water"]
    building_cost *= modifier["building"]
    heritage_cost *= modifier["heritage"]
    slope_cost *= modifier["slope"]
    canopy_cost *= modifier["canopy"]

    # --------------------------------------------------------
    # USER SOFT PREFERENCES
    # --------------------------------------------------------

    weights = build_weights(
        tree_priority=tree_priority,
        greenery_priority=greenery_priority,
        water_priority=water_priority,
        heat_priority=heat_priority,
        flood_priority=flood_priority,
    )

    soft_cost = (
        weights["slope"] * slope_cost
        + weights["ndvi"] * ndvi_cost
        + weights["water"] * water_cost
        + weights["canopy"] * canopy_cost
        + weights["buildings"] * building_cost
        + weights["roads"] * road_cost
        + weights["heritage"] * heritage_cost
        + weights["heat"] * heat_cost
        + weights["flood"] * flood_cost
    )

    # Scale to 0-100.
    soft_cost *= 100.0

    # --------------------------------------------------------
    # HARD CONSTRAINT MASK
    #
    # 0 = allowed
    # 1 = forbidden
    # 255 = nodata
    # --------------------------------------------------------

    hard_mask = np.zeros_like(
        ndvi,
        dtype="uint8",
    )

    # Heritage
    if hard_heritage:

        if heritage is not None:

            hard_mask[
                np.isfinite(heritage)
                & (heritage > 0)
            ] = 1

        else:

            print(
                "WARNING: --hard-heritage requested, "
                "but no heritage raster was found."
            )

    # Water
    if hard_water:

        if water is not None:

            hard_mask[
                np.isfinite(water)
                & (water > 0)
            ] = 1

        else:

            print(
                "WARNING: --hard-water requested, "
                "but no water raster was found."
            )

    # Forest
    if hard_forest:

        if forest is not None:

            hard_mask[
                np.isfinite(forest)
                & (forest > 0)
            ] = 1

        else:

            print(
                "WARNING: --hard-forest requested, "
                "but no forest raster was found."
            )

    # Flood: land where water has been recorded.
    if hard_flood:

        if flood is not None:

            hard_mask[
                np.isfinite(flood)
                & (flood >= FLOOD_VERY_HIGH)
            ] = 1

        else:

            print(
                "WARNING: hard flood constraint requested, "
                "but no flood raster was found."
            )

    # Steep terrain
    if hard_steep:

        if slope is not None:

            hard_mask[
                np.isfinite(slope)
                & (slope >= STEEP_SLOPE_DEG)
            ] = 1

        else:

            print(
                "WARNING: hard steep-terrain constraint requested, "
                "but no slope raster was found."
            )

    # --------------------------------------------------------
    # NODATA
    # --------------------------------------------------------

    invalid = ~np.isfinite(ndvi)

    soft_cost[invalid] = -9999
    hard_mask[invalid] = 255

    # --------------------------------------------------------
    # OUTPUT PROFILES
    # --------------------------------------------------------

    soft_profile = profile.copy()

    soft_profile.update(
        dtype="float32",
        count=1,
        nodata=-9999,
        compress="deflate",
    )

    hard_profile = profile.copy()

    hard_profile.update(
        dtype="uint8",
        count=1,
        nodata=255,
        compress="deflate",
    )

    output_soft.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_hard.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # WRITE SOFT COST
    # --------------------------------------------------------

    with rasterio.open(
        output_soft,
        "w",
        **soft_profile,
    ) as dst:

        dst.write(
            soft_cost.astype("float32"),
            1,
        )

    # --------------------------------------------------------
    # WRITE HARD MASK
    # --------------------------------------------------------

    with rasterio.open(
        output_hard,
        "w",
        **hard_profile,
    ) as dst:

        dst.write(
            hard_mask,
            1,
        )

    return {
        "soft_output": str(output_soft),
        "hard_output": str(output_hard),

        "construction": construction,

        "soft_preferences": {
            "tree_priority": tree_priority,
            "greenery_priority": greenery_priority,
            "water_priority": water_priority,
            "shortest_priority": shortest_priority,
            "construction_priority": construction_priority,
            "heat_priority": heat_priority,
            "flood_priority": flood_priority,
        },

        "hard_constraints": {
            "heritage": hard_heritage,
            "water": hard_water,
            "forest": hard_forest,
            "flood": hard_flood,
            "steep_slope": hard_steep,
        },

        "layers_used": {
            "buildings": buildings is not None,
            "roads": roads is not None,
            "heritage": heritage is not None,
            "forest": forest is not None,
            "heat": heat is not None,
            "flood": flood is not None,
        },

        "weights": weights,
    }


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Build Shuhul soft cost surface and hard "
            "constraint mask."
        )
    )

    # --------------------------------------------------------
    # District
    # --------------------------------------------------------

    parser.add_argument(
        "--district",
        required=True,
        help="District folder inside processed/",
    )

    # --------------------------------------------------------
    # Construction
    # --------------------------------------------------------

    parser.add_argument(
        "--construction",
        choices=list(CONSTRUCTION.keys()),
        default="road",
        help="road, bridge or flyover",
    )

    # --------------------------------------------------------
    # SOFT PARAMETERS
    # --------------------------------------------------------

    parser.add_argument(
        "--tree-priority",
        type=float,
        default=0.5,
        help="Tree/canopy priority: 0-1",
    )

    parser.add_argument(
        "--greenery-priority",
        type=float,
        default=0.5,
        help="Greenery priority: 0-1",
    )

    parser.add_argument(
        "--water-priority",
        type=float,
        default=0.5,
        help="Water priority: 0-1",
    )

    parser.add_argument(
        "--shortest-priority",
        type=float,
        default=0.5,
        help=(
            "Shortest-route priority: 0-1. "
            "Saved for route_planner.py."
        ),
    )

    parser.add_argument(
        "--construction-priority",
        type=float,
        default=0.5,
        help=(
            "Construction-cost priority: 0-1. "
            "Saved for route_planner.py."
        ),
    )

    # --------------------------------------------------------
    # HARD PARAMETERS
    # --------------------------------------------------------

    parser.add_argument(
        "--hard-heritage",
        action="store_true",
        help="Make heritage areas forbidden.",
    )

    parser.add_argument(
        "--hard-water",
        action="store_true",
        help="Make water areas forbidden.",
    )

    parser.add_argument(
        "--hard-forest",
        action="store_true",
        help="Make forest areas forbidden.",
    )

    # --------------------------------------------------------
    # PATHS
    # --------------------------------------------------------

    project_root = (
        Path(__file__).resolve().parents[2]
    )

    default_processed_root = (
        project_root / "processed"
    )

    default_output_root = (
        project_root
        / "outputs"
        / "cost_surfaces"
    )

    parser.add_argument(
        "--processed-root",
        default=str(default_processed_root),
    )

    parser.add_argument(
        "--output-root",
        default=str(default_output_root),
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Validate priorities
    # --------------------------------------------------------

    priorities = {
        "tree": args.tree_priority,
        "greenery": args.greenery_priority,
        "water": args.water_priority,
        "shortest": args.shortest_priority,
        "construction": args.construction_priority,
    }

    for name, value in priorities.items():

        if not 0 <= value <= 1:

            raise ValueError(
                f"{name} priority must be between 0 and 1. "
                f"Received: {value}"
            )

    # --------------------------------------------------------
    # District
    # --------------------------------------------------------

    district = (
        Path(args.processed_root)
        / args.district
    )

    if not district.exists():

        raise FileNotFoundError(
            f"District not found: {district}"
        )

    # --------------------------------------------------------
    # Outputs
    # --------------------------------------------------------

    output_dir = (
        Path(args.output_root)
        / args.district
    )

    output_soft = (
        output_dir
        / f"soft_cost_{args.construction}.tif"
    )

    output_hard = (
        output_dir
        / f"hard_constraints_{args.construction}.tif"
    )

    config_path = (
        output_dir
        / f"config_{args.construction}.json"
    )

    # --------------------------------------------------------
    # Build
    # --------------------------------------------------------

    result = build_cost_surface(

        district_dir=district,

        output_soft=output_soft,
        output_hard=output_hard,

        construction=args.construction,

        tree_priority=args.tree_priority,
        greenery_priority=args.greenery_priority,
        water_priority=args.water_priority,

        shortest_priority=args.shortest_priority,
        construction_priority=args.construction_priority,

        hard_heritage=args.hard_heritage,
        hard_water=args.hard_water,
        hard_forest=args.hard_forest,
    )

    # --------------------------------------------------------
    # Save exact configuration
    # --------------------------------------------------------

    with open(
        config_path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            result,
            file,
            indent=2,
        )

    # --------------------------------------------------------
    # Terminal summary
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("SHUHUL COST SURFACE")
    print("=" * 70)

    print(f"District:             {args.district}")
    print(f"Construction:         {args.construction}")

    print()
    print("SOFT PARAMETERS")
    print("-" * 70)
    print(f"Tree priority:        {args.tree_priority:.2f}")
    print(f"Greenery priority:    {args.greenery_priority:.2f}")
    print(f"Water priority:       {args.water_priority:.2f}")
    print(f"Shortest priority:    {args.shortest_priority:.2f}")
    print(f"Construction priority:{args.construction_priority:.2f}")

    print()
    print("HARD PARAMETERS")
    print("-" * 70)
    print(f"Heritage:             {args.hard_heritage}")
    print(f"Water:                {args.hard_water}")
    print(f"Forest:               {args.hard_forest}")

    print()
    print("OUTPUTS")
    print("-" * 70)
    print(f"Soft cost:            {output_soft}")
    print(f"Hard constraints:     {output_hard}")
    print(f"Configuration:        {config_path}")

    print("=" * 70)


if __name__ == "__main__":
    main()