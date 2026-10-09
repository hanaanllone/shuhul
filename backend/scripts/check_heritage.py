from pathlib import Path
import geopandas as gpd


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

HERITAGE_DIR = ROOT / "rawdata" / "heritage"

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


# ============================================================
# CHECK HERITAGE DATA
# ============================================================

print("=" * 75)
print("TSAAY — HERITAGE DATA CHECK")
print("=" * 75)

print(f"Directory: {HERITAGE_DIR}")
print()


total_features = 0

for district in DISTRICTS:

    path = HERITAGE_DIR / f"{district}_heritage.gpkg"

    print("-" * 75)
    print(f"DISTRICT: {district.upper()}")

    if not path.exists():
        print("❌ FILE NOT FOUND")
        continue

    try:

        gdf = gpd.read_file(path)

        count = len(gdf)
        total_features += count

        print(f"File:       {path.name}")
        print(f"CRS:        {gdf.crs}")
        print(f"Features:   {count:,}")

        if gdf.empty:
            print("Status:     ⚠ EMPTY")
        else:
            print("Status:     ✓ HAS FEATURES")

            print(
                f"Geometry:   "
                f"{', '.join(gdf.geometry.geom_type.unique())}"
            )

            print(
                f"Bounds:     "
                f"{gdf.total_bounds}"
            )

    except Exception as e:

        print("❌ ERROR READING FILE")
        print(f"   {e}")


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 75)
print("SUMMARY")
print("=" * 75)

print(f"Total heritage features: {total_features:,}")

print()
print("Legend:")
print("  ✓ HAS FEATURES")
print("  ⚠ EMPTY")
print("  ❌ FILE NOT FOUND")

print("=" * 75)