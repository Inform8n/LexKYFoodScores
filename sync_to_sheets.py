#!/usr/bin/env python3
"""
sync_to_sheets.py

Syncs food inspection data to Google Sheets.
Only appends new records that don't already exist (based on deduplication logic).

Usage:
    python sync_to_sheets.py
    python sync_to_sheets.py --input joined_scores_violations.csv
"""

import argparse
import os
import sys
import pandas as pd
import gspread
from dotenv import load_dotenv


def load_config():
    """Load configuration from environment variables."""
    load_dotenv()

    sheet_id = os.getenv('GOOGLE_SHEET_ID')
    worksheet_name = os.getenv('GOOGLE_WORKSHEET_NAME', 'Food Inspections')
    auth_method = os.getenv('GOOGLE_AUTH_METHOD', 'oauth')  # 'oauth' or 'service_account'

    if not sheet_id:
        print("[ERROR] GOOGLE_SHEET_ID not found in .env file")
        sys.exit(1)

    return sheet_id, worksheet_name, auth_method


def authenticate_oauth():
    """Authenticate using OAuth (personal Google account)."""
    print(">> Authenticating with your Google account...")

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive.file'
        ]

        creds = None
        token_file = 'token.json'
        credentials_file = 'credentials.json'

        # Check if we have saved credentials
        if os.path.exists(token_file):
            print("[INFO] Found saved credentials")
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)

        # If no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("[INFO] Refreshing expired credentials...")
                creds.refresh(Request())
            else:
                # Need to authenticate via browser
                if not os.path.exists(credentials_file):
                    print(f"[ERROR] Credentials file not found: {credentials_file}")
                    sys.exit(1)

                print("[INFO] Opening browser for authentication...")
                flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)

            # Save credentials for future runs
            with open(token_file, 'w') as token:
                token.write(creds.to_json())
            print(f"[SUCCESS] Credentials saved to {token_file}")

        # Authorize gspread
        client = gspread.authorize(creds)
        print("[SUCCESS] Authenticated successfully")
        return client

    except ImportError:
        print("[ERROR] Missing OAuth dependencies")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Authentication failed: {e}")
        sys.exit(1)


def authenticate_service_account(creds_path: str):
    """Authenticate using Service Account (for automation)."""
    print(">> Authenticating with Service Account...")

    try:
        from google.oauth2.service_account import Credentials

        if not os.path.exists(creds_path):
            print(f"[ERROR] Credentials file not found: {creds_path}")
            sys.exit(1)

        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

        credentials = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        client = gspread.authorize(credentials)

        print("[SUCCESS] Authenticated successfully")
        return client

    except Exception as e:
        print(f"[ERROR] Authentication failed: {e}")
        sys.exit(1)


def authenticate_google_sheets(auth_method: str):
    """Authenticate with Google Sheets API using specified method."""
    if auth_method == 'oauth':
        return authenticate_oauth()
    elif auth_method == 'service_account':
        load_dotenv()
        creds_path = os.getenv('GOOGLE_CREDENTIALS_PATH')
        if not creds_path:
            print("[ERROR] GOOGLE_CREDENTIALS_PATH not found in .env file")
            sys.exit(1)
        return authenticate_service_account(creds_path)
    else:
        print(f"[ERROR] Invalid auth method: {auth_method}")
        print("Valid options: 'oauth' or 'service_account'")
        sys.exit(1)


def get_or_create_worksheet(client, sheet_id: str, worksheet_name: str):
    """Get or create the worksheet in the Google Sheet."""
    print(f">> Opening Google Sheet: {sheet_id}")

    try:
        # Open the spreadsheet
        spreadsheet = client.open_by_key(sheet_id)
        print(f"[SUCCESS] Opened spreadsheet: {spreadsheet.title}")

        # Try to get the worksheet
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
            print(f"[SUCCESS] Found worksheet: {worksheet_name}")
        except gspread.WorksheetNotFound:
            print(f"[INFO] Worksheet '{worksheet_name}' not found, creating new...")
            worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=20)
            print(f"[SUCCESS] Created worksheet: {worksheet_name}")

        return worksheet

    except Exception as e:
        print(f"[ERROR] Failed to open/create worksheet: {e}")
        sys.exit(1)


def get_existing_data(worksheet) -> pd.DataFrame:
    """Fetch existing data from the worksheet."""
    print(">> Fetching existing data from Google Sheet...")

    try:
        # Get all values
        values = worksheet.get_all_values()

        if not values:
            print("[INFO] Worksheet is empty")
            return pd.DataFrame()

        # First row is headers
        headers = values[0]
        data = values[1:]

        if not data:
            print("[INFO] No data rows found (only headers)")
            return pd.DataFrame(columns=headers)

        df = pd.DataFrame(data, columns=headers)
        print(f"[SUCCESS] Fetched {len(df):,} existing records")
        return df

    except Exception as e:
        print(f"[ERROR] Failed to fetch existing data: {e}")
        sys.exit(1)


def identify_new_records(local_df: pd.DataFrame, sheet_df: pd.DataFrame) -> pd.DataFrame:
    """Identify new records that don't exist in the sheet yet."""
    print(">> Identifying new records...")

    # Deduplication columns (same as transform_food_scores.py)
    dedup_cols = ['Permit #', 'Establishment Name', 'Date', 'Violations']

    # Ensure both DataFrames have the required columns
    missing_cols = [col for col in dedup_cols if col not in local_df.columns]
    if missing_cols:
        print(f"[ERROR] Missing columns in local data: {missing_cols}")
        sys.exit(1)

    if sheet_df.empty:
        print(f"[INFO] Sheet is empty, all {len(local_df):,} records are new")
        return local_df

    # Check if sheet has required columns
    missing_sheet_cols = [col for col in dedup_cols if col not in sheet_df.columns]
    if missing_sheet_cols:
        print(f"[WARNING] Sheet missing columns: {missing_sheet_cols}")
        print("[INFO] Treating all records as new")
        return local_df

    # Create a composite key for comparison
    local_df['_composite_key'] = local_df[dedup_cols].astype(str).agg('|'.join, axis=1)
    sheet_df['_composite_key'] = sheet_df[dedup_cols].astype(str).agg('|'.join, axis=1)

    # Find records that exist in local but not in sheet
    existing_keys = set(sheet_df['_composite_key'])
    new_records = local_df[~local_df['_composite_key'].isin(existing_keys)].copy()

    # Remove the temporary composite key column
    new_records = new_records.drop(columns=['_composite_key'])

    print(f"[INFO] Found {len(new_records):,} new records to add")
    return new_records


def append_to_sheet(worksheet, new_df: pd.DataFrame, is_first_write: bool):
    """Append new records to the Google Sheet."""
    if new_df.empty:
        print("[INFO] No new records to append")
        return

    print(f">> Appending {len(new_df):,} new records to Google Sheet...")

    try:
        # Replace NaN values with empty strings to avoid JSON serialization errors
        new_df_clean = new_df.fillna('')

        # Convert DataFrame to list of lists for gspread
        if is_first_write:
            # Include headers
            values = [new_df_clean.columns.tolist()] + new_df_clean.values.tolist()
            print("[INFO] Writing headers + data (first write)")
        else:
            # Only data rows
            values = new_df_clean.values.tolist()
            print("[INFO] Appending data only (headers exist)")

        # Append to worksheet
        worksheet.append_rows(values, value_input_option='USER_ENTERED')

        print(f"[SUCCESS] Successfully appended {len(new_df):,} records")

    except Exception as e:
        print(f"[ERROR] Failed to append data: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Sync food inspection data to Google Sheets"
    )
    parser.add_argument(
        "--input",
        default="joined_scores_violations.csv",
        help="Input CSV file to sync (default: joined_scores_violations.csv)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force sync all records (ignores deduplication)"
    )

    args = parser.parse_args()

    print("\n" + "="*60)
    print("GOOGLE SHEETS SYNC")
    print("="*60)

    # Load configuration
    sheet_id, worksheet_name, auth_method = load_config()

    # Check input file exists
    if not os.path.exists(args.input):
        print(f"[ERROR] Input file not found: {args.input}")
        sys.exit(1)

    # Read local CSV
    print(f">> Reading local data from: {args.input}")
    local_df = pd.read_csv(args.input)
    print(f"[SUCCESS] Loaded {len(local_df):,} records from local CSV")

    # Authenticate
    client = authenticate_google_sheets(auth_method)

    # Get or create worksheet
    worksheet = get_or_create_worksheet(client, sheet_id, worksheet_name)

    # Get existing data
    sheet_df = get_existing_data(worksheet)
    is_first_write = sheet_df.empty

    # Identify new records
    if args.force:
        print("[INFO] Force mode enabled, syncing all records")
        new_records = local_df
    else:
        new_records = identify_new_records(local_df, sheet_df)

    # Append new records
    append_to_sheet(worksheet, new_records, is_first_write)

    print("\n" + "="*60)
    print("SYNC COMPLETED!")
    print("="*60)
    print(f"Total records in local CSV:  {len(local_df):,}")
    print(f"Records already in sheet:    {len(sheet_df):,}")
    print(f"New records added:           {len(new_records):,}")
    print(f"Total records in sheet now:  {len(sheet_df) + len(new_records):,}")
    print("\nGoogle Sheet updated successfully!")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
