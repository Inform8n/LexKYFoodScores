#!/usr/bin/env python3
"""
download_report.py

Downloads the latest food establishment inspection score report from the
Lexington-Fayette County Health Department website and stores it in a Reports
directory for historical purposes.

LFCHD retired the inspections PDF in February 2026 and now publishes the scores
as an Excel workbook. The download link text is stable ("Most recent food
establishment inspection scores"); the URL is not -- it carries the reporting
period (e.g. Report_53_Jul-Dec_2025_establishments.xlsx) and changes every time
a new period is published. So we match on link text, not on the URL.

Usage:
    python download_report.py
    python download_report.py --output-dir Reports --force
"""

import argparse
import hashlib
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

# This runs unattended at 7am on a laptop, where the network is often not up
# yet when the scheduled task fires. Retry before giving up.
MAX_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 30

# Spreadsheet formats LFCHD has used or might reasonably switch to.
REPORT_EXTENSIONS = ('.xlsx', '.xls', '.csv')

# A link is the score report if its visible text looks like the published label,
# or if its filename matches the report naming convention.
TEXT_PATTERN = re.compile(r'inspection\s+scores', re.IGNORECASE)
HREF_PATTERN = re.compile(r'Report_\d+.*establishments', re.IGNORECASE)


class ReportLinkParser(HTMLParser):
    """Collects (href, link text) pairs for every spreadsheet link on the page."""

    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = dict(attrs).get('href', '')
            self._href = href if href.lower().endswith(REPORT_EXTENSIONS) else None
            self._text = []

    def handle_data(self, data):
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self._href:
            self.links.append((self._href, ' '.join(self._text).strip()))
            self._href = None
            self._text = []


def with_retries(description: str, action):
    """Run a network action, retrying transient failures before giving up."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return action()
        except Exception as e:
            if attempt == MAX_ATTEMPTS:
                print(f"[ERROR] {description} failed after {MAX_ATTEMPTS} attempts: {e}")
                sys.exit(1)
            print(f"[WARNING] {description} failed (attempt {attempt}/{MAX_ATTEMPTS}): {e}")
            print(f"          Retrying in {RETRY_DELAY_SECONDS}s...")
            time.sleep(RETRY_DELAY_SECONDS)


def fetch_page(url: str) -> str:
    """Fetch the HTML content of a webpage."""
    def _get():
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read().decode('utf-8', errors='replace')

    return with_retries("Fetching page", _get)


def find_report_link(base_url: str) -> tuple[str, str]:
    """Find the inspection score report link. Returns (url, link text)."""
    print(f">> Fetching page: {base_url}")
    parser = ReportLinkParser()
    parser.feed(fetch_page(base_url))

    if not parser.links:
        print("[ERROR] No spreadsheet links at all were found on the page.")
        print("        The page layout has probably changed -- check it by hand:")
        print(f"        {base_url}")
        sys.exit(1)

    matches = [
        (href, text) for href, text in parser.links
        if TEXT_PATTERN.search(text) or HREF_PATTERN.search(href)
    ]

    if not matches:
        # Fail loudly and show what we did see. Never silently fall back to some
        # other link -- that is exactly how this pipeline quietly died in 2026.
        print("[ERROR] Could not find the inspection score report link.")
        print("        Spreadsheet links found on the page were:")
        for href, text in parser.links:
            print(f"          - {text or '(no link text)'}\n            {href}")
        print(f"\n        Check the page by hand: {base_url}")
        sys.exit(1)

    # The page lists the same report twice (desktop + mobile markup); dedupe.
    unique = list(dict.fromkeys(href for href, _ in matches))
    if len(unique) > 1:
        print(f"[WARNING] {len(unique)} candidate reports found; using the first:")
        for href in unique:
            print(f"          - {href}")

    report_url, link_text = matches[0]
    if not report_url.startswith('http'):
        report_url = urljoin(base_url, report_url)

    print(f"[SUCCESS] Found report: {link_text}")
    print(f"          {report_url}")
    return report_url, link_text


def download(url: str, output_path: str) -> str:
    """Download a file from a URL."""
    print(f">> Downloading to: {output_path}")
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with_retries("Downloading report", lambda: urllib.request.urlretrieve(url, output_path))
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"[SUCCESS] Downloaded {size_mb:.2f} MB")
    return output_path


def calculate_md5(file_path: str) -> str:
    """Calculate MD5 hash of a file."""
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def main():
    parser = argparse.ArgumentParser(
        description="Download the latest food inspection score report from LFCHD"
    )
    parser.add_argument(
        "--url",
        default="https://www.lfchd.org/food-protection/",
        help="URL of the food protection page"
    )
    parser.add_argument(
        "--output-dir",
        default="Reports",
        help="Directory to store downloaded reports"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Process the report even if it is unchanged since the last run"
    )

    args = parser.parse_args()

    print("\n" + "="*60)
    print("LFCHD FOOD INSPECTION REPORT DOWNLOADER")
    print("="*60)

    report_url, _ = find_report_link(args.url)
    filename = os.path.basename(urlparse(report_url).path)
    output_path = os.path.join(args.output_dir, filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if os.path.exists(output_path) and not args.force:
        print(f"\n>> Report already downloaded: {output_path}")
        print(">> Checking if content has changed (MD5)...")
        existing_md5 = calculate_md5(output_path)
        print(f"Existing file MD5: {existing_md5}")

        temp_path = os.path.join(tempfile.gettempdir(), f"temp_{filename}")
        download(report_url, temp_path)
        new_md5 = calculate_md5(temp_path)
        print(f"New file MD5:      {new_md5}")

        if existing_md5 == new_md5:
            os.remove(temp_path)
            print("\n" + "="*60)
            print("NO UPDATE NEEDED")
            print("="*60)
            print(f"Current version:   {output_path}")
            print(f"MD5:               {existing_md5}")
            print("\nThe online report is identical to the local copy.")
            print("="*60 + "\n")
            # Still tell the caller which file is current, so a --force
            # reprocess does not have to re-derive the path.
            print(f"CURRENT_REPORT={output_path}")
            sys.exit(0)

        print("\n[INFO] Report has changed - new data detected!")
        os.replace(temp_path, output_path)
    else:
        if args.force and os.path.exists(output_path):
            print("\n>> Force requested, skipping MD5 check...")
        download(report_url, output_path)

    final_md5 = calculate_md5(output_path)

    # Keep a timestamped historical copy so past reporting periods are retained.
    base_name, ext = os.path.splitext(filename)
    historical_path = os.path.join(args.output_dir, f"{base_name}_{timestamp}{ext}")
    print(f"\n>> Creating historical copy: {os.path.basename(historical_path)}")
    shutil.copy2(output_path, historical_path)
    print("[SUCCESS] Historical copy saved")

    print("\n" + "="*60)
    print("DOWNLOAD COMPLETED!")
    print("="*60)
    print(f"Current version:   {output_path}")
    print(f"Historical copy:   {historical_path}")
    print(f"MD5:               {final_md5}")
    print("="*60 + "\n")

    # Machine-readable handoff to run_pipeline.py.
    print(f"CURRENT_REPORT={output_path}")


if __name__ == "__main__":
    main()
