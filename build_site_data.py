#!/usr/bin/env python3
"""
build_site_data.py

Turns the published dataset into the JSON the static site reads.

The site is plain files on GitHub Pages — no API, no database — so everything it
needs has to be small enough to hand a browser. That shapes the split:

  establishments.json  ~4k rows, loaded on every page (map + search)
  inspections.json     ~94k rows, fetched lazily the first time someone opens a
                       detail view, so the initial load stays light
  insights.json        pre-aggregated stats for the insights page
  geo.json             Fayette County + ZIP boundaries, simplified, so the map
                       needs no tile server and works offline

Usage:
    python build_site_data.py
"""

import json
import math
import os
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

OUT = os.path.join("site", "data")
JOINED = "joined_scores_violations.csv"
ESTABLISHMENTS = "establishments.csv"

# Score 0 is a "not scored" sentinel, not a failing grade — see README.
UNSCORED = 0
HALF_LIFE_DAYS = 365 * 2
TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"


def log(m=""):
    print(m, flush=True)


# ---------------------------------------------------------------- geometry
def simplify(points, tol):
    """Douglas-Peucker. Keeps the shape, drops the vertices nobody can see."""
    if len(points) < 3:
        return points
    ax, ay = points[0]
    bx, by = points[-1]
    dx, dy = bx - ax, by - ay
    denom = math.hypot(dx, dy)
    worst, idx = -1.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        d = (abs(dy * px - dx * py + bx * ay - by * ax) / denom) if denom else math.hypot(px - ax, py - ay)
        if d > worst:
            worst, idx = d, i
    if worst <= tol:
        return [points[0], points[-1]]
    return simplify(points[:idx + 1], tol)[:-1] + simplify(points[idx:], tol)


def clean_ring(ring, tol, nd=4):
    pts = simplify([(float(x), float(y)) for x, y in ring], tol)
    return [[round(x, nd), round(y, nd)] for x, y in pts]


def fetch_geo():
    """Fayette County outline + ZIP boundaries, simplified for the browser."""
    def q(url):
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))

    out = {'county': [], 'zips': []}
    try:
        county = q(f"{TIGER}/State_County/MapServer/1/query?" + urllib.parse.urlencode({
            'where': "STATE='21' AND COUNTY='067'", 'outFields': 'BASENAME',
            'returnGeometry': 'true', 'outSR': '4326', 'f': 'geojson'}))
        for f in county['features']:
            g = f['geometry']
            polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
            for poly in polys:
                out['county'].append(clean_ring(poly[0], 0.0008))
    except Exception as e:
        log(f"[WARNING] county boundary unavailable ({e}) — map will omit it")

    try:
        z = q(f"{TIGER}/PUMA_TAD_TAZ_UGA_ZCTA/MapServer/4/query?" + urllib.parse.urlencode({
            'where': "BASENAME LIKE '405%'", 'outFields': 'BASENAME',
            'returnGeometry': 'true', 'outSR': '4326', 'f': 'geojson'}))
        for f in z['features']:
            g = f['geometry']
            polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
            rings = [clean_ring(p[0], 0.0006) for p in polys]
            out['zips'].append({'zip': f['properties'].get('BASENAME', ''), 'rings': rings})
    except Exception as e:
        log(f"[WARNING] ZIP boundaries unavailable ({e}) — map will omit them")

    return out


# ---------------------------------------------------------------- main
def main():
    if not os.path.isfile(JOINED):
        log(f"[ERROR] {JOINED} not found — run the pipeline first")
        sys.exit(1)
    os.makedirs(OUT, exist_ok=True)

    log("=" * 64)
    log("BUILD SITE DATA")
    log("=" * 64)

    d = pd.read_csv(JOINED, low_memory=False)
    d['Date'] = pd.to_datetime(d['Date'], errors='coerce')
    d['Score'] = pd.to_numeric(d['Score'], errors='coerce')
    d['Permit #'] = d['Permit #'].astype('Int64').astype(str)
    d = d.dropna(subset=['Date'])

    insp = d.drop_duplicates(subset=['Permit #', 'Date', 'Inspection Type', 'Score']).copy()
    scored = insp[insp['Score'].notna() & (insp['Score'] > UNSCORED)]
    ASOF = insp['Date'].max()
    log(f"[INFO] {len(insp):,} inspections, {len(scored):,} scored, as-of {ASOF:%Y-%m-%d}")

    # ---- per-establishment rollup
    def weighted(g):
        w = 0.5 ** ((ASOF - g['Date']).dt.days / HALF_LIFE_DAYS)
        return float(np.average(g['Score'], weights=w))

    agg = scored.groupby('Permit #').agg(
        n=('Score', 'size'), plain=('Score', 'mean'),
        worst=('Score', 'min'), first=('Date', 'min'), last=('Date', 'max'))
    agg['latest'] = scored.sort_values('Date').groupby('Permit #')['Score'].last()
    agg['weighted'] = scored.groupby('Permit #').apply(weighted, include_groups=False)

    est = pd.read_csv(ESTABLISHMENTS, dtype={'Permit #': str, 'Zip': str})
    est = est.set_index('Permit #')
    have_geo = 'lat' in est.columns

    rows = []
    for pid, r in agg.iterrows():
        e = est.loc[pid] if pid in est.index else None
        lat = lon = None
        if e is not None and have_geo and pd.notna(e.get('lat')):
            lat, lon = round(float(e['lat']), 5), round(float(e['lon']), 5)
        rows.append({
            'p': pid,
            'n': (e['Establishment Name'] if e is not None else ''),
            'a': (e['Address'] if e is not None and pd.notna(e['Address']) else ''),
            'z': (e['Zip'] if e is not None and pd.notna(e['Zip']) else ''),
            'lat': lat, 'lon': lon,
            'c': int(r['n']),
            'l': round(float(r['latest']), 1),
            'w': round(float(r['weighted']), 1),
            'v': round(float(r['plain']), 1),
            'x': round(float(r['worst']), 1),
            'f': r['first'].strftime('%Y-%m-%d'),
            't': r['last'].strftime('%Y-%m-%d'),
        })

    with open(os.path.join(OUT, "establishments.json"), "w", encoding="utf-8") as f:
        json.dump({'asof': ASOF.strftime('%Y-%m-%d'), 'half_life_years': HALF_LIFE_DAYS / 365,
                   'items': rows}, f, separators=(',', ':'))
    geo_n = sum(1 for r in rows if r['lat'] is not None)
    log(f"[SUCCESS] establishments.json — {len(rows):,} places, {geo_n:,} with coordinates")

    # ---- inspection history (lazy-loaded)
    vio = (d.dropna(subset=['Violation Code'])
             .assign(code=lambda x: x['Violation Code'].astype(float).astype(int).astype(str))
             .groupby(['Permit #', 'Date', 'Inspection Type'])['code']
             .apply(lambda s: sorted(set(s), key=int)).rename('codes').reset_index())
    hist = insp.merge(vio, on=['Permit #', 'Date', 'Inspection Type'], how='left')
    hist['codes'] = hist['codes'].apply(lambda v: v if isinstance(v, list) else [])

    by_permit = {}
    for pid, g in hist.sort_values('Date').groupby('Permit #'):
        by_permit[pid] = [
            {'d': r['Date'].strftime('%Y-%m-%d'),
             't': (r['Inspection Type'] if pd.notna(r['Inspection Type']) else ''),
             's': (None if pd.isna(r['Score']) else round(float(r['Score']), 1)),
             'v': r['codes']}
            for _, r in g.iterrows()]
    with open(os.path.join(OUT, "inspections.json"), "w", encoding="utf-8") as f:
        json.dump(by_permit, f, separators=(',', ':'))
    log(f"[SUCCESS] inspections.json — {sum(len(v) for v in by_permit.values()):,} inspections")

    # ---- violation code lookup
    codes = pd.read_csv("CodeViolations.csv", dtype={'Violation Code': str})
    cmap = {str(int(float(r['Violation Code']))): {'t': r['Violation Explanation'],
                                                   'c': r['Category']}
            for _, r in codes.iterrows() if pd.notna(r['Violation Code'])}

    # ---- insights aggregates
    sc = scored[scored['Date'] >= '2005-01-01'].copy()
    sc['yr'] = sc['Date'].dt.year
    g = sc.groupby('yr')['Score']
    yearly = [{'year': int(y), 'n': int(g.size()[y]), 'median': float(g.median()[y]),
               'q1': float(g.quantile(.25)[y]), 'q3': float(g.quantile(.75)[y]),
               'mean': round(float(g.mean()[y]), 2)}
              for y in sorted(g.size().index) if g.size()[y] > 200]

    bins = [0, 70, 75, 80, 85, 90, 95, 98, 100, 101]
    labels = ['<70', '70-74', '75-79', '80-84', '85-89', '90-94', '95-97', '98-99', '100']
    cut = pd.cut(scored['Score'], bins=bins, labels=labels, include_lowest=True, right=False)
    dist = cut.value_counts().reindex(labels).fillna(0)
    assert int(dist.sum()) == len(scored)

    vjoin = d.dropna(subset=['Violation Code'])
    top = (vjoin.groupby(['Violation Code', 'Violation Explanation', 'Category'])
                .size().reset_index(name='n').sort_values('n', ascending=False).head(12))

    zsrc = scored.merge(est[['Zip']], left_on='Permit #', right_index=True, how='left')
    zsrc = zsrc[zsrc['Zip'].notna() & (zsrc['Zip'] != '')]
    zz = (zsrc.groupby('Zip').agg(n=('Score', 'size'), median=('Score', 'median'),
                                  mean=('Score', 'mean'),
                                  establishments=('Permit #', 'nunique')).reset_index())
    zz = zz[zz['n'] >= 300].sort_values('mean')

    elig = agg[(agg['n'] >= 10) & (agg['last'] >= '2025-01-01')].copy()
    elig['gap'] = elig['latest'] - elig['weighted']
    names = est['Establishment Name']

    def pack(df, cols):
        out = []
        for pid, r in df.iterrows():
            item = {'p': pid, 'name': names.get(pid, ''),
                    'n': int(r['n']), 'latest': round(float(r['latest']), 0),
                    'weighted': round(float(r['weighted']), 1),
                    'plain': round(float(r['plain']), 1)}
            if 'gap' in cols:
                item['gap'] = round(float(r['gap']), 1)
            out.append(item)
        return out

    insights = {
        'headline': {
            'inspections': int(len(insp)), 'scored': int(len(scored)),
            'establishments': int(d['Permit #'].nunique()),
            'violations_recorded': int(d['Violation Code'].notna().sum()),
            'first': insp['Date'].min().strftime('%Y-%m-%d'),
            'last': ASOF.strftime('%Y-%m-%d'),
        },
        'yearly': yearly,
        'distribution': [{'band': b, 'n': int(dist[b])} for b in labels],
        'top_violations': [{'code': str(int(float(r['Violation Code']))),
                            'text': r['Violation Explanation'], 'category': r['Category'],
                            'n': int(r['n'])} for _, r in top.iterrows()],
        'by_zip': [{'zip': r['Zip'], 'n': int(r['n']), 'median': float(r['median']),
                    'mean': round(float(r['mean']), 2),
                    'establishments': int(r['establishments'])} for _, r in zz.iterrows()],
        'metric_eligible': int(len(elig)),
        'clean_now_bad_history': pack(elig.sort_values('gap', ascending=False).head(12), ['gap']),
        'persistent': pack(elig.sort_values('weighted').head(12), []),
        # every eligible point, named — the scatter labels all of them on hover
        'scatter': [{'x': round(float(r['weighted']), 1), 'y': round(float(r['latest']), 0),
                     'n': int(r['n']), 'name': names.get(pid, ''), 'p': pid}
                    for pid, r in elig.iterrows()],
        'coverage': {
            'gap_start': '2024-02-15', 'gap_end': '2024-04-30',
            'unscored_visits': int(insp['Score'].isna().sum()),
            'zero_sentinel_excluded': int((insp['Score'] == 0).sum()),
            'establishments_total': int(len(est)),
            'with_address': int((est['Address'].fillna('') != '').sum()),
            'with_zip': int((est['Zip'].fillna('') != '').sum()),
            'geocoded': geo_n,
        },
        'codes': cmap,
    }
    with open(os.path.join(OUT, "insights.json"), "w", encoding="utf-8") as f:
        json.dump(insights, f, separators=(',', ':'))
    log(f"[SUCCESS] insights.json — {len(insights['scatter']):,} scatter points, all named")

    # ---- boundaries
    geo_path = os.path.join(OUT, "geo.json")
    if os.path.isfile(geo_path):
        log("[INFO] geo.json already present — leaving it alone (boundaries do not change)")
    else:
        log("[INFO] Fetching Fayette County and ZIP boundaries…")
        geo = fetch_geo()
        with open(geo_path, "w", encoding="utf-8") as f:
            json.dump(geo, f, separators=(',', ':'))
        log(f"[SUCCESS] geo.json — county rings {len(geo['county'])}, ZIP areas {len(geo['zips'])}")

    log("\n  output sizes:")
    for fn in sorted(os.listdir(OUT)):
        kb = os.path.getsize(os.path.join(OUT, fn)) / 1024
        log(f"     {fn:24s} {kb:8,.0f} KB")
    log("")


if __name__ == "__main__":
    main()
