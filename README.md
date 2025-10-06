# Lexington KY Food Inspection Scores

A Python-based data extraction and analysis pipeline for processing food establishment inspection scores from Lexington-Fayette County Health Department reports.

## Overview

This project extracts food safety inspection data from PDF reports, cleans and transforms the data, and enriches it with detailed violation code descriptions to enable analysis of food establishment safety compliance.

## Features

- **PDF Data Extraction**: Automatically extracts inspection scores and violation codes from PDF reports
- **Data Cleaning**: Transforms raw extracted data into clean, structured CSV format
- **Violation Enrichment**: Joins inspection records with detailed violation code descriptions
- **Multi-page Processing**: Handles large PDF reports with multiple pages and tables

## Requirements

```bash
pip install pandas tabula-py pdfplumber camelot-py
```

**Note**: `tabula-py` requires Java to be installed and available on your PATH.

## Project Structure

```
LexKYFoodScores/
├── LexFoodScoresExtract copy.py  # Extracts data from PDF reports
├── transform_food_scores.py      # Cleans and transforms raw data
├── JoinScoresViolations.py       # Joins scores with violation descriptions
├── CodeViolations.csv            # Reference table of violation codes
├── food_scores.csv               # Raw extracted data
├── food_scores_cleaned.csv       # Cleaned data with proper headers
└── joined_scores_violations.csv  # Final enriched dataset
```

## Usage

### Step 1: Extract Data from PDF

Extract inspection scores and violation codes from the health department PDF:

```bash
python "LexFoodScoresExtract copy.py" \
    --scores-pdf "Food-Retail_Inspections-06.2024-06.2025.pdf" \
    --scores-csv food_scores.csv
```

**Note**: The current implementation replaces existing data on each run. If you want to accumulate data across multiple scrapes, you'll need to modify the extraction script to append rather than replace.

### Step 2: Clean and Transform Data

Transform the raw extracted data into a clean format with proper headers:

```bash
python transform_food_scores.py \
    --input food_scores.csv \
    --output food_scores_cleaned.csv
```

This step:
- Renames columns to meaningful headers (Permit #, Establishment Name, Address, Date, etc.)
- Filters out non-data rows
- Parses dates
- Splits multiple violations into separate rows

### Step 3: Join with Violation Descriptions

Enrich the cleaned data with detailed violation descriptions:

```bash
python JoinScoresViolations.py
```

This produces `joined_scores_violations.csv` with complete inspection records including:
- Establishment details (name, address, permit)
- Inspection date, type, and score
- Violation codes and their full descriptions
- Violation categories

## Data Schema

### Final Output Columns (`joined_scores_violations.csv`)

- **Permit #**: Establishment permit number
- **Establishment Name**: Name of the food establishment
- **Address**: Physical address
- **Date**: Inspection date
- **Inspection Type**: Type of inspection conducted
- **Food or Retail**: Classification
- **Score**: Inspection score
- **Violations**: Violation code
- **Violation Code**: Code from reference table
- **Category**: Violation category (e.g., Supervision, Employee Health)
- **Violation Explanation**: Detailed description of the violation

## Example Analysis

Once you have the final joined dataset, you can analyze:
- Distribution of inspection scores by establishment
- Most common violation types
- Trends in food safety compliance over time
- Establishments with repeat violations

## Data Source

Data is sourced from the Lexington-Fayette County Health Department food establishment inspection reports.

## License

This project is provided as-is for data analysis and transparency purposes.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.
