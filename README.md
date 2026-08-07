# Lexington KY Food Inspection Scores

A Python-based data extraction and analysis pipeline for processing food establishment inspection scores from Lexington-Fayette County Health Department reports.

## Overview

This project downloads food safety inspection data published by LFCHD, cleans and transforms it, and enriches it with detailed violation code descriptions to enable analysis of food establishment safety compliance. The system is designed to **accumulate historical data** by appending new scrapes to existing data, allowing you to track establishment performance over time.

### A note on the data source

LFCHD published inspection results as a PDF through January 2026. In **February 2026 they switched to an Excel workbook** (`Report_NN_<period>_establishments.xlsx`) and removed the PDF from their site. The pipeline now reads the Excel report; the PDF extraction code is retained in `Archive/` for reference.

The download link's URL changes with every reporting period, so the downloader matches on the link's **text** ("Most recent food establishment inspection scores") rather than its URL. If LFCHD changes that wording, the downloader **fails loudly** and prints every spreadsheet link it did find — it will never silently fall back to a different file.

## Features

- **Automatic Download**: Finds and downloads the current inspection report from the LFCHD site
- **Change Detection**: MD5 comparison skips processing when the report is unchanged
- **Historical Tracking**: Appends new scrapes to existing data with a scrape date timestamp
- **Data Cleaning**: Transforms raw extracted data into clean, structured CSV format
- **Violation Enrichment**: Joins inspection records with detailed violation code descriptions
- **Trend Analysis**: Track establishments over time to identify repeat violations and compliance patterns

## Requirements

```bash
pip install -r requirements.txt
```

## Project Structure

```
LexKYFoodScores/
├── download_report.py            # Downloads the latest inspection report from LFCHD
├── run_pipeline.py               # Orchestrator script (runs all steps)
├── extract_report_scores.py      # Step 1: Reads the Excel report into raw CSV
├── transform_food_scores.py      # Step 2: Cleans and transforms raw data
├── JoinScoresViolations.py       # Step 3: Joins scores with violation descriptions
├── build_site_data.py            # Step 4: Builds the JSON the static site reads
├── backfill_history.py           # One-off: recovers LFCHD's full 2005-present archive
├── geocode_establishments.py     # One-off: adds lat/lon via the Census geocoder
├── site/                         # Static site published to GitHub Pages
├── CodeViolations.csv            # Reference table of violation codes
├── establishments.csv            # Permit # -> name / street address / ZIP lookup
├── Reports/                      # Downloaded reports (historical archive)
├── logs/                         # Run logs from the scheduled task
├── Archive/                      # Superseded PDF-era extraction scripts
├── food_scores.csv               # Raw data from ongoing runs (intermediate)
├── food_scores_history.csv       # Raw data from the backfill (intermediate)
├── food_scores_cleaned.csv       # Cleaned data with proper headers (intermediate)
└── joined_scores_violations.csv  # Final enriched dataset
```

## Historical Backfill

LFCHD only ever links the *current* report, but it never deletes the old ones — they stay in the WordPress media library, unlinked and undiscoverable from the site itself. `backfill_history.py` finds them through the media API and recovers the full archive:

```bash
python backfill_history.py
```

The richest single source is `Inspections_Report_for_Website-April-2023.xlsx`. Its own filter sheet shows no date filter and no inspection-type filter, making it a complete dump of everything through 2023-04-12 — about 90,000 inspections going back to 2005.

This takes the dataset from roughly 18 months to **20 years**:

| | Before | After |
|---|---|---|
| Inspections | 7,539 | 89,892 |
| Establishments | 2,695 | 4,250 |
| Date range | 2024-06 → 2025-12 | 2002-02 → 2025-12 |
| Inspections per establishment | mean 2.7 | mean 21.2, median 11 |

The script writes two files and touches neither of the live pipeline inputs:

- **`food_scores_history.csv`** — raw rows in the same layout as `food_scores.csv`. `run_pipeline.py` folds it in automatically when present, so re-running either the backfill or a nightly extract stays idempotent.
- **`establishments.csv`** — Permit # → name, street address, ZIP, first/last seen. The current Excel report has no street address, so this is what keeps addresses populated going forward.

### Things worth knowing about the historical data

- **Three schema eras.** Column names change twice (`Est Number`/`Premise Name` → `Permit Number (No.)`/`Name.1`); the script matches columns by keyword rather than position.
- **Numeric inspection types.** Pre-2024 reports encode Inspection Type as a number. `1→REGULAR`, `2→FOLLOWUP`, `3→COMPLAINT` is supported by three independent signals (frequency match against the current report, the 2019–2022 extracts filtering to types 1,2 exactly, and agreement on inspections appearing in both eras). Codes outside that set — notably 12, about 5% of rows — are left as `TYPE_12` rather than guessed at.
- **Reporting-area duplication.** One inspection is emitted once per reporting area (`TYPE` 605/607/603/610), so a premise inspected as both food service and retail appears twice with identical score and violations. These collapse during deduplication; the ~370 same-day pairs carrying genuinely different violation lists are preserved.
- **Unscored visits.** About 4,700 rows record a visit with no score and no violations. They are kept, since they are real events — filter on a blank `Score` to exclude them.
- **One ragged source file** (`...-10.11.2023.xlsx`) has shifted columns on a few rows. Violation codes are validated against `CodeViolations.csv`, which catches this without special-casing; the script reports anything it discards.
- **Coverage gap.** No published report covers 2024-02-15 → 2024-04-30.

## Usage

### Quick Start: Automated Download and Processing

**Option 1: Windows Batch File (Easiest)**

Double-click `run_pipeline.bat` or run from command prompt:

```bash
run_pipeline.bat
```

**Option 2: Python Command**

```bash
python run_pipeline.py
```

Both methods will:
1. Download the latest report from the LFCHD website
2. Check MD5 hash - skip processing if the report is unchanged (perfect for daily runs!)
3. Store reports in the `Reports/` directory with timestamps for historical tracking
4. Run all processing steps
5. Generate the final `joined_scores_violations.csv` file

**Alternative: Manual Download**

You can also download the report separately first:

```bash
python download_report.py
python run_pipeline.py --report "Reports/Report_53_Jul-Dec_2025_establishments.xlsx"
```

**Options:**
- `--report PATH`: Path to an inspection report (if not provided, downloads the latest)
- `--force`: Reprocess even if the online report is unchanged
- `--skip-sheets`: Skip the Google Sheets sync even if configured
- `--scrape-date YYYY-MM-DD`: Date of scrape (defaults to today)
- `--scores-csv PATH`: Output path for raw data (default: `food_scores.csv`)
- `--cleaned-csv PATH`: Output path for cleaned data (default: `food_scores_cleaned.csv`)

### Manual Step-by-Step Usage

If you prefer to run each step individually:

#### Step 1: Extract Data from the Report

Read inspection scores and violation codes out of the health department's Excel report:

```bash
python extract_report_scores.py \
    --report "Reports/Report_53_Jul-Dec_2025_establishments.xlsx" \
    --scores-csv food_scores.csv \
    --scrape-date 2026-08-06
```

**Key Features:**
- **Appends to existing data**: New scrapes are added to `food_scores.csv` rather than replacing it
- **Automatic scrape date**: If you don't provide `--scrape-date`, it defaults to today's date
- **Historical tracking**: Each row is tagged with when it was scraped, so you can track which inspections appeared in which reporting period
- **Address backfill**: The Excel report carries only city and ZIP, so street addresses are filled in from the existing published dataset by Permit #. Establishments never seen before have a blank address until LFCHD publishes one.

#### Step 2: Clean and Transform Data

Transform the raw extracted data into a clean format with proper headers:

```bash
python transform_food_scores.py \
    --input food_scores.csv \
    --output food_scores_cleaned.csv
```

This step:
- Renames columns to meaningful headers (Permit #, Establishment Name, Address, Date, ScrapeDate, etc.)
- Filters out non-data rows
- Parses inspection dates and scrape dates
- Splits multiple violations into separate rows
- Preserves scrape date metadata for historical tracking

#### Step 3: Join with Violation Descriptions

Enrich the cleaned data with detailed violation descriptions:

```bash
python JoinScoresViolations.py
```

This produces `joined_scores_violations.csv` with complete inspection records including:
- Establishment details (name, address, permit)
- Inspection date, type, and score
- **Scrape date** (when this data was captured)
- Violation codes and their full descriptions
- Violation categories

## Data Schema

### Final Output Columns (`joined_scores_violations.csv`)

- **Permit #**: Establishment permit number
- **Establishment Name**: Name of the food establishment
- **Address**: Street address. PDF-era rows carry it directly; Excel-era rows inherit it from a prior record for the same Permit #, and it is blank for establishments first seen in the Excel era.
- **Date**: Inspection date (when the inspection occurred)
- **Inspection Type**: Type of inspection conducted (REGULAR, FOLLOWUP, COMPLAINT)
- **Food or Retail**: Classification. As with Address, only available for establishments known from the PDF era.
- **Score**: Inspection score
- **Violations**: Violation code. Blank when an inspection recorded no violations.
- **ScrapeDate**: Date when this data was captured from the published report
- **Page**: Page number in the source PDF. Blank for Excel-sourced rows.
- **Table**: Table number on the page. Blank for Excel-sourced rows.
- **SourceFile**: Name of the source report file
- **Violation Code**: Code from reference table
- **Category**: Violation category (e.g., Supervision, Employee Health)
- **Violation Explanation**: Detailed description of the violation

Rows with no violation code represent clean inspections; their Category, Violation Code, and Violation Explanation are blank.

## Example Analysis

Once you have the final joined dataset, you can analyze:
- **Historical performance**: Track how individual establishments' scores change over time
- **Repeat offenders**: Identify establishments that consistently appear in reports with violations
- **Violation trends**: See which violations are most common across all establishments
- **Disappearing establishments**: Detect establishments that stopped appearing in reports (closed or improved?)
- **Seasonal patterns**: Analyze if certain times of year have more violations
- **New vs. routine inspections**: Compare scores between different inspection types over time

### Sample Historical Analysis Queries

```python
import pandas as pd

df = pd.read_csv('joined_scores_violations.csv')

# Find establishments that appeared in multiple scrapes
repeat_establishments = df.groupby('Permit #')['ScrapeDate'].nunique()
establishments_with_multiple_scrapes = repeat_establishments[repeat_establishments > 1]

# Track score changes over time for a specific establishment
permit = '12345'
score_history = df[df['Permit #'] == permit][['Date', 'ScrapeDate', 'Score']].drop_duplicates()

# Find establishments that disappeared (were in early scrapes but not recent ones)
early_scrapes = df[df['ScrapeDate'] < '2025-06-01']['Permit #'].unique()
recent_scrapes = df[df['ScrapeDate'] >= '2025-06-01']['Permit #'].unique()
disappeared = set(early_scrapes) - set(recent_scrapes)
```

## Automated Scheduling

### Windows Task Scheduler (Recommended)

Set up automatic daily checks for new inspection data:

1. **Open Task Scheduler**
   - Press `Win + R`, type `taskschd.msc`, press Enter

2. **Create Basic Task**
   - Click "Create Basic Task" in the right panel
   - Name: `Food Inspection Data Update`
   - Description: `Daily check for new food inspection data`

3. **Set Trigger**
   - Choose "Daily"
   - Set start time (e.g., 6:00 AM)
   - Recur every: 1 day

4. **Set Action**
   - Choose "Start a program"
   - Program/script: `C:\PythonCode\LexKYFoodScores\run_pipeline.bat`
   - Start in: `C:\PythonCode\LexKYFoodScores`
   - (Adjust path to match your installation)

5. **Finish**
   - Check "Open Properties dialog" to review settings

**Why Daily?**
- MD5 check ensures no duplicate processing
- Script exits quickly if no new data (< 5 seconds)
- Always have latest data when it's published

**Enable task history.** Task Scheduler's history log is off by default, which leaves you with no record of why a run failed. Turn it on once:

```powershell
wevtutil set-log Microsoft-Windows-TaskScheduler/Operational /enabled:true
```

### Troubleshooting a scheduled run

Every run writes `logs\pipeline-last.log`. Failures are also archived to `logs\pipeline-failed-<timestamp>.log` and kept for 30 days, so the error is still readable after you close the notification window.

To check the last result:

```powershell
Get-ScheduledTaskInfo -TaskName 'Food Scores Log'   # LastTaskResult 0 = success
Get-Content .\logs\pipeline-last.log -Tail 40
```

Because LFCHD publishes new data only a couple of times a year, a long run of "no update needed" days is normal. What is *not* normal is the report link disappearing — the downloader treats that as a hard error rather than quietly processing the wrong file.

### Manual Schedule
You can also run manually whenever you want fresh data - the MD5 check prevents redundant processing.

## The website

`site/` is a static three-page site — no server, no database, no API. It reads
pre-built JSON and is published to GitHub Pages by
[`.github/workflows/pages.yml`](.github/workflows/pages.yml) whenever `site/` changes.

| Page | What it does |
|---|---|
| `index.html` | Insights — the reputation gap, score trends, violations, ZIP breakdown |
| `map.html` | Every geocoded establishment, coloured by latest score, weighted history, or the gap. Drag to pan, pinch or scroll to zoom, and **Near me** centres on your GPS fix and lists the eight closest establishments |
| `search.html` | Search by name, street, ZIP or permit number |
| `selftest.html` | Not linked from the site; checks the deployed data reconciles |

Clicking anything anywhere opens the same drawer with the establishment's full
inspection history back to 2005.

**Geolocation** is browser-side only — the coordinates are used to centre the map
and measure distances, and are never sent anywhere. It needs HTTPS, which
GitHub Pages provides. Being outside Fayette County is handled as a normal case
rather than an error: the map says so and still reports the nearest
establishment on record.

`map.html?debug=1` shows an on-screen event log — pointer events, whether a tap
found a point, and the drawer's live state. There is no console to attach to a
phone, and that log is the difference between a swallowed tap and a missed one.

### Rebuilding the site's data

```bash
python build_site_data.py
```

This runs automatically as step 4 of `run_pipeline.py`. It writes four files:

| File | Size | Loaded |
|---|---|---|
| `establishments.json` | ~750 KB | every page |
| `insights.json` | ~110 KB | insights page |
| `geo.json` | ~26 KB | map page |
| `inspections.json` | ~5.7 MB | lazily, on first detail view |

`geo.json` holds the Fayette County and ZIP boundaries, simplified with
Douglas-Peucker and rounded to four decimals. That is what lets the map render
with no tile server and no external requests. It is fetched once and then left
alone — boundaries don't change.

### Previewing locally

```bash
python -m http.server 8765 --directory site
```

Then open <http://localhost:8765/>. A plain `file://` open will not work: the
pages use ES modules and `fetch`, both of which need a real origin.

### Geocoding

The reports carry no coordinates, so `geocode_establishments.py` derives them
from street addresses using the U.S. Census batch geocoder — free, no API key:

```bash
python geocode_establishments.py                 # first pass
python geocode_establishments.py --retry-failed  # retry rejects with looser parsing
```

Results are cached in `geocode_cache.csv` so an address is only ever sent once.
About 89% of establishments with a street address get coordinates; the rest are
PO boxes, non-addresses, or addresses the Census TIGER data doesn't carry.

A few dozen geocode to points **outside Fayette County** — farmers-market
vendors, mobile units and out-of-county producers that LFCHD still permits.
Those are correct, not errors, which is why the map frames itself on the county
boundary rather than on the spread of the points.

### Hosting note

GitHub Pages can publish from a private repository only on **GitHub Pro, Team or
Enterprise**; on a free personal account the repository must be public. Either
way the published site is public — restricting who can view a Pages site is an
Enterprise Cloud feature.

## Data Source

Data is sourced from the [Lexington-Fayette County Health Department food protection page](https://www.lfchd.org/food-protection/).

## License

This project is provided as-is for data analysis and transparency purposes.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.
