# Lexington KY Food Inspection Scores

A Python-based data extraction and analysis pipeline for processing food establishment inspection scores from Lexington-Fayette County Health Department reports.

## Overview

This project extracts food safety inspection data from PDF reports, cleans and transforms the data, and enriches it with detailed violation code descriptions to enable analysis of food establishment safety compliance. The system is designed to **accumulate historical data** by appending new scrapes to existing data, allowing you to track establishment performance over time.

## Features

- **PDF Data Extraction**: Automatically extracts inspection scores and violation codes from PDF reports
- **Historical Tracking**: Appends new scrapes to existing data with a scrape date timestamp
- **Data Cleaning**: Transforms raw extracted data into clean, structured CSV format
- **Violation Enrichment**: Joins inspection records with detailed violation code descriptions
- **Multi-page Processing**: Handles large PDF reports with multiple pages and tables
- **Trend Analysis**: Track establishments over time to identify repeat violations and compliance patterns

## Requirements

```bash
pip install pandas tabula-py pdfplumber camelot-py
```

**Note**: `tabula-py` requires Java to be installed and available on your PATH.

## Project Structure

```
LexKYFoodScores/
├── download_pdf.py               # Downloads latest PDF from LFCHD website
├── run_pipeline.py               # Orchestrator script (runs all steps)
├── LexFoodScoresExtract.py       # Step 1: Extracts data from PDF reports
├── transform_food_scores.py      # Step 2: Cleans and transforms raw data
├── JoinScoresViolations.py       # Step 3: Joins scores with violation descriptions
├── CodeViolations.csv            # Reference table of violation codes
├── PDFs/                         # Downloaded PDFs (historical archive)
├── food_scores.csv               # Raw extracted data (intermediate)
├── food_scores_cleaned.csv       # Cleaned data with proper headers (intermediate)
└── joined_scores_violations.csv  # Final enriched dataset
```

## Usage

### Quick Start: Automated Download and Processing

The easiest way is to let the pipeline automatically download the latest PDF:

```bash
python run_pipeline.py
```

This will:
1. Download the latest PDF from the LFCHD website
2. Store it in the `PDFs/` directory with a timestamp for historical tracking
3. Run all three processing steps
4. Generate the final `joined_scores_violations.csv` file

**Alternative: Manual PDF Download**

You can also download the PDF separately first:

```bash
python download_pdf.py
python run_pipeline.py --scores-pdf "PDFs/Food-Retail_Inspections-06.2024-06.2025.pdf"
```

**Options:**
- `--download`: Force download of latest PDF even if you specify --scores-pdf
- `--scores-pdf PATH`: Path to the inspection scores PDF (if not provided, downloads latest)
- `--form-pdf PATH`: Path to the infractions form PDF (default: `2585_001.pdf`)
- `--scrape-date YYYY-MM-DD`: Date of scrape (defaults to today)
- `--scores-csv PATH`: Output path for raw data (default: `food_scores.csv`)
- `--cleaned-csv PATH`: Output path for cleaned data (default: `food_scores_cleaned.csv`)

### Manual Step-by-Step Usage

If you prefer to run each step individually:

#### Step 1: Extract Data from PDF

Extract inspection scores and violation codes from the health department PDF:

```bash
python LexFoodScoresExtract.py \
    --scores-pdf "Food-Retail_Inspections-06.2024-06.2025.pdf" \
    --scores-csv food_scores.csv \
    --scrape-date 2025-10-06
```

**Key Features:**
- **Appends to existing data**: New scrapes are added to `food_scores.csv` rather than replacing it
- **Automatic scrape date**: If you don't provide `--scrape-date`, it defaults to today's date
- **Historical tracking**: Each row is tagged with when it was scraped, allowing you to track which inspection reports appeared in which PDF reports over time

**Example with auto-date:**
```bash
python LexFoodScoresExtract.py \
    --scores-pdf "Food-Retail_Inspections-06.2024-06.2025.pdf" \
    --scores-csv food_scores.csv
```

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
- **Address**: Physical address
- **Date**: Inspection date (when the inspection occurred)
- **Inspection Type**: Type of inspection conducted
- **Food or Retail**: Classification
- **Score**: Inspection score
- **Violations**: Violation code
- **ScrapeDate**: Date when this data was scraped from the PDF report
- **Page**: Page number in the source PDF
- **Table**: Table number on the page
- **SourceFile**: Name of the source PDF file
- **Violation Code**: Code from reference table
- **Category**: Violation category (e.g., Supervision, Employee Health)
- **Violation Explanation**: Detailed description of the violation

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

## Data Source

Data is sourced from the Lexington-Fayette County Health Department food establishment inspection reports.

## License

This project is provided as-is for data analysis and transparency purposes.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.
