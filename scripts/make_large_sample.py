"""Generate a large, realistic sales CSV for scale/performance testing.

Writes a CSV with realistic columns (region, date, amount, category,
quantity, customer) including some nulls and outliers, sized to prove the
~100MB / ~500k-row happy path holds the 30s budget over the FULL dataset.

The output file is intentionally large and MUST NOT be committed -- write
it under ``data/`` (gitignored) or a tmp path. See `.gitignore`.

Usage:
    uv run python scripts/make_large_sample.py [OUTPUT_PATH] [--rows N] [--seed S]

Defaults: OUTPUT_PATH=data/large_sample.csv, rows=500000, seed=42.
The default 500k rows produces roughly ~90MB.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_ROWS = 500_000
DEFAULT_OUTPUT = "data/large_sample.csv"

REGIONS = ["North", "South", "East", "West", "Central"]
CATEGORIES = ["Electronics", "Grocery", "Apparel", "Home", "Toys", "Sports"]
PRODUCTS = [
    "Wireless Noise-Cancelling Headphones",
    "Stainless Steel Insulated Water Bottle",
    "Organic Cotton Bath Towel Set",
    "4K Ultra HD Streaming Media Player",
    "Ergonomic Mesh Office Chair",
    "Ceramic Non-Stick Cookware Bundle",
    "Bluetooth Portable Party Speaker",
    "Memory Foam Contour Pillow",
]
NOTES = [
    "Standard fulfilment, no special handling required; shipped from the "
    "primary regional distribution centre.",
    "Customer requested gift wrapping and an expedited delivery window; "
    "a signature was required on delivery.",
    "Bulk purchase against a recurring quarterly procurement contract; "
    "volume-tier pricing, payment terms net 30.",
    "Return processed and restocked; refund issued after inspection "
    "confirmed resaleable condition.",
    "Promotional discount applied under the seasonal clearance campaign; "
    "transaction flagged for margin review.",
]


def build_dataframe(rows: int, seed: int) -> pd.DataFrame:
    """Build the sample DataFrame using vectorized numpy generation only."""
    rng = np.random.default_rng(seed)

    region = rng.choice(REGIONS, size=rows)
    category = rng.choice(CATEGORIES, size=rows)

    # Dates spread across ~2 years, ISO formatted.
    day_offsets = rng.integers(0, 730, size=rows)
    dates = (np.datetime64("2023-01-01") + day_offsets.astype("timedelta64[D]"))
    date_str = np.datetime_as_string(dates, unit="D")

    # Amounts: log-normal-ish, with a small fraction of extreme outliers.
    amount = rng.gamma(shape=2.0, scale=150.0, size=rows).round(2)
    outlier_mask = rng.random(rows) < 0.001
    amount[outlier_mask] = amount[outlier_mask] * rng.uniform(50, 200, size=outlier_mask.sum())
    amount = amount.round(2)

    quantity = rng.integers(1, 50, size=rows)

    customer_id = rng.integers(1, rows // 5 + 2, size=rows)
    customer = np.char.add("CUST-", customer_id.astype(str))

    product = rng.choice(PRODUCTS, size=rows)
    notes = rng.choice(NOTES, size=rows)

    df = pd.DataFrame(
        {
            "date": date_str,
            "region": region,
            "category": category,
            "customer": customer,
            "product": product,
            "quantity": quantity,
            "amount": amount,
            "notes": notes,
        }
    )

    # Inject ~2% nulls into the amount column so anomaly detection has signal.
    null_mask = rng.random(rows) < 0.02
    df.loc[null_mask, "amount"] = np.nan

    return df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", default=DEFAULT_OUTPUT, help="Output CSV path")
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS, help="Number of rows")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    args = parser.parse_args(argv)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = build_dataframe(args.rows, args.seed)
    df.to_csv(out_path, index=False)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Wrote {len(df):,} rows x {len(df.columns)} cols -> {out_path} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
