#!/usr/bin/env python3
"""
geocode_establishments.py

Adds latitude/longitude to establishments.csv using the U.S. Census Bureau's
batch geocoder — free, no API key, and built for exactly this shape of data.

The LFCHD reports carry a street address and ZIP but no coordinates, so the map
needs this step. Results are cached in geocode_cache.csv: an address is only
sent once, and re-running only geocodes what is new. That matters because a full
pass is a few thousand addresses and the service is rate-limited in practice.

Usage:
    python geocode_establishments.py
    python geocode_establishments.py --retry-failed   # re-attempt No_Match rows
    python geocode_establishments.py --batch-size 500
"""

import argparse
import csv
import io
import os
import sys
import time

import pandas as pd

try:
    import requests
except ImportError:
    print("[ERROR] This script needs the 'requests' package:  pip install requests")
    sys.exit(1)

ENDPOINT = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BENCHMARK = "Public_AR_Current"
CITY, STATE = "LEXINGTON", "KY"

CACHE_COLS = ['Permit #', 'query', 'status', 'matched_address', 'lat', 'lon']


def log(m=""):
    print(m, flush=True)


def normalise(addr: str) -> str:
    """Tidy an address enough for the geocoder without changing its meaning."""
    a = ' '.join(str(addr).split()).upper().strip(' ,')
    # Suite/unit noise is a common cause of No_Match and never helps placement.
    for sep in [' STE ', ' SUITE ', ' UNIT ', ' APT ', ' #', ' BLDG ']:
        if sep in a:
            a = a.split(sep)[0].strip(' ,')
    return a


def aggressive_normalise(addr: str) -> str:
    """Second-tier cleanup, used only for addresses the geocoder rejected.

    The failures cluster into a few fixable shapes — a bare unit number tacked
    on the end ("400 OLD VINE ST 114"), a lot number ("... RD, LOT 8"), and
    abbreviated directionals carrying a period ("1200 S. BROADWAY") — plus a
    residue that is genuinely not an address (PO boxes, and a few rows where the
    address column holds something else entirely).
    """
    import re
    a = normalise(addr)
    if not a or a.startswith(('P.O.', 'PO BOX', 'P O BOX')):
        return ''
    if not re.match(r'^\d', a):      # a real street address starts with a number
        return ''
    a = re.sub(r',?\s+(LOT|SPACE|SP|RM|ROOM)\s+\S+$', '', a)
    a = re.sub(r'\b([NSEW])\.\s*', r'\1 ', a)          # "S." -> "S "
    a = re.sub(r'\s+\d{1,4}[A-Z]?$', '', a)            # trailing bare unit number
    return ' '.join(a.split()).strip(' ,')


def load_cache(path):
    if os.path.isfile(path):
        c = pd.read_csv(path, dtype={'Permit #': str, 'lat': float, 'lon': float})
        for col in CACHE_COLS:
            if col not in c.columns:
                c[col] = None
        return c[CACHE_COLS]
    return pd.DataFrame(columns=CACHE_COLS)


def send_batch(rows, attempt_note=""):
    """POST one batch. rows = list of (permit, street, zipcode)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    for permit, street, zc in rows:
        w.writerow([permit, street, CITY, STATE, zc])
    payload = buf.getvalue().encode()

    files = {'addressFile': ('addresses.csv', payload, 'text/csv')}
    data = {'benchmark': BENCHMARK}
    r = requests.post(ENDPOINT, files=files, data=data, timeout=600)
    r.raise_for_status()

    out = []
    for rec in csv.reader(io.StringIO(r.text)):
        # id, input, match, matchtype, matched address, "lon,lat", tigerline, side
        if len(rec) < 3:
            continue
        pid, status = rec[0], rec[2]
        matched, lat, lon = '', None, None
        if status == 'Match' and len(rec) >= 6 and ',' in rec[5]:
            matched = rec[4]
            try:
                lon_s, lat_s = rec[5].split(',')
                lon, lat = float(lon_s), float(lat_s)
            except ValueError:
                status = 'Parse_Error'
        out.append({'Permit #': pid, 'status': status,
                    'matched_address': matched, 'lat': lat, 'lon': lon})
    return out


def main():
    ap = argparse.ArgumentParser(description="Geocode establishments via the Census batch API")
    ap.add_argument("--establishments", default="establishments.csv")
    ap.add_argument("--cache", default="geocode_cache.csv")
    ap.add_argument("--batch-size", type=int, default=1000,
                    help="Addresses per request (Census allows up to 10,000)")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Re-attempt addresses previously returned as No_Match")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only geocode this many new addresses (for a trial run)")
    args = ap.parse_args()

    log("=" * 64)
    log("GEOCODE ESTABLISHMENTS  (U.S. Census batch geocoder)")
    log("=" * 64)

    est = pd.read_csv(args.establishments, dtype={'Permit #': str, 'Zip': str})
    est['query'] = est['Address'].fillna('').map(normalise)
    have_addr = est[est['query'] != ''].copy()
    log(f"[INFO] {len(est):,} establishments, {len(have_addr):,} with a usable street address")

    cache = load_cache(args.cache)
    log(f"[INFO] {len(cache):,} addresses already in {args.cache}")

    done = set(cache.loc[cache['status'] == 'Match', 'query'])
    if not args.retry_failed:
        done |= set(cache['query'].dropna())

    todo = have_addr[~have_addr['query'].isin(done)].drop_duplicates('query')
    if args.limit:
        todo = todo.head(args.limit)
    log(f"[INFO] {len(todo):,} addresses to geocode this run")

    results = []
    if len(todo):
        batches = [todo.iloc[i:i + args.batch_size] for i in range(0, len(todo), args.batch_size)]
        for bi, b in enumerate(batches, 1):
            rows = [(r['Permit #'], r['query'], (r['Zip'] if pd.notna(r['Zip']) else ''))
                    for _, r in b.iterrows()]
            log(f"   batch {bi}/{len(batches)} — {len(rows)} addresses…")
            for attempt in range(1, 4):
                try:
                    got = send_batch(rows)
                    break
                except Exception as e:
                    if attempt == 3:
                        log(f"   [WARNING] batch {bi} failed after 3 attempts: {e}")
                        got = []
                    else:
                        log(f"   [WARNING] batch {bi} attempt {attempt} failed ({e}); retrying…")
                        time.sleep(10 * attempt)
            qmap = dict(zip(b['Permit #'].astype(str), b['query']))
            for g in got:
                g['query'] = qmap.get(str(g['Permit #']), '')
            results.extend(got)
            matched = sum(1 for g in got if g['status'] == 'Match')
            log(f"      matched {matched}/{len(rows)}")

    if results:
        new = pd.DataFrame(results)[CACHE_COLS]
        keep = cache[~cache['query'].isin(new['query'])]
        cache = new if keep.empty else pd.concat([keep, new], ignore_index=True)
        cache.to_csv(args.cache, index=False)
        log(f"[SUCCESS] Cache now holds {len(cache):,} addresses -> {args.cache}")

    # ---- Second pass: retry rejects under the aggressive normalisation
    if args.retry_failed:
        failed = cache[cache['status'] != 'Match'].copy()
        failed['retry'] = failed['query'].map(aggressive_normalise)
        already = set(cache.loc[cache['status'] == 'Match', 'query'])
        retry = failed[(failed['retry'] != '') & (failed['retry'] != failed['query'])
                       & (~failed['retry'].isin(already))].drop_duplicates('retry')
        skipped = int((failed['retry'] == '').sum())
        log(f"\n[INFO] Retry pass: {len(retry):,} rewritten addresses "
            f"({skipped:,} are not street addresses and were skipped)")

        r2 = []
        batches = [retry.iloc[i:i + args.batch_size] for i in range(0, len(retry), args.batch_size)]
        for bi, b in enumerate(batches, 1):
            rows = [(r['Permit #'], r['retry'], '') for _, r in b.iterrows()]
            log(f"   retry batch {bi}/{len(batches)} — {len(rows)} addresses…")
            try:
                got = send_batch(rows)
            except Exception as e:
                log(f"   [WARNING] retry batch {bi} failed: {e}")
                continue
            qmap = dict(zip(b['Permit #'].astype(str), b['retry']))
            for g in got:
                g['query'] = qmap.get(str(g['Permit #']), '')
            r2.extend(got)
            log(f"      matched {sum(1 for g in got if g['status'] == 'Match')}/{len(rows)}")

        if r2:
            newer = pd.DataFrame(r2)[CACHE_COLS]
            cache = pd.concat([cache, newer], ignore_index=True)
            cache.to_csv(args.cache, index=False)
            # Map the rewritten form back onto the original address string.
            back = dict(zip(failed['retry'], failed['query']))
            extra = newer[newer['status'] == 'Match'].copy()
            extra['query'] = extra['query'].map(lambda q: back.get(q, q))
            cache = pd.concat([cache, extra], ignore_index=True)
            log(f"[SUCCESS] Retry recovered {len(extra):,} more addresses")

    # ---- Merge coordinates back onto establishments.csv
    hits = cache[cache['status'] == 'Match'].drop_duplicates('query').set_index('query')
    est['lat'] = est['query'].map(hits['lat'])
    est['lon'] = est['query'].map(hits['lon'])
    est = est.drop(columns=['query'])
    est.to_csv(args.establishments, index=False)

    got_n = int(est['lat'].notna().sum())
    addr_n = int((est['Address'].fillna('') != '').sum())
    log("")
    log("=" * 64)
    log("GEOCODING SUMMARY")
    log("=" * 64)
    log(f"  establishments          : {len(est):,}")
    log(f"  with a street address   : {addr_n:,}")
    log(f"  geocoded                : {got_n:,}  ({100*got_n/max(1,addr_n):.1f}% of those with an address)")
    log(f"  no coordinates          : {len(est)-got_n:,}")
    if len(cache):
        log("\n  cache status breakdown:")
        for k, v in cache['status'].value_counts().items():
            log(f"     {k:14s} {v:6,d}")
    log("")


if __name__ == "__main__":
    main()
