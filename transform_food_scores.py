#!/usr/bin/env python3
"""
transform_food_scores.py

Reads the raw food_scores CSV, renames the first 8 columns to meaningful headers,
filters out extraneous header rows or non-data rows, and writes a cleaned CSV.

Usage:
    python transform_food_scores.py \
        --input food_scores.csv \
        --output food_scores_clean.csv
"""
import pandas as pd
import argparse
import os
import sys

DEFAULT_HEADERS = [
    "Permit #",
    "Establishment Name",
    "Address",
    "Date",
    "Inspection Type",
    "Food or Retail",
    "Score",
    "Violations",
    "ScrapeDate",
    "Page",
    "Table",
    "SourceFile",
]


def transform(input_csvs, output_csv: str, establishments_csv: str = "establishments.csv"):
    # Read every raw CSV. There are normally two: food_scores.csv, which the
    # nightly pipeline appends to, and food_scores_history.csv from the one-off
    # backfill. Keeping them separate means re-running either is idempotent.
    if isinstance(input_csvs, str):
        input_csvs = [input_csvs]

    frames = []
    for path in input_csvs:
        part = pd.read_csv(path, dtype=str)
        print(f"[INFO] Read {len(part):,} raw rows from '{path}'")
        frames.append(part)
    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]

    # Ensure there are at least 12 columns
    if df.shape[1] < len(DEFAULT_HEADERS):
        print(f"Error: expected at least {len(DEFAULT_HEADERS)} columns, found {df.shape[1]}", file=sys.stderr)
        sys.exit(1)

    # Select and rename the first 12 columns
    data = df.iloc[:, : len(DEFAULT_HEADERS)].copy()
    data.columns = DEFAULT_HEADERS

    # Drop rows where Permit # is not purely numeric
    data = data[data['Permit #'].str.match(r'^\d+$')]

    # Parse date columns. format='mixed' parses each value on its own terms --
    # the raw CSV accumulates across source formats (the old PDF wrote
    # '23-Aug-2024', the Excel report writes '2025-07-02'), and without this
    # pandas infers a single format from the first row and silently coerces
    # every differently-formatted date to NaT.
    data['Date'] = pd.to_datetime(data['Date'], errors='coerce', format='mixed')
    data['ScrapeDate'] = pd.to_datetime(data['ScrapeDate'], errors='coerce', format='mixed')

    # Drop rows with invalid dates, but say so -- a sudden spike here means the
    # upstream date format changed again.
    invalid_dates = int(data['Date'].isna().sum())
    if invalid_dates:
        print(f"[WARNING] Dropping {invalid_dates:,} rows with unparseable dates")
    data = data.dropna(subset=['Date'])

    # Pivot multiple violations (space-separated) into individual rows
    data['Violations'] = data['Violations'].fillna('').str.split()  # multiple codes to list
    data = data.explode('Violations')
    # Remove any empty violations entries
    data = data[data['Violations'] != '']

    # Remove duplicates (can happen during PDF extraction or re-scraping).
    # The key is deliberately Permit #, not Establishment Name: LFCHD truncates
    # names at different widths in different eras ("LEXINGTON GRIFFIN GATE
    # MARRIOTT MAIN KITCHEN" vs "...MARRIOTT MAIN"), so keying on the name lets
    # the same inspection survive twice and makes the output churn whenever a
    # new source file supplies a different truncation. The permit number is the
    # stable identifier; inspection type separates a same-day regular from a
    # follow-up.
    before_dedup = len(data)
    data = data.drop_duplicates(subset=['Permit #', 'Date', 'Inspection Type', 'Violations'])
    after_dedup = len(data)
    if before_dedup != after_dedup:
        print(f"[INFO] Removed {before_dedup - after_dedup:,} duplicate records")

    # One permit should show one name. Without this the same establishment
    # appears under several source-side truncations, which breaks grouping and
    # display even though Permit # is what actually identifies it.
    if establishments_csv and os.path.isfile(establishments_csv):
        est = pd.read_csv(establishments_csv, dtype=str)
        canon = est.dropna(subset=['Permit #']).set_index('Permit #')['Establishment Name']
        mapped = data['Permit #'].map(canon)
        changed = int((mapped.notna() & (mapped != data['Establishment Name'])).sum())
        data['Establishment Name'] = mapped.fillna(data['Establishment Name'])
        print(f"[INFO] Canonicalised establishment names on {changed:,} rows "
              f"using '{establishments_csv}'")

    # Write cleaned CSV
    data.to_csv(output_csv, index=False)
    print(f"[SUCCESS] Cleaned data written to '{output_csv}' ({after_dedup:,} records)")


def main():
    parser = argparse.ArgumentParser(
        description="Transform raw food_scores CSV into cleaned data with proper headers"
    )
    parser.add_argument(
        "--input", required=True, nargs='+',
        help="Raw input CSV file(s), e.g. food_scores.csv food_scores_history.csv"
    )
    parser.add_argument(
        "--output", required=True, help="Output cleaned CSV file"
    )
    parser.add_argument(
        "--establishments", default="establishments.csv",
        help="Lookup used to give each Permit # a single canonical name"
    )
    args = parser.parse_args()

    transform(args.input, args.output, args.establishments)


if __name__ == '__main__':
    main()
