"""Download the Brickset catalogue for the chosen themes and save sets.csv
(set number -> theme, year, pieces, official price, availability).
Run rarely (manually or monthly); the daily bot only reads sets.csv.
Needs env var BRICKSET_API_KEY. Requires: pip install requests"""
import csv
import json
import statistics
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests

API = "https://brickset.com/api/v3.asmx"
KEY = os.environ.get("BRICKSET_API_KEY", "")
TERMS = ["star wars", "lord of the rings", "city", "icons", "ninjago",
         "super mario", "ideas", "bricklink"]
PRICE_REGIONS = ["ES", "DE"]  # euro prices: first region with a price wins (DE as proxy for Spain)
# Fallback when no euro price exists (mostly sets from before ~2014), marked approximate.
# The regional price is scaled by a factor calibrated in each build from sets that have both a
# DE price and that region's price (median DE/region ratio). Currency conversion is not used
# while calibration works: LEGO sets euro prices by price point, not by exchange rate
# (e.g. 79006: 29.99 GBP converts to ~35.5 EUR, but US 29.99 USD sat at the same price point).
# Order = preference (US first: its ratio to DE is the most stable, to be confirmed in the log).
FX_REGIONS = [("US", "USD"), ("UK", "GBP"), ("CA", "CAD")]
MIN_CALIBRATION = 30  # sets needed per region; below this, that region falls back to the ECB rate
FX_FALLBACK = {"GBP": 0.85, "USD": 1.10, "CAD": 1.50}  # units per 1 EUR, only if the ECB fetch fails
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
RETIRED_AFTER_YEARS = 3  # set with no LEGO.com data in any region and older than this: retired
# Promotional / gift-with-purchase sets: never sold at a price. Brickset tags are checked too;
# this list covers sets the tags miss. Verify against the build log ("promo" lines).
PROMO_SETS = {"40893", "40693", "40761"}
PROMO_TAG = re.compile(r"gift.with.purchase|\bgwp\b|promotional", re.I)
PAGE_SIZE = 500
OUT = "sets.csv"
FIELDS = ["number", "name", "theme", "subtheme", "year", "pieces",
          "rrp", "rrp_region", "rrp_approx", "promo",
          "first_available", "last_available", "retired"]
CHECK_SETS = ["75192", "75257", "10316", "79008", "79006", "9469", "40893", "40693", "40761"]


def call(method, **params):
    data = {"apiKey": KEY, "userHash": ""}
    data.update(params)
    r = requests.post(f"{API}/{method}", data=data, timeout=60,
                      headers={"User-Agent": "lego-deals-bot/0.1"})
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"{method}: {body.get('message', body)}")
    return body


def pick_themes(all_themes):
    chosen, candidates = [], {}
    for t in all_themes:
        name = t["theme"]
        low = name.lower()
        for term in TERMS:
            if low == term or (term in ("lord of the rings", "bricklink") and term in low):
                chosen.append(name)
            elif term in low or (term == "icons" and "creator" in low):
                candidates.setdefault(term, []).append(name)
    return sorted(set(chosen)), candidates


def fx_rates():
    """Units of each currency per 1 EUR, from the ECB daily reference rates."""
    try:
        r = requests.get(ECB_URL, timeout=30)
        r.raise_for_status()
        rates = {c.get("currency"): float(c.get("rate"))
                 for c in ET.fromstring(r.content).iter() if c.get("currency")}
        out = {cur: rates[cur] for cur in FX_FALLBACK if cur in rates}
        if len(out) == len(FX_FALLBACK):
            print("ECB rates per 1 EUR:", out)
            return out
        print("ECB response incomplete, using fallback rates")
    except Exception as e:  # network or parse error: the build must still finish
        print(f"ECB rates unavailable ({type(e).__name__}: {e}), using fallback rates")
    return dict(FX_FALLBACK)


def fetch_theme(theme):
    sets, page = [], 1
    while True:
        params = {"theme": theme, "pageSize": PAGE_SIZE, "pageNumber": page, "extendedData": 1}
        body = call("getSets", params=json.dumps(params))
        batch = body.get("sets", [])
        sets.extend(batch)
        total = body.get("matches", len(sets))
        if not batch or len(sets) >= total:
            return sets
        page += 1
        time.sleep(1)


def _dates(d):
    return (d.get("dateFirstAvailable") or "")[:10] or None, (d.get("dateLastAvailable") or "")[:10] or None


def is_promo(s):
    if str(s.get("number")) in PROMO_SETS:
        return True
    tags = (s.get("extendedData") or {}).get("tags") or []
    return any(PROMO_TAG.search(str(t)) for t in tags)


def calibrate(all_sets, fx):
    """Price factor per fallback region: median of DE price / region price over sets with both."""
    factors = {}
    for reg, cur in FX_REGIONS:
        ratios = []
        for s in all_sets:
            lc = s.get("LEGOCom") or {}
            de, other = (lc.get("DE") or {}).get("retailPrice"), (lc.get(reg) or {}).get("retailPrice")
            if de and other:
                ratios.append(de / other)
        if len(ratios) >= MIN_CALIBRATION:
            q = statistics.quantiles(ratios, n=4)
            factors[reg] = statistics.median(ratios)
            within = sum(1 for r in ratios if abs(r / factors[reg] - 1) <= 0.10) / len(ratios)
            print(f"Calibration {reg}: factor {factors[reg]:.3f} from {len(ratios)} sets "
                  f"(IQR {q[0]:.3f}-{q[2]:.3f}, {within:.0%} within ±10%)")
        elif fx.get(cur):
            factors[reg] = 1 / fx[cur]
            print(f"Calibration {reg}: only {len(ratios)} sets, using ECB rate factor {factors[reg]:.3f}")
    return factors


def to_row(s, today, factors):
    lc = s.get("LEGOCom") or {}
    price = region = first = last = None
    approx = False
    for reg in PRICE_REGIONS:
        d = lc.get(reg) or {}
        if d.get("retailPrice") is not None:
            price, region = d["retailPrice"], reg
            first, last = _dates(d)
            break
    if price is None:
        for reg, _cur in FX_REGIONS:
            d = lc.get(reg) or {}
            if d.get("retailPrice") and factors.get(reg):
                price, region, approx = round(d["retailPrice"] * factors[reg], 2), reg, True
                first, last = _dates(d)
                break
    promo = is_promo(s)
    if promo:
        price = region = None  # a gift has no sale price, whatever a region lists
        approx = False
    avail = str(s.get("availability") or "").lower()
    any_dates = any((lc.get(r) or {}).get("dateFirstAvailable") for r in lc)
    try:
        old = int(s.get("year") or 0) <= int(today[:4]) - RETIRED_AFTER_YEARS
    except ValueError:
        old = False
    retired = "yes" if ((last and last <= today) or "retired" in avail
                        or (not any_dates and old)) else "no"
    return {
        "number": str(s.get("number")), "name": s.get("name"),
        "theme": s.get("theme"), "subtheme": s.get("subtheme"),
        "year": s.get("year"), "pieces": s.get("pieces"),
        "rrp": price, "rrp_region": region,
        "rrp_approx": "yes" if approx else "", "promo": "yes" if promo else "",
        "first_available": first, "last_available": last, "retired": retired,
    }


def main():
    if not KEY:
        sys.exit("BRICKSET_API_KEY is not set")
    today = date.today().isoformat()
    fx = fx_rates()
    raw = {}
    themes, candidates = pick_themes(call("getThemes")["themes"])
    print("Themes selected:", themes)
    for term, names in candidates.items():
        print(f"  also contains '{term}' (NOT selected):", names)
    all_sets = []
    for th in themes:
        sets = fetch_theme(th)
        print(f"  {th}: {len(sets)} sets")
        all_sets += [s for s in sets if s.get("numberVariant") in (None, 1)]
        time.sleep(1)
    factors = calibrate(all_sets, fx)
    rows = {}
    for s in all_sets:
        rows[str(s.get("number"))] = to_row(s, today, factors)
        if str(s.get("number")) in CHECK_SETS:
            raw[str(s.get("number"))] = s
    ordered = sorted(rows.values(), key=lambda r: r["number"])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(ordered)
    priced = sum(1 for r in ordered if r["rrp"] is not None)
    approx = sum(1 for r in ordered if r["rrp_approx"])
    promo = sum(1 for r in ordered if r["promo"])
    retired = sum(1 for r in ordered if r["retired"] == "yes")
    print(f"\nSaved {len(ordered)} sets to {OUT} | with price: {priced} (approximate: {approx}) "
          f"| promo: {promo} | no price: {len(ordered) - priced - promo} | retired: {retired}")
    for num in CHECK_SETS:
        s = raw.get(num) or {}
        print("check", num, "->", rows.get(num))
        print("   LEGOCom:", json.dumps(s.get("LEGOCom")),
              "| tags:", (s.get("extendedData") or {}).get("tags"))


if __name__ == "__main__":
    main()
