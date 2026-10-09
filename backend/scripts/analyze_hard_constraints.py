from pathlib import Path
import argparse

import numpy as np
import rasterio
import matplotlib.pyplot as plt


def analyze(path: Path, output_png: Path):

    print("\n" + "=" * 70)
    print("SHUHUL HARD CONSTRAINT ANALYSIS")
    print("=" * 70)

    with rasterio.open(path) as src:

        data = src.read(1)

        print("\n[1] RASTER INFORMATION")
        print("-" * 70)

        print(f"File:              {path}")
        print(f"CRS:               {src.crs}")
        print(f"Width:             {src.width}")
        print(f"Height:            {src.height}")
        print(f"Resolution:        {src.res}")
        print(f"Bounds:            {src.bounds}")
        print(f"NoData:            {src.nodata}")

        # --------------------------------------------------------
        # Masks
        # --------------------------------------------------------

        nodata = src.nodata

        if nodata is not None:
            nodata_mask = data == nodata
        else:
            nodata_mask = np.zeros(data.shape, dtype=bool)

        valid_mask = ~nodata_mask

        allowed = valid_mask & (data == 0)
        forbidden = valid_mask & (data == 1)

        other = valid_mask & ~((data == 0) | (data == 1))

        valid_count = np.sum(valid_mask)
        allowed_count = np.sum(allowed)
        forbidden_count = np.sum(forbidden)
        nodata_count = np.sum(nodata_mask)
        other_count = np.sum(other)

        print("\n[2] CONSTRAINT STATISTICS")
        print("-" * 70)

        print(f"Total pixels:       {data.size:,}")
        print(f"Valid pixels:       {valid_count:,}")
        print(f"Allowed pixels:     {allowed_count:,}")
        print(f"Forbidden pixels:   {forbidden_count:,}")
        print(f"NoData pixels:      {nodata_count:,}")

        if other_count:
            print(f"Unexpected values:  {other_count:,}")
            print("WARNING: values other than 0, 1 and NoData detected.")
        else:
            print("Unexpected values:  0")

        # --------------------------------------------------------
        # Percentages
        # --------------------------------------------------------

        print("\n[3] AREA DISTRIBUTION")
        print("-" * 70)

        if valid_count > 0:

            allowed_pct = (
                allowed_count / valid_count * 100
            )

            forbidden_pct = (
                forbidden_count / valid_count * 100
            )

            print(
                f"Allowed:            "
                f"{allowed_pct:.2f}%"
            )

            print(
                f"Forbidden:          "
                f"{forbidden_pct:.2f}%"
            )

        # --------------------------------------------------------
        # Approximate area
        # --------------------------------------------------------

        pixel_width = abs(src.transform.a)
        pixel_height = abs(src.transform.e)

        pixel_area_m2 = pixel_width * pixel_height

        forbidden_area_m2 = (
            forbidden_count * pixel_area_m2
        )

        allowed_area_m2 = (
            allowed_count * pixel_area_m2
        )

        print("\n[4] APPROXIMATE AREA")
        print("-" * 70)

        print(
            f"Pixel area:          "
            f"{pixel_area_m2:.2f} m²"
        )

        print(
            f"Allowed area:        "
            f"{allowed_area_m2 / 1_000_000:.4f} km²"
        )

        print(
            f"Forbidden area:      "
            f"{forbidden_area_m2 / 1_000_000:.4f} km²"
        )

        # --------------------------------------------------------
        # Sanity checks
        # --------------------------------------------------------

        print("\n[5] SANITY CHECKS")
        print("-" * 70)

        if src.crs and src.crs.to_epsg() == 32643:
            print("✓ CRS is EPSG:32643.")
        else:
            print(
                f"⚠ WARNING: CRS is {src.crs}, "
                "expected EPSG:32643."
            )

        xres = abs(src.transform.a)
        yres = abs(src.transform.e)

        if (
            abs(xres - 10) < 0.01
            and abs(yres - 10) < 0.01
        ):
            print("✓ Resolution is approximately 10 m.")
        else:
            print(
                f"⚠ WARNING: Resolution is "
                f"{xres} x {yres} m."
            )

        unique = np.unique(data)

        print(
            f"Unique raster values: "
            f"{unique[:20]}"
        )

        # --------------------------------------------------------
        # Visualization
        # --------------------------------------------------------

        print("\n[6] GENERATING VISUALIZATION")
        print("-" * 70)

        display = data.astype(float)

        display[nodata_mask] = np.nan

        output_png.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        fig, ax = plt.subplots(
            figsize=(10, 8)
        )

        im = ax.imshow(
            display,
            vmin=0,
            vmax=1
        )

        ax.set_title(
            "Shuhul Hard Constraint Mask"
        )

        ax.set_xlabel("Column")
        ax.set_ylabel("Row")

        plt.colorbar(
            im,
            ax=ax,
            ticks=[0, 1],
            label="0 = Allowed, 1 = Forbidden"
        )

        plt.tight_layout()

        fig.savefig(
            output_png,
            dpi=200,
            bbox_inches="tight"
        )

        plt.close(fig)

        print(
            "✓ Visualization saved to:"
        )
        print(
            f"  {output_png}"
        )

    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)


def main():

    parser = argparse.ArgumentParser(
        description="Analyze Shuhul hard constraint mask."
    )

    parser.add_argument(
        "--file",
        required=True,
        help="Path to hard constraint TIFF."
    )

    parser.add_argument(
        "--output",
        default=None,
        help="Optional output PNG."
    )

    args = parser.parse_args()

    input_path = Path(args.file)

    if not input_path.exists():
        raise FileNotFoundError(
            f"File not found: {input_path}"
        )

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            input_path.parent
            / f"{input_path.stem}_analysis.png"
        )

    analyze(
        input_path,
        output_path
    )


if __name__ == "__main__":
    main()