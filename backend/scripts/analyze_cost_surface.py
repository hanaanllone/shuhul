from pathlib import Path
import argparse

import numpy as np
import rasterio
import matplotlib.pyplot as plt


def analyze(path: Path, output_png: Path):

    print("\n" + "=" * 70)
    print("TSHAAI COST SURFACE ANALYSIS")
    print("=" * 70)

    with rasterio.open(path) as src:

        data = src.read(1).astype(np.float32)

        # ------------------------------------------------------------
        # Basic raster information
        # ------------------------------------------------------------

        print("\n[1] RASTER INFORMATION")
        print("-" * 70)

        print(f"File:              {path}")
        print(f"CRS:               {src.crs}")
        print(f"Width:             {src.width}")
        print(f"Height:            {src.height}")
        print(f"Resolution:        {src.res}")
        print(f"Bounds:            {src.bounds}")
        print(f"Transform:         {src.transform}")
        print(f"NoData:            {src.nodata}")

        # ------------------------------------------------------------
        # Valid pixels
        # ------------------------------------------------------------

        if src.nodata is not None:
            valid = data[data != src.nodata]
        else:
            valid = data[np.isfinite(data)]

        valid = valid[np.isfinite(valid)]

        if len(valid) == 0:
            raise ValueError("No valid pixels found.")

        print("\n[2] COST STATISTICS")
        print("-" * 70)

        print(f"Valid pixels:      {len(valid):,}")
        print(f"Minimum:           {np.min(valid):.4f}")
        print(f"Maximum:           {np.max(valid):.4f}")
        print(f"Mean:              {np.mean(valid):.4f}")
        print(f"Median:            {np.median(valid):.4f}")
        print(f"Std deviation:     {np.std(valid):.4f}")

        print("\nPercentiles:")
        for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
            print(
                f"  P{p:02d}:             "
                f"{np.percentile(valid, p):.4f}"
            )

        # ------------------------------------------------------------
        # Cost categories
        # ------------------------------------------------------------

        print("\n[3] COST DISTRIBUTION")
        print("-" * 70)

        categories = {
            "Very Low (0-20)": (0, 20),
            "Low (20-40)": (20, 40),
            "Medium (40-60)": (40, 60),
            "High (60-80)": (60, 80),
            "Very High (80-100)": (80, 100),
        }

        for name, (low, high) in categories.items():

            if high == 100:
                mask = (valid >= low) & (valid <= high)
            else:
                mask = (valid >= low) & (valid < high)

            count = np.sum(mask)
            percentage = (count / len(valid)) * 100

            print(
                f"{name:<22} "
                f"{count:>10,} pixels "
                f"({percentage:6.2f}%)"
            )

        # ------------------------------------------------------------
        # Extreme pixels
        # ------------------------------------------------------------

        print("\n[4] EXTREME AREAS")
        print("-" * 70)

        low_threshold = np.percentile(valid, 10)
        high_threshold = np.percentile(valid, 90)

        low_count = np.sum(valid <= low_threshold)
        high_count = np.sum(valid >= high_threshold)

        print(
            f"Bottom 10% threshold: {low_threshold:.4f}"
        )
        print(
            f"Top 10% threshold:    {high_threshold:.4f}"
        )

        print(
            f"Low-cost pixels:      {low_count:,} "
            f"({low_count / len(valid) * 100:.2f}%)"
        )

        print(
            f"High-cost pixels:     {high_count:,} "
            f"({high_count / len(valid) * 100:.2f}%)"
        )

        # ------------------------------------------------------------
        # Check expected range
        # ------------------------------------------------------------

        print("\n[5] SANITY CHECKS")
        print("-" * 70)

        if np.min(valid) < 0:
            print("⚠ WARNING: Cost values below 0 detected.")
        else:
            print("✓ No negative cost values.")

        if np.max(valid) > 100:
            print("⚠ WARNING: Cost values above 100 detected.")
        else:
            print("✓ Maximum cost is within 0-100.")

        if src.crs and src.crs.to_epsg() == 32643:
            print("✓ CRS is EPSG:32643.")
        else:
            print(
                f"⚠ WARNING: CRS is {src.crs}, "
                "expected EPSG:32643."
            )

        xres = abs(src.transform.a)
        yres = abs(src.transform.e)

        if abs(xres - 10) < 0.01 and abs(yres - 10) < 0.01:
            print("✓ Resolution is approximately 10 m.")
        else:
            print(
                f"⚠ WARNING: Resolution is "
                f"{xres} x {yres} m, expected ~10 x 10 m."
            )

        # ------------------------------------------------------------
        # Histogram
        # ------------------------------------------------------------

        print("\n[6] GENERATING VISUALIZATION")
        print("-" * 70)

        output_png.parent.mkdir(parents=True, exist_ok=True)

        fig, axes = plt.subplots(
            1,
            2,
            figsize=(16, 7)
        )

        # Spatial cost surface
        display = data.copy()

        if src.nodata is not None:
            display[display == src.nodata] = np.nan

        im = axes[0].imshow(
            display,
            vmin=0,
            vmax=100
        )

        axes[0].set_title(
            "Tshaai Environmental Cost Surface"
        )

        axes[0].set_xlabel("Column")
        axes[0].set_ylabel("Row")

        plt.colorbar(
            im,
            ax=axes[0],
            label="Planning Cost (0 = lower, 100 = higher)"
        )

        # Histogram
        axes[1].hist(
            valid,
            bins=50
        )

        axes[1].set_title(
            "Cost Distribution"
        )

        axes[1].set_xlabel(
            "Planning Cost"
        )

        axes[1].set_ylabel(
            "Number of Pixels"
        )

        axes[1].grid(
            alpha=0.25
        )

        fig.suptitle(
            f"Tshaai Cost Surface — {path.stem}",
            fontsize=15
        )

        plt.tight_layout()

        fig.savefig(
            output_png,
            dpi=200,
            bbox_inches="tight"
        )

        plt.close(fig)

        print(f"✓ Visualization saved to:")
        print(f"  {output_png}")

    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)


def main():

    parser = argparse.ArgumentParser(
        description="Analyze a Tshaai cost surface."
    )

    parser.add_argument(
        "--file",
        required=True,
        help="Path to the cost surface TIFF."
    )

    parser.add_argument(
        "--output",
        default=None,
        help="Optional output PNG path."
    )

    args = parser.parse_args()

    input_path = Path(args.file)

    if not input_path.exists():
        raise FileNotFoundError(
            f"Cost surface not found: {input_path}"
        )

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            input_path.parent /
            f"{input_path.stem}_analysis.png"
        )

    analyze(
        input_path,
        output_path
    )


if __name__ == "__main__":
    main()