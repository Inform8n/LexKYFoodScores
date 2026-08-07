#!/usr/bin/env python3
"""
backfill_history.py

Recovers LFCHD's full inspection history.

LFCHD only ever links the current report, but it never deletes the old ones --
they stay in the WordPress media library, unlinked. This script finds them via
the media API, downloads them, and normalises three different schema eras into
the same raw layout the ongoing pipeline produces.

The richest single source is `Inspections_Report_for_Website-April-2023.xlsx`:
its own filter sheet shows no date filter and no inspection-type filter, so it
is a complete dump of everything through 2023-04-12 -- about 90,000 inspections
going back to 2005.

Outputs two files, neither of which touches the live pipeline inputs:

  food_scores_history.csv  Raw rows in the same 12-column layout as
                           food_scores.csv, ready to concatenate and feed to
                           transform_food_scores.py.

  establishments.csv       Permit # -> name / street address / ZIP / type.
                           The current Excel report has no street address, so
                           this is the lookup that keeps addresses populated
                           going forward.

Usage:
    python backfill_history.py
    python backfill_history.py --refresh        # re-discover URLs from the site
    python backfill_history.py --skip-download  # use already-downloaded files
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime

import pandas as pd

MEDIA_API = "https://www.lfchd.org/wp-json/wp/v2/media"
SEARCH_TERMS = ["inspections", "inspection", "establishments", "website_inspections",
                "foodservice", "premise"]
UA = {'User-Agent': 'Mozilla/5.0'}

# Spreadsheets that are inspection extracts, as opposed to guidance documents.
IS_SPREADSHEET = re.compile(r'\.(xlsx|xls|csv)$', re.I)
# Keep this generous. LFCHD has used at least four unrelated naming schemes over
# the years (most_recent_food_scores, website_inspections, EH-Foodservice-...,
# Report_NN_..._establishments); a narrow pattern silently skips a whole era.
LOOKS_LIKE_DATA = re.compile(
    r'(inspection|establishments|premise|foodservice|food[_-]?scores|scores)', re.I)
NOT_DATA = re.compile(r'(codes|poster|guideline|form|sheet-|template)', re.I)

# Known-good URLs, used if the media API is unavailable. These are unlinked from
# the site and could be removed at any time, which is why they are pinned here.
FALLBACK_URLS = [
    "https://www.lfchd.org/wp-content/uploads/2018/11/most_recent_food_scores-1.xls",
    "https://www.lfchd.org/wp-content/uploads/2018/12/most_recent_food_scores.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2019/01/most_recent_food_scores.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2019/02/most_recent_food_scores.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2019/03/most_recent_food_scores.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2019/04/most_recent_food_scores.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2019/05/most_recent_food_scores.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2019/09/most_recent_food_scores.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2020/02/website_inspections-9.1.19-2.11.20.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2020/09/Copy-of-605_website_inspections-3.1.20-9.24.20.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2021/05/4.21-A-Z-Inspections.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2021/09/website_inspections-5.1.21-9.24.21.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2022/03/Inspections-9.25.21-to-3.1.22.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2022/06/EH-Foodservice-inspections-3-01-2022-to-6-14-2022.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2023/04/Inspections_Report_for_Website-April-2023.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2023/07/Inspections_Report_for_Website-1.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2024/01/Inspections_Report_for_Website-10.11.2023.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2024/02/Inspections_Report_for_Website.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2024/06/05.2024-Inspections.xlsx",
    "https://www.lfchd.org/wp-content/uploads/2024/07/06.2024-Inspections.xlsx",
]

# Raw layout produced by the ongoing pipeline. Columns 0-7 are positional.
RAW_COLUMNS = ['0', '1', '2', '3', '4', '5', '6', '7',
               'ScrapeDate', 'Page', 'Table', 'SourceFile']

# Older reports encode Inspection Type as a number. Three independent signals
# support this mapping:
#   * frequency -- 1 is 72% of rows and REGULAR is 85% of the current report;
#     2 is 21% vs FOLLOWUP 15%; 3 is 0.7% vs COMPLAINT 0.4%
#   * the 2019-2022 "website inspections" extracts filter to Inspection Type
#     1,2 exactly -- the routine pair LFCHD publishes
#   * the handful of inspections that appear in both a numeric-typed file and
#     the text-typed data agree
# Codes outside this set (notably 12, ~5% of rows) have no counterpart in the
# current three-value vocabulary and are deliberately left undecoded rather than
# guessed at.
NUMERIC_INSPECTION_TYPE = {1: 'REGULAR', 2: 'FOLLOWUP', 3: 'COMPLAINT'}

# Violation code 0 is a "no violation" placeholder, not a real code.
PLACEHOLDER_CODE = '0'

# Anything outside this window is a data-entry artifact (one file carries
# epoch-zero dates).
MIN_DATE = pd.Timestamp('2000-01-01')


def log(msg=""):
    print(msg, flush=True)


# --------------------------------------------------------------------------
# Discovery and download
# --------------------------------------------------------------------------

def discover_urls():
    """Find inspection data files in the LFCHD media library."""
    log(">> Discovering historical reports via the LFCHD media API...")
    found = {}
    for term in SEARCH_TERMS:
        for page in range(1, 4):
            try:
                req = urllib.request.Request(
                    f"{MEDIA_API}?search={term}&per_page=100&page={page}", headers=UA)
                with urllib.request.urlopen(req, timeout=90) as r:
                    items = json.loads(r.read().decode('utf-8', 'replace'))
            except Exception:
                break
            if not items:
                break
            for it in items:
                u = it.get('source_url', '')
                if u:
                    found[u] = True
            if len(items) < 100:
                break

    hits = sorted(u for u in found
                  if IS_SPREADSHEET.search(u)
                  and LOOKS_LIKE_DATA.search(u)
                  and not NOT_DATA.search(u))

    if not hits:
        log("[WARNING] Media API returned nothing usable; using the pinned URL list")
        return list(FALLBACK_URLS)

    log(f"[SUCCESS] Found {len(hits)} candidate report files")
    return hits


def local_name(url):
    """Tag the filename with its upload year/month so reused names don't collide."""
    name = url.rsplit('/', 1)[-1]
    parts = url.split('/uploads/')[-1].split('/')
    return f"{parts[0]}-{parts[1]}_{name}" if len(parts) >= 2 else name


def download_all(urls, dest):
    os.makedirs(dest, exist_ok=True)
    paths = []
    for u in urls:
        path = os.path.join(dest, local_name(u))
        if os.path.exists(path):
            paths.append(path)
            continue
        try:
            req = urllib.request.Request(u, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            with open(path, 'wb') as fh:
                fh.write(data)
            log(f"   downloaded {os.path.basename(path)} ({len(data)/1024:.0f} KB)")
            paths.append(path)
        except Exception as e:
            log(f"   [WARNING] failed {u}: {e}")
    return paths


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

def normalize(name):
    return ''.join(ch for ch in str(name).lower() if ch.isalnum())


def find_col(cols, *keywords, exclude=()):
    """First column whose normalised header contains all keywords."""
    for c in cols:
        n = normalize(c)
        if all(k in n for k in keywords) and not any(x in n for x in exclude):
            return c
    return None


KNOWN_CODES = set()
DROPPED_CODES = {}


def load_known_codes(path="CodeViolations.csv"):
    """Load the authoritative violation code list, used to reject junk."""
    global KNOWN_CODES
    try:
        codes = pd.read_csv(path, dtype={'Violation Code': str})['Violation Code']
        KNOWN_CODES = {str(int(float(c))) for c in codes.dropna()}
        log(f"[INFO] Loaded {len(KNOWN_CODES)} known violation codes from {path}")
    except Exception as e:
        log(f"[WARNING] Could not load {path} ({e}); violation codes will not be validated")
        KNOWN_CODES = set()


def parse_violations(raw):
    """Normalise both '  30  32' and '6/2 7/3 10/1' into '30 32' / '6 7 10'.

    At least one historical file is ragged -- it carries a stray trailing column
    and a handful of rows are shifted, pushing reporting-area codes (605, 607)
    into the violation column. Validating against CodeViolations.csv catches that
    without having to special-case the file.
    """
    if pd.isna(raw):
        return ''
    codes = []
    for token in str(raw).split():
        code = token.split('/')[0].strip()
        if not code or code == PLACEHOLDER_CODE or not code.isdigit():
            continue
        code = str(int(code))
        if KNOWN_CODES and code not in KNOWN_CODES:
            DROPPED_CODES[code] = DROPPED_CODES.get(code, 0) + 1
            continue
        codes.append(code)
    return ' '.join(codes)


def map_inspection_type(v):
    if pd.isna(v):
        return ''
    s = str(v).strip()
    try:
        n = int(float(s))
    except ValueError:
        return s.upper()          # already textual (REGULAR / FOLLOWUP / ...)
    return NUMERIC_INSPECTION_TYPE.get(n, f'TYPE_{n}')


def data_sheet(book):
    """Pick the data sheet, skipping SplashBI's 'Report Filters' metadata sheet."""
    for s in book.sheet_names:
        if 'filter' not in s.lower():
            return s
    return book.sheet_names[0]


def read_report(path):
    """Read one report into a normalised frame, whichever schema era it uses."""
    try:
        book = pd.ExcelFile(path)
    except Exception as e:
        log(f"   [WARNING] cannot open {os.path.basename(path)}: {e}")
        return None

    df = book.parse(data_sheet(book))
    if df.empty:
        return None
    cols = list(df.columns)

    # The current report splits the name across columns and has no street
    # address; the historical ones use 'Est Number' / 'Premise ...'.
    permit = find_col(cols, 'permit') or find_col(cols, 'est', 'number')
    if permit is None:
        log(f"   [WARNING] no permit column in {os.path.basename(path)}: {cols}")
        return None

    date = find_col(cols, 'inspection', 'date') or find_col(cols, 'date', exclude=('open',))
    score = find_col(cols, 'score')
    viol = find_col(cols, 'violation') or find_col(cols, 'violations')
    itype = find_col(cols, 'inspection', 'type')
    addr = find_col(cols, 'premise', 'address') or find_col(cols, 'address')
    zipc = find_col(cols, 'zip') or find_col(cols, 'city')
    name = find_col(cols, 'premise', 'name')
    rfinsp = find_col(cols, 'rfinsp')
    esttype = find_col(cols, 'esttype') or find_col(cols, 'type', exclude=('inspection', 'est'))

    if name is not None:
        est_name = df[name].astype(str).str.strip()
    else:
        # Current-report layout: name is split across the columns between the
        # permit and the city/ZIP; the last of them holds the combined value.
        city_idx = cols.index(zipc) if zipc in cols else len(cols)
        parts = cols[cols.index(permit) + 1:city_idx]
        if not parts:
            log(f"   [WARNING] no name column in {os.path.basename(path)}")
            return None
        est_name = df[parts[-1]].astype(str).str.strip()
        if len(parts) > 1:
            joined = (df[parts[:-1]].fillna('').astype(str)
                      .agg(' '.join, axis=1).str.strip()
                      .str.replace(r'\s+', ' ', regex=True))
            est_name = est_name.mask(est_name.isin(['', 'nan']), joined)

    out = pd.DataFrame({
        'permit': pd.to_numeric(df[permit], errors='coerce'),
        'name': est_name,
        'address': df[addr].astype(str).str.strip() if addr else '',
        'zip': df[zipc].astype(str).str.strip() if zipc else '',
        'date': pd.to_datetime(df[date], errors='coerce') if date else pd.NaT,
        'itype': df[itype].apply(map_inspection_type) if itype else '',
        'foodretail': df[rfinsp].fillna('').astype(str).str.strip() if rfinsp else '',
        'esttype': df[esttype].astype(str).str.strip() if esttype is not None else '',
        'score': pd.to_numeric(df[score], errors='coerce') if score else pd.NA,
        'violations': df[viol].apply(parse_violations) if viol else '',
        'source': os.path.basename(path),
    })

    out = out.dropna(subset=['permit', 'date'])
    out = out[out['date'] >= MIN_DATE]
    out = out[out['date'] <= pd.Timestamp(datetime.now().date())]
    out['permit'] = out['permit'].astype(int).astype(str)

    # ZIP arrives as '40503', '40503.0' or 'LEXINGTON 40503' depending on era.
    out['zip'] = (out['zip'].astype(str)
                  .str.extract(r'(\d{5})', expand=False).fillna(''))
    # astype(str) on a NaN column yields the literal 'nan', which would otherwise
    # survive as a value and win the "last non-blank" pick in the lookup.
    for c in ('address', 'name', 'esttype', 'foodretail'):
        out[c] = (out[c].astype(str).str.strip()
                  .replace({'nan': '', 'None': '', 'NaT': '', '<NA>': ''}).fillna(''))
    out['esttype'] = out['esttype'].str.replace(r'\.0$', '', regex=True)

    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Backfill LFCHD inspection history")
    ap.add_argument("--reports-dir", default=os.path.join("Reports", "historical"),
                    help="Where downloaded reports are cached")
    ap.add_argument("--output", default="food_scores_history.csv",
                    help="Raw output CSV, matching the food_scores.csv layout")
    ap.add_argument("--establishments", default="establishments.csv",
                    help="Output lookup of Permit # -> name / address / ZIP")
    ap.add_argument("--scrape-date", default=None,
                    help="ScrapeDate to stamp on backfilled rows (default: today)")
    ap.add_argument("--refresh", action="store_true",
                    help="Re-discover report URLs from the site")
    ap.add_argument("--skip-download", action="store_true",
                    help="Use only reports already in --reports-dir")
    args = ap.parse_args()

    scrape_date = args.scrape_date or datetime.now().strftime('%Y-%m-%d')

    log("=" * 64)
    log("LFCHD HISTORICAL BACKFILL")
    log("=" * 64)

    load_known_codes()

    if args.skip_download:
        if not os.path.isdir(args.reports_dir):
            log(f"[ERROR] {args.reports_dir} does not exist")
            sys.exit(1)
        paths = [os.path.join(args.reports_dir, f)
                 for f in sorted(os.listdir(args.reports_dir))
                 if f.lower().endswith(('.xlsx', '.xls'))]
    else:
        urls = discover_urls() if args.refresh else (discover_urls() or FALLBACK_URLS)
        paths = download_all(urls, args.reports_dir)

    if not paths:
        log("[ERROR] No reports available to process")
        sys.exit(1)

    log(f"\n>> Normalising {len(paths)} report(s)...")
    frames = []
    for p in sorted(paths):
        f = read_report(p)
        if f is None or f.empty:
            continue
        log(f"   {os.path.basename(p)[:58]:58s} {len(f):6,d} rows  "
            f"{f['date'].min():%Y-%m-%d}..{f['date'].max():%Y-%m-%d}")
        frames.append(f)

    if not frames:
        log("[ERROR] Nothing could be normalised")
        sys.exit(1)

    allrows = pd.concat(frames, ignore_index=True)
    log(f"\n[INFO] {len(allrows):,} rows before deduplication")

    if DROPPED_CODES:
        detail = ', '.join(f"{c}x{n}" for c, n in sorted(DROPPED_CODES.items(),
                                                         key=lambda kv: -kv[1])[:10])
        log(f"[WARNING] Discarded {sum(DROPPED_CODES.values())} violation code(s) "
            f"not in CodeViolations.csv: {detail}")

    # Some visits carry no score and no violations -- largely inspection type 12,
    # which LFCHD does not score. They are real visits, so they are kept rather
    # than discarded; a blank Score makes them trivial to filter downstream.
    unscored = allrows['score'].isna() & (allrows['violations'] == '')
    if unscored.any():
        log(f"[INFO] {int(unscored.sum()):,} row(s) record an unscored visit "
            f"(no score, no violations) - kept, filter on blank Score to exclude")

    # Two kinds of duplication have to collapse here:
    #   * across files -- the 2023 dump repeats almost everything the 2019-2022
    #     extracts contain
    #   * within a file -- one inspection is emitted once per reporting area
    #     (TYPE 605/607/603/610), so a premise inspected as both food service and
    #     retail appears twice with identical score and violations
    # Violations stay in the key because ~370 same-day/same-score pairs carry
    # genuinely different violation lists and are distinct inspections.
    allrows = allrows.sort_values(['permit', 'date', 'source'])
    inspections = allrows.drop_duplicates(
        subset=['permit', 'date', 'itype', 'score', 'violations'])
    log(f"[INFO] {len(inspections):,} distinct inspections after deduplication")

    # ---- Establishment lookup: most recent non-blank values win.
    def best_name(series):
        """Pick a display name, undoing source-side truncation.

        LFCHD truncates names at different widths per era, so the newest record
        is often a clipped prefix of a fuller one ("...MARRIOTT MAIN" for
        "...MARRIOTT MAIN KITCHEN"). Take the most recent name, then prefer the
        longest name it is a prefix of -- that repairs truncation without
        resurrecting a genuinely superseded name from a real rename.
        """
        vals = [v for v in series if v]
        if not vals:
            return ''
        latest = vals[-1]
        stem = latest.rstrip(' &-,(').upper()
        longer = [v for v in vals if v.upper().startswith(stem) and len(v) > len(latest)]
        return max(longer, key=len) if longer else latest

    est = allrows.sort_values('date')
    lookup = (est.groupby('permit')
                 .agg(name=('name', best_name),
                      address=('address', lambda s: next((v for v in reversed(list(s)) if v), '')),
                      zip=('zip', lambda s: next((v for v in reversed(list(s)) if v), '')),
                      est_type=('esttype', lambda s: next((v for v in reversed(list(s)) if v), '')),
                      first_seen=('date', 'min'),
                      last_seen=('date', 'max'),
                      inspections=('date', 'size'))
                 .reset_index()
                 .rename(columns={'permit': 'Permit #', 'name': 'Establishment Name',
                                  'address': 'Address', 'zip': 'Zip',
                                  'est_type': 'Est Type', 'first_seen': 'First Seen',
                                  'last_seen': 'Last Seen', 'inspections': 'Inspections'}))
    lookup['First Seen'] = lookup['First Seen'].dt.strftime('%Y-%m-%d')
    lookup['Last Seen'] = lookup['Last Seen'].dt.strftime('%Y-%m-%d')
    lookup.to_csv(args.establishments, index=False)
    log(f"[SUCCESS] Wrote {args.establishments} ({len(lookup):,} establishments)")

    # ---- Raw rows in the pipeline's layout.
    raw = pd.DataFrame({
        '0': inspections['permit'],
        '1': inspections['name'],
        '2': inspections['address'],
        '3': inspections['date'].dt.strftime('%Y-%m-%d'),
        '4': inspections['itype'],
        '5': inspections['foodretail'],
        '6': inspections['score'],
        '7': inspections['violations'],
        'ScrapeDate': scrape_date,
        'Page': '',
        'Table': '',
        'SourceFile': inspections['source'],
    })[RAW_COLUMNS]

    raw.to_csv(args.output, index=False)
    log(f"[SUCCESS] Wrote {args.output} ({len(raw):,} rows)")

    # ---- Summary
    d = inspections['date']
    log("\n" + "=" * 64)
    log("BACKFILL SUMMARY")
    log("=" * 64)
    log(f"  Inspections:     {len(inspections):,}")
    log(f"  Establishments:  {inspections['permit'].nunique():,}")
    log(f"  Date range:      {d.min():%Y-%m-%d} to {d.max():%Y-%m-%d}")
    log(f"  With address:    {(lookup['Address'] != '').sum():,} / {len(lookup):,}")
    log(f"  With ZIP:        {(lookup['Zip'] != '').sum():,} / {len(lookup):,}")
    log("\n  Inspections per year:")
    for year, n in d.dt.year.value_counts().sort_index().items():
        log(f"     {year}  {n:6,d}")
    log("")


if __name__ == "__main__":
    main()
