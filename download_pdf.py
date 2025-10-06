#!/usr/bin/env python3
"""
download_pdf.py

Downloads the latest Food Inspection PDF from the Lexington-Fayette County Health Department
website and stores it in a PDFs directory for historical purposes.

Usage:
    python download_pdf.py
    python download_pdf.py --output-dir PDFs
"""

import argparse
import os
import re
import sys
import hashlib
from datetime import datetime
from urllib.parse import urljoin, urlparse
import urllib.request
from html.parser import HTMLParser


class PDFLinkParser(HTMLParser):
    """HTML parser to find PDF links related to food inspections."""

    def __init__(self):
        super().__init__()
        self.pdf_links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            attrs_dict = dict(attrs)
            href = attrs_dict.get('href', '')

            # Look for PDF links that mention food/retail inspections
            if href.endswith('.pdf') and any(keyword in href.lower() for keyword in
                ['food', 'retail', 'inspection']):
                self.pdf_links.append(href)


def fetch_page(url: str) -> str:
    """Fetch the HTML content of a webpage."""
    try:
        with urllib.request.urlopen(url) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        print(f"[ERROR] Failed to fetch page: {e}")
        sys.exit(1)


def find_pdf_link(base_url: str) -> str:
    """Find the food inspection PDF link on the webpage."""
    print(f">> Fetching page: {base_url}")
    html_content = fetch_page(base_url)

    parser = PDFLinkParser()
    parser.feed(html_content)

    if not parser.pdf_links:
        print("[ERROR] No food inspection PDF found on the page")
        sys.exit(1)

    # Get the first matching PDF link
    pdf_link = parser.pdf_links[0]

    # Convert to absolute URL if needed
    if not pdf_link.startswith('http'):
        pdf_link = urljoin(base_url, pdf_link)

    print(f"[SUCCESS] Found PDF: {pdf_link}")
    return pdf_link


def download_pdf(url: str, output_path: str):
    """Download a PDF file from a URL."""
    print(f">> Downloading PDF to: {output_path}")

    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Download the file
        urllib.request.urlretrieve(url, output_path)

        # Check file size
        file_size = os.path.getsize(output_path)
        file_size_mb = file_size / (1024 * 1024)

        print(f"[SUCCESS] Downloaded {file_size_mb:.2f} MB to {output_path}")
        return output_path

    except Exception as e:
        print(f"[ERROR] Failed to download PDF: {e}")
        sys.exit(1)


def calculate_md5(file_path: str) -> str:
    """Calculate MD5 hash of a file."""
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        # Read in chunks to handle large files
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def extract_date_from_filename(filename: str) -> str:
    """Extract date information from the PDF filename."""
    # Look for patterns like "06.2024-06.2025" in the filename
    match = re.search(r'(\d{2}\.\d{4}-\d{2}\.\d{4})', filename)
    if match:
        return match.group(1)
    return datetime.now().strftime('%Y-%m-%d')


def main():
    parser = argparse.ArgumentParser(
        description="Download the latest food inspection PDF from LFCHD website"
    )
    parser.add_argument(
        "--url",
        default="https://www.lfchd.org/food-protection/",
        help="URL of the food protection page"
    )
    parser.add_argument(
        "--output-dir",
        default="PDFs",
        help="Directory to store downloaded PDFs"
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="Custom output filename (if not specified, uses original name)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force download even if file already exists with same MD5"
    )

    args = parser.parse_args()

    print("\n" + "="*60)
    print("LFCHD FOOD INSPECTION PDF DOWNLOADER")
    print("="*60)

    # Find the PDF link
    pdf_url = find_pdf_link(args.url)

    # Extract filename from URL
    url_path = urlparse(pdf_url).path
    original_filename = os.path.basename(url_path)

    # Use custom name or original filename
    if args.output_name:
        filename = args.output_name
    else:
        filename = original_filename

    # Create timestamped copy for historical purposes
    date_info = extract_date_from_filename(original_filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Download to output directory
    output_path = os.path.join(args.output_dir, filename)

    # Check if file already exists and compare MD5
    if os.path.exists(output_path) and not args.force:
        print(f"\n>> File already exists: {output_path}")
        print(">> Checking if content has changed (MD5)...")

        # Calculate MD5 of existing file
        existing_md5 = calculate_md5(output_path)
        print(f"Existing file MD5: {existing_md5}")

        # Download to temp location to check MD5
        import tempfile
        temp_path = os.path.join(tempfile.gettempdir(), f"temp_{filename}")
        download_pdf(pdf_url, temp_path)
        new_md5 = calculate_md5(temp_path)
        print(f"New file MD5:      {new_md5}")

        if existing_md5 == new_md5:
            print("\n[INFO] PDF unchanged - no new data available")
            print("Skipping processing (file is identical)")
            os.remove(temp_path)
            print("\n" + "="*60)
            print("NO UPDATE NEEDED")
            print("="*60)
            print(f"Current version:   {output_path}")
            print(f"MD5:               {existing_md5}")
            print("\nThe online PDF is identical to your local copy.")
            print("No processing required.")
            print("="*60 + "\n")
            sys.exit(0)
        else:
            print("\n[INFO] PDF has changed - new data detected!")
            print(">> Replacing old version...")
            os.replace(temp_path, output_path)
    else:
        if args.force:
            print("\n>> Force download requested, skipping MD5 check...")
        # Download the PDF
        download_pdf(pdf_url, output_path)

    # Calculate MD5 of final file
    final_md5 = calculate_md5(output_path)

    # Also create a timestamped historical copy
    base_name, ext = os.path.splitext(filename)
    historical_filename = f"{base_name}_{timestamp}{ext}"
    historical_path = os.path.join(args.output_dir, historical_filename)

    # Create historical copy
    print(f"\n>> Creating historical copy: {historical_filename}")
    import shutil
    shutil.copy2(output_path, historical_path)
    print(f"[SUCCESS] Historical copy saved")

    print("\n" + "="*60)
    print("DOWNLOAD COMPLETED!")
    print("="*60)
    print(f"Current version:   {output_path}")
    print(f"Historical copy:   {historical_path}")
    print(f"Date range:        {date_info}")
    print(f"MD5:               {final_md5}")
    print("\nYou can now run the pipeline with:")
    print(f'  python run_pipeline.py --scores-pdf "{output_path}"')
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
