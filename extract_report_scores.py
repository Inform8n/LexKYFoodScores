#!/usr/bin/env python3
"""
extract_report_scores.py

Reads the LFCHD food establishment inspection score report (Excel) and appends
it to the raw scores CSV in the same 12-column layout the old PDF extractor
produced, so transform_food_scores.py and JoinScoresViolations.py keep working
unchanged.

The Excel report does not carry a street address or the Food/Retail flag that
the PDF did, so both are backfilled from the existing published dataset by
Permit #. Establishments that have never been seen before get a blank address.

Usage:
    python extract_report_scores.py \
        --report Reports/Report_53_Jul-Dec_2025_establishments.xlsx \
        --scores-csv food_scores.csv
"""

import argparse
import os
import sys
from datetime import datetime
from typing import Optional

import pandas as pd

# Column layout of the raw scores CSV, as written by the original Camelot
# extractor. The first eight columns are positional and unnamed.
RAW_COLUMNS = ['0', '1', '2', '3', '4', '5', '6', '7',
               'ScrapeDate', 'Page', 'Table', 'SourceFile']

# Violation code 0 is LFCHD's "no violation" placeholder, not a real code --
# it has no entry in CodeViolations.csv.
PLACEHOLDER_CODE = '0'


def normalize(name: str) -> str:
    """Reduce a column header to lowercase alphanumerics for fuzzy matching."""
    return ''.join(ch for ch in str(name).lower() if ch.isalnum())


def find_column(columns: list, *keywords: str) -> Optional[int]:
    """Return the index of the first column whose header contains all keywords."""
    for idx, col in enumerate(columns):
        norm = normalize(col)
        if all(kw in norm for kw in keywords):
            return idx
    return None


def require_column(columns: list, label: str, *keywords: str) -> int:
    """Like find_column, but fail loudly if the column is missing."""
    idx = find_column(columns, *keywords)
    if idx is None:
        print(f"[ERROR] Could not find the {label} column in the report.")
        print(f"        Columns present: {list(columns)}")
        print("        LFCHD has probably changed the report layout.")
        sys.exit(1)
    return idx


def parse_violations(raw) -> str:
    """Convert LFCHD's 'code/points' pairs into space-separated bare codes.

    '17/1 50/1 56/1 9/2' -> '17 50 56 9'
    """
    if pd.isna(raw):
        return ''
    codes = []
    for token in str(raw).split():
        code = token.split('/')[0].strip()
        if code and code != PLACEHOLDER_CODE:
            codes.append(code)
    return ' '.join(codes)


def load_backfill(history_csv: str) -> pd.DataFrame:
    """Build a Permit # -> (Address, Food or Retail) lookup from published data."""
    if not os.path.isfile(history_csv):
        print(f"[WARNING] {history_csv} not found - addresses will be blank")
        return pd.DataFrame(columns=['Permit #', 'Address', 'Food or Retail'])

    hist = pd.read_csv(history_csv, dtype={'Permit #': str}, low_memory=False)
    missing = [c for c in ('Permit #', 'Address', 'Food or Retail') if c not in hist.columns]
    if missing:
        print(f"[WARNING] {history_csv} missing columns {missing} - addresses will be blank")
        return pd.DataFrame(columns=['Permit #', 'Address', 'Food or Retail'])

    # Most recent record per permit wins, so a relocated establishment keeps its
    # latest known address.
    if 'Date' in hist.columns:
        hist = hist.sort_values('Date')
    lookup = (hist[['Permit #', 'Address', 'Food or Retail']]
              .dropna(subset=['Permit #'])
              .drop_duplicates(subset=['Permit #'], keep='last'))

    print(f"[INFO] Loaded addresses for {len(lookup):,} known establishments")
    return lookup


def extract(report_path: str, output_csv: str, history_csv: str,
            scrape_date: Optional[str] = None):
    if scrape_date is None:
        scrape_date = datetime.now().strftime('%Y-%m-%d')

    print(f">> Reading inspection report '{report_path}'...")
    print(f"Scrape date: {scrape_date}")

    try:
        book = pd.ExcelFile(report_path)
    except Exception as e:
        print(f"[ERROR] Could not open the report: {e}")
        sys.exit(1)

    sheet = 'Establishments' if 'Establishments' in book.sheet_names else book.sheet_names[0]
    df = book.parse(sheet)
    print(f"[INFO] Sheet '{sheet}': {len(df):,} rows, {len(df.columns)} columns")

    if df.empty:
        print("[ERROR] The report contains no rows.")
        sys.exit(1)

    cols = list(df.columns)
    i_permit = require_column(cols, 'permit number', 'permit')
    i_city = require_column(cols, 'city/ZIP', 'city')
    i_type = require_column(cols, 'inspection type', 'inspection', 'type')
    i_date = require_column(cols, 'inspection date', 'date')
    i_score = require_column(cols, 'score', 'score')
    i_viol = require_column(cols, 'violations', 'violation')

    # The establishment name is split across the columns between Permit # and
    # City/ZIP ('Name', 'Type', 'Name.1'); the last of them holds the full name.
    name_cols = cols[i_permit + 1:i_city]
    if not name_cols:
        print("[ERROR] Could not locate the establishment name columns.")
        print(f"        Columns present: {cols}")
        sys.exit(1)

    full_name = df[name_cols[-1]].astype(str).str.strip()
    if len(name_cols) > 1:
        # Fall back to joining the parts wherever the combined column is blank.
        parts = (df[name_cols[:-1]].fillna('').astype(str)
                 .agg(' '.join, axis=1).str.strip().str.replace(r'\s+', ' ', regex=True))
        blank = full_name.isin(['', 'nan'])
        full_name = full_name.mask(blank, parts)

    out = pd.DataFrame({
        '0': df[cols[i_permit]].astype(str).str.strip(),
        '1': full_name,
        '2': '',  # Address - backfilled below
        '3': pd.to_datetime(df[cols[i_date]], errors='coerce').dt.strftime('%Y-%m-%d'),
        '4': df[cols[i_type]].fillna('').astype(str).str.strip(),
        '5': '',  # Food or Retail - backfilled below
        '6': df[cols[i_score]],
        '7': df[cols[i_viol]].apply(parse_violations),
        'ScrapeDate': scrape_date,
        'Page': '',   # No page/table concept in a spreadsheet source
        'Table': '',
        'SourceFile': os.path.basename(report_path),
    })

    # Drop rows without a usable permit number or inspection date.
    before = len(out)
    out = out[out['0'].str.match(r'^\d+$', na=False)]
    out = out.dropna(subset=['3'])
    if len(out) != before:
        print(f"[INFO] Skipped {before - len(out):,} rows with no permit number or date")

    # Backfill address and Food/Retail from the published dataset by Permit #.
    lookup = load_backfill(history_csv)
    if not lookup.empty:
        merged = out.merge(lookup, how='left', left_on='0', right_on='Permit #')
        out['2'] = merged['Address'].fillna('').values
        out['5'] = merged['Food or Retail'].fillna('').values
        matched = (out['2'] != '').sum()
        print(f"[INFO] Backfilled addresses for {matched:,} of {len(out):,} rows "
              f"({len(out) - matched:,} establishments are new)")

    out = out[RAW_COLUMNS]

    # Append to the raw CSV so history across reporting periods accumulates;
    # transform_food_scores.py deduplicates the combined result.
    first_write = not os.path.exists(output_csv)
    out.to_csv(output_csv, mode='a', header=first_write, index=False)

    action = "Wrote" if first_write else "Appended"
    print(f"[SUCCESS] {action} {len(out):,} rows to '{output_csv}'")
    print(f"          Inspection dates {out['3'].min()} to {out['3'].max()}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract food inspection scores from the LFCHD Excel report"
    )
    parser.add_argument("--report", required=True,
                        help="Path to the downloaded inspection score report (.xlsx)")
    parser.add_argument("--scores-csv", default="food_scores.csv",
                        help="Raw output CSV for the scores data")
    parser.add_argument("--history-csv", default="joined_scores_violations.csv",
                        help="Published dataset used to backfill street addresses")
    parser.add_argument("--scrape-date", default=None,
                        help="Date of the scrape (YYYY-MM-DD). Defaults to today.")
    args = parser.parse_args()

    if not os.path.isfile(args.report):
        print(f"[ERROR] Report not found: {args.report}")
        sys.exit(1)

    extract(args.report, args.scores_csv, args.history_csv, args.scrape_date)
    print(f"[SUCCESS] All done! Data extracted to '{args.scores_csv}'.")


if __name__ == "__main__":
    main()
