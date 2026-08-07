#!/usr/bin/env python3
"""
run_pipeline.py

Orchestrator script that runs the complete food inspection data pipeline:
1. Download the latest inspection score report from LFCHD
2. Extract the data
3. Clean and transform the data
4. Join with violation descriptions
5. Optionally sync to Google Sheets

Usage:
    python run_pipeline.py
    python run_pipeline.py --report "Reports/Report_53_Jul-Dec_2025_establishments.xlsx"

    Optional arguments:
    --force                   Reprocess even if the report is unchanged
    --scrape-date YYYY-MM-DD  Date of the scrape (defaults to today)
"""

import argparse
import os
import subprocess
import sys
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


def download_report(force: bool) -> str:
    """Download the latest report. Returns its path, or exits if nothing is new."""
    print("\n>> Downloading latest inspection report from LFCHD website...")

    command = [sys.executable, "download_report.py"]
    if force:
        command.append("--force")

    result = subprocess.run(command, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        print("[ERROR] Failed to download the inspection report")
        sys.exit(1)

    # download_report.py emits a machine-readable CURRENT_REPORT=<path> line.
    report_path = None
    for line in result.stdout.splitlines():
        if line.startswith("CURRENT_REPORT="):
            report_path = line.split("=", 1)[1].strip()

    if not report_path:
        print("[ERROR] Downloader did not report which file is current")
        sys.exit(1)

    if "NO UPDATE NEEDED" in result.stdout and not force:
        print("[INFO] No new data to process. Exiting.")
        sys.exit(0)

    print(f"[SUCCESS] Using report: {report_path}")
    return report_path


def main():
    parser = argparse.ArgumentParser(
        description="Run the complete food inspection data pipeline"
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Path to an inspection score report (if omitted, downloads the latest)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess even if the online report is unchanged"
    )
    parser.add_argument(
        "--scrape-date",
        default=None,
        help="Date of the scrape (YYYY-MM-DD). Defaults to today."
    )
    parser.add_argument(
        "--skip-site",
        action="store_true",
        help="Skip rebuilding the static site's data files"
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
    parser.add_argument(
        "--history-csv",
        default="food_scores_history.csv",
        help="Backfilled historical raw data, folded in when present"
    )

    args = parser.parse_args()

    if args.report is None:
        args.report = download_report(args.force)

    if not os.path.isfile(args.report):
        print(f"[ERROR] Report not found: {args.report}")
        sys.exit(1)

    scrape_date = args.scrape_date or datetime.now().strftime('%Y-%m-%d')
    print("\n" + "="*60)
    print("FOOD INSPECTION DATA PIPELINE")
    print("="*60)
    print(f"Report:         {args.report}")
    print(f"Scrape Date:    {scrape_date}")
    print(f"Output CSV:     joined_scores_violations.csv")
    print("="*60)

    # Step 1: Extract data from the report
    extract_cmd = [
        sys.executable, "extract_report_scores.py",
        "--report", args.report,
        "--scores-csv", args.scores_csv,
        "--scrape-date", scrape_date,
    ]
    run_command("Step 1: Extract data from report", extract_cmd)

    # Step 2: Transform and clean data.
    # The backfilled history (produced once by backfill_history.py) is a separate
    # raw file so that re-running either it or the nightly extract stays
    # idempotent; both are fed to the transform together.
    raw_inputs = [args.scores_csv]
    if os.path.isfile(args.history_csv):
        raw_inputs.append(args.history_csv)
    else:
        print(f"\n[INFO] No {args.history_csv} found - processing current data only."
              f"\n       Run 'python backfill_history.py' to recover LFCHD's full history.")

    transform_cmd = [
        sys.executable, "transform_food_scores.py",
        "--input", *raw_inputs,
        "--output", args.cleaned_csv
    ]
    run_command("Step 2: Transform and clean data", transform_cmd)

    # Step 3: Join with violation descriptions
    join_cmd = [sys.executable, "JoinScoresViolations.py"]
    run_command("Step 3: Join with violation descriptions", join_cmd)

    # Step 4: Build the static site's data files
    if args.skip_site:
        print("\n[INFO] Skipping site data build (--skip-site)")
    elif os.path.isfile("build_site_data.py"):
        run_command("Step 4: Build site data", [sys.executable, "build_site_data.py"])

    # Final summary
    print("\n" + "="*60)
    print("PIPELINE COMPLETED SUCCESSFULLY!")
    print("="*60)
    print(f"\nFinal output: joined_scores_violations.csv")

    if os.path.isfile("joined_scores_violations.csv"):
        import pandas as pd
        df = pd.read_csv("joined_scores_violations.csv", low_memory=False)
        print(f"\nDataset statistics:")
        print(f"  Total records:         {len(df):,}")
        print(f"  Unique establishments: {df['Permit #'].nunique():,}")
        print(f"  Date range:            {df['Date'].min()} to {df['Date'].max()}")
        if 'ScrapeDate' in df.columns:
            print(f"  Scrape dates:          {df['ScrapeDate'].nunique()} unique dates")

    print("\nReady for analysis!\n")


if __name__ == "__main__":
    main()
