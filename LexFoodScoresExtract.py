#!/usr/bin/env python3
"""
extract_inspections.py

Dependencies:
    pip install pandas tabula-py pdfplumber
    * tabula-py requires Java (make sure `java` is on your PATH).

Usage:
    python extract_inspections.py \
        --scores-pdf Food-Retail_Inspections-06.2024-06.2025.pdf \
        --form-pdf 2585_001.pdf \
        --scores-csv food_scores.csv \
        --infractions-csv infractions.csv
"""

import os
import re
import pandas as pd
import camelot  # type: ignore
import pdfplumber
import argparse
from datetime import datetime
from typing import Optional

def extract_scores(pdf_path: str, output_csv: str, scrape_date: Optional[str] = None):
    print(f">> Extracting food scores from '{pdf_path}'...")
    # Use provided scrape_date or default to today
    if scrape_date is None:
        scrape_date = datetime.now().strftime('%Y-%m-%d')
    print(f"Scrape date: {scrape_date}")

    # Check if file exists to determine if we need headers
    first_write = not os.path.exists(output_csv)
    # determine total_pages via pdfplumber
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
    except Exception:
        total_pages = 0
    if total_pages < 1:
        raise RuntimeError(f"No pages found in PDF: {pdf_path}")
    # per-page extraction with Camelot
    for page_num in range(1, total_pages + 1):
        print(f"Camelot: reading page {page_num}/{total_pages}...")
        tables = camelot.read_pdf(pdf_path, pages=str(page_num), flavor='lattice')  # type: ignore[reportPrivateImportUsage]
        print(f"Camelot page {page_num} returned {len(tables)} tables")
        for table_idx, table in enumerate(tables, start=1):
            df_page = table.df  # type: ignore
            df_page["ScrapeDate"] = scrape_date  # type: ignore[attr-defined]
            df_page["Page"] = page_num  # type: ignore[attr-defined]
            df_page["Table"] = table_idx  # type: ignore[attr-defined]
            df_page["SourceFile"] = os.path.basename(pdf_path)  # type: ignore[attr-defined]
            df_page.to_csv(output_csv, mode="a", header=first_write, index=False)  # type: ignore[attr-defined]
            print(f"Appended page {page_num} table {table_idx} to '{output_csv}'")
            first_write = False
    print(f"Finished writing all tables to '{output_csv}'")
    return
    for idx, df in enumerate(tables, start=1):
        rows, cols_count = df.shape if hasattr(df, 'shape') else (None, None)  # type: ignore
        print(f">> Processing table {idx}: {rows} rows x {cols_count} cols")
        # log column names for debug
        try:
            col_list = [str(c) for c in df.columns]  # type: ignore[attr-defined]
        except Exception:
            col_list = []
        print(f"    columns: {col_list}")
        # detect if this table looks like the inspection table
        cols = [str(c).lower() for c in df.columns]  # type: ignore[attr-defined]
        if any("score" in c for c in cols) and any("permit" in c for c in cols):
            print(f"    ++ Table {idx} matched (contains 'score' and 'permit')")
            dfs.append(df)

    if not dfs:
        raise RuntimeError("No table containing both 'Permit' and 'Score' columns was found.")

    # concatenate all pages
    combined = pd.concat(dfs, ignore_index=True)

    # sometimes the first row is a repeat of the header
    # detect if row-0 contains headers
    first_row = combined.iloc[0].astype(str).str.lower()
    if any("score" in cell for cell in first_row):
        combined.columns = combined.iloc[0]
        combined = combined.drop(0).reset_index(drop=True)

    # clean up column names
    combined.columns = [str(col).strip() for col in combined.columns]

    # convert date columns
    for col in combined.columns:
        if "date" in col.lower():
            combined[col] = pd.to_datetime(combined[col], errors="coerce")

    # convert Score to numeric
    if "Score" in combined.columns:
        combined["Score"] = pd.to_numeric(combined["Score"], errors="coerce")

    combined.to_csv(output_csv, index=False)
    print(f"[SUCCESS] Saved food scores to '{output_csv}'")


def extract_infractions(pdf_path: str, output_csv: str):
    print(f">> Extracting infractions from form '{pdf_path}'...")
    data = []
    # pattern: code like "3-301.11" followed by description
    pattern = re.compile(r"([0-9]+-[0-9]+\.[0-9]+)\s+(.+)")
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for line in text.split("\n"):
                m = pattern.match(line.strip())
                if m:
                    code, desc = m.groups()
                    data.append({
                        "InfractionCode": code,
                        "Description": desc.strip(),
                        "Page": page_num
                    })

    if not data:
        print(f"[WARNING] No infraction codes detected in '{pdf_path}'. Writing empty infractions CSV.")
        infractions_df = pd.DataFrame([], columns=["InfractionCode", "Description", "Page"])
        infractions_df.to_csv(output_csv, index=False)
        return

    infractions_df = pd.DataFrame(data)
    infractions_df.to_csv(output_csv, index=False)
    print(f"[SUCCESS] Saved infractions list to '{output_csv}'")


def main():
    parser = argparse.ArgumentParser(
        description="Extract food inspection scores and infraction codes from PDFs"
    )
    parser.add_argument("--scores-pdf",    default="Food-Retail_Inspections-06.2024-06.2025.pdf",
                        help="Path to the food-scores PDF")
    parser.add_argument("--form-pdf",      default="2585_001.pdf",
                        help="Path to the infractions form PDF")
    parser.add_argument("--scores-csv",    default="food_scores.csv",
                        help="Output CSV for the scores data")
    parser.add_argument("--infractions-csv", default="infractions.csv",
                        help="Output CSV for the infractions lookup table")
    parser.add_argument("--scrape-date",   default=None,
                        help="Date of the scrape (YYYY-MM-DD). Defaults to today.")
    args = parser.parse_args()

    if not os.path.isfile(args.scores_pdf):
        raise FileNotFoundError(f"Scores PDF not found: {args.scores_pdf}")
    if not os.path.isfile(args.form_pdf):
        raise FileNotFoundError(f"Form PDF not found: {args.form_pdf}")

    extract_scores(args.scores_pdf, args.scores_csv, args.scrape_date)
    extract_infractions(args.form_pdf, args.infractions_csv)
    print("[SUCCESS] All done! You can now join 'food_scores.csv' with 'infractions.csv' on the InfractionCode column.")

if __name__ == "__main__":
    main()
