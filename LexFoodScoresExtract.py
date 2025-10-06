#!/usr/bin/env python3
"""
extract_inspections.py

Dependencies:
    pip install pandas tabula-py pdfplumber
    * tabula-py requires Java (make sure `java` is on your PATH).

Usage:
    python extract_inspections.py \
        --scores-pdf Food-Retail_Inspections-06.2024-06.2025.pdf \
        --scores-csv food_scores.csv
"""

import os
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


def main():
    parser = argparse.ArgumentParser(
        description="Extract food inspection scores from PDF"
    )
    parser.add_argument("--scores-pdf",    default="Food-Retail_Inspections-06.2024-06.2025.pdf",
                        help="Path to the food-scores PDF")
    parser.add_argument("--scores-csv",    default="food_scores.csv",
                        help="Output CSV for the scores data")
    parser.add_argument("--scrape-date",   default=None,
                        help="Date of the scrape (YYYY-MM-DD). Defaults to today.")
    args = parser.parse_args()

    if not os.path.isfile(args.scores_pdf):
        raise FileNotFoundError(f"Scores PDF not found: {args.scores_pdf}")

    extract_scores(args.scores_pdf, args.scores_csv, args.scrape_date)
    print("[SUCCESS] All done! Data extracted to 'food_scores.csv'.")

if __name__ == "__main__":
    main()
