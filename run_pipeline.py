#!/usr/bin/env python3
"""
run_pipeline.py

Orchestrator script that runs the complete food inspection data pipeline:
1. Extract data from PDF
2. Clean and transform the data
3. Join with violation descriptions

Usage:
    python run_pipeline.py --scores-pdf "Food-Retail_Inspections-06.2024-06.2025.pdf"

    Optional arguments:
    --scrape-date YYYY-MM-DD  Date of the scrape (defaults to today)
"""

import argparse
import subprocess
import sys
import os
import shutil
from datetime import datetime


def run_command(description: str, command: list):
    """Run a command and handle errors."""
    print(f"\n{'='*60}")
    print(f">> {description}")
    print(f"{'='*60}")
    print(f"Command: {' '.join(command)}\n")

    result = subprocess.run(command, capture_output=False, text=True)

    if result.returncode != 0:
        print(f"\n[ERROR] {description} failed with exit code {result.returncode}")
        sys.exit(1)

    print(f"\n[SUCCESS] {description} completed successfully!")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run the complete food inspection data pipeline"
    )
    parser.add_argument(
        "--scores-pdf",
        default=None,
        help="Path to the food-scores PDF (if not provided, will download latest)"
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the latest PDF before processing"
    )
    parser.add_argument(
        "--scrape-date",
        default=None,
        help="Date of the scrape (YYYY-MM-DD). Defaults to today."
    )
    parser.add_argument(
        "--scores-csv",
        default="food_scores.csv",
        help="Output CSV for raw scores data"
    )
    parser.add_argument(
        "--cleaned-csv",
        default="food_scores_cleaned.csv",
        help="Output CSV for cleaned data"
    )

    args = parser.parse_args()

    # Download PDF if requested or if no PDF specified
    if args.download or args.scores_pdf is None:
        print("\n>> Downloading latest PDF from LFCHD website...")
        download_cmd = ["python", "download_pdf.py"]
        result = subprocess.run(download_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"[ERROR] Failed to download PDF: {result.stderr}")
            sys.exit(1)

        print(result.stdout)

        # Find the downloaded PDF in PDFs directory
        pdf_dir = "PDFs"
        if os.path.isdir(pdf_dir):
            # Look for the most recent non-timestamped PDF
            pdfs = [f for f in os.listdir(pdf_dir) if f.endswith('.pdf') and '_' not in f]
            if pdfs:
                args.scores_pdf = os.path.join(pdf_dir, pdfs[0])
                print(f"[SUCCESS] Using downloaded PDF: {args.scores_pdf}")
            else:
                print("[ERROR] No PDF found in PDFs directory after download")
                sys.exit(1)
        else:
            print("[ERROR] PDFs directory not found after download")
            sys.exit(1)

    # Validate input files exist
    if not os.path.isfile(args.scores_pdf):
        print(f"[ERROR] Scores PDF not found: {args.scores_pdf}")
        print("Tip: Use --download to automatically download the latest PDF")
        sys.exit(1)

    # Display pipeline info
    scrape_date = args.scrape_date or datetime.now().strftime('%Y-%m-%d')
    print("\n" + "="*60)
    print("FOOD INSPECTION DATA PIPELINE")
    print("="*60)
    print(f"Scores PDF:     {args.scores_pdf}")
    print(f"Scrape Date:    {scrape_date}")
    print(f"Output CSV:     joined_scores_violations.csv")
    print("="*60)

    # Step 1: Extract data from PDF
    extract_cmd = [
        "python", "LexFoodScoresExtract.py",
        "--scores-pdf", args.scores_pdf,
        "--scores-csv", args.scores_csv,
    ]
    if args.scrape_date:
        extract_cmd.extend(["--scrape-date", args.scrape_date])

    run_command("Step 1: Extract data from PDF", extract_cmd)

    # Step 2: Transform and clean data
    transform_cmd = [
        "python", "transform_food_scores.py",
        "--input", args.scores_csv,
        "--output", args.cleaned_csv
    ]
    run_command("Step 2: Transform and clean data", transform_cmd)

    # Step 3: Join with violation descriptions
    join_cmd = [
        "python", "JoinScoresViolations.py"
    ]
    run_command("Step 3: Join with violation descriptions", join_cmd)

    # Move PDFs to PDFs directory if they're not already there
    pdf_dir = "PDFs"
    os.makedirs(pdf_dir, exist_ok=True)

    # Move scores PDF if needed
    if not args.scores_pdf.startswith(pdf_dir):
        pdf_basename = os.path.basename(args.scores_pdf)
        target_path = os.path.join(pdf_dir, pdf_basename)
        if os.path.exists(args.scores_pdf) and not os.path.exists(target_path):
            print(f"\n>> Moving {pdf_basename} to {pdf_dir}/")
            shutil.move(args.scores_pdf, target_path)
            print(f"[SUCCESS] Moved to {target_path}")

    # Final summary
    print("\n" + "="*60)
    print("PIPELINE COMPLETED SUCCESSFULLY!")
    print("="*60)
    print(f"\nFinal output: joined_scores_violations.csv")

    # Show some stats if the file exists
    if os.path.isfile("joined_scores_violations.csv"):
        import pandas as pd
        df = pd.read_csv("joined_scores_violations.csv")
        print(f"\nDataset statistics:")
        print(f"  Total records:        {len(df):,}")
        print(f"  Unique establishments: {df['Permit #'].nunique():,}")
        print(f"  Date range:           {df['Date'].min()} to {df['Date'].max()}")
        if 'ScrapeDate' in df.columns:
            print(f"  Scrape dates:         {df['ScrapeDate'].nunique()} unique dates")

    print("\nReady for analysis!\n")


if __name__ == "__main__":
    main()
