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
]


def transform(input_csv: str, output_csv: str):
    # Read the raw CSV
    df = pd.read_csv(input_csv, dtype=str)

    # Ensure there are at least 8 columns
    if df.shape[1] < len(DEFAULT_HEADERS):
        print(f"Error: expected at least {len(DEFAULT_HEADERS)} columns, found {df.shape[1]}", file=sys.stderr)
        sys.exit(1)

    # Select and rename the first 8 columns
    data = df.iloc[:, : len(DEFAULT_HEADERS)].copy()
    data.columns = DEFAULT_HEADERS

    # Drop rows where Permit # is not purely numeric
    data = data[data['Permit #'].str.match(r'^\d+$')]

    # Parse date column
    data['Date'] = pd.to_datetime(data['Date'], errors='coerce')

    # Optionally drop rows with invalid dates
    data = data.dropna(subset=['Date'])

    # Pivot multiple violations (space-separated) into individual rows
    data['Violations'] = data['Violations'].fillna('').str.split()  # multiple codes to list
    data = data.explode('Violations')
    # Remove any empty violations entries
    data = data[data['Violations'] != '']

    # Write cleaned CSV
    data.to_csv(output_csv, index=False)
    print(f"✅ Cleaned data written to '{output_csv}'")


def main():
    parser = argparse.ArgumentParser(
        description="Transform raw food_scores CSV into cleaned data with proper headers"
    )
    parser.add_argument(
        "--input", required=True, help="Raw input CSV file (e.g., food_scores.csv)"
    )
    parser.add_argument(
        "--output", required=True, help="Output cleaned CSV file"
    )
    args = parser.parse_args()

    transform(args.input, args.output)


if __name__ == '__main__':
    main()
