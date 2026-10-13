"""Download the Brickset catalogue for the chosen themes and save sets.csv
(set number -> theme, year, pieces, official price, availability).
Run rarely (manually or monthly); the daily bot only reads sets.csv.
Needs env var BRICKSET_API_KEY. Requires: pip install requests"""
import csv
import json
import os
import sys
import time
from datetime import date

import requests

API = "https://brickset.com/api/v3.asmx"
KEY = os.environ.get("BRICKSET_API_KEY", "")
TERMS = ["star wars", "lord of the rings", "city", "icons", "ninjago",
         "super mario", "ideas", "bricklink"]
PRICE_REGIONS = ["ES", "DE"]  # first region with a price wins (DE as proxy for Spain)
PAGE_SIZE = 500
OUT = "sets.csv"
FIELDS = ["number", "name", "theme", "subtheme", "year", "pieces",
          "rrp", "rrp_region", "first_available", "last_available", "retired"]


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


def fetch_theme(theme):
    sets, page = [], 1
    while True:
        params = {"theme": theme, "pageSize": PAGE_SIZE, "pageNumber": page}
        body = call("getSets", params=json.dumps(params))
        batch = body.get("sets", [])
        sets.extend(batch)
        total = body.get("matches", len(sets))
        if not batch or len(sets) >= total:
            return sets
        page += 1
        time.sleep(1)


def to_row(s, today):
    lc = s.get("LEGOCom") or {}
    price = region = first = last = None
    for reg in PRICE_REGIONS:
        d = lc.get(reg) or {}
        if d.get("retailPrice") is not None:
            price, region = d["retailPrice"], reg
            first = (d.get("dateFirstAvailable") or "")[:10] or None
            last = (d.get("dateLastAvailable") or "")[:10] or None
            break
    avail = str(s.get("availability") or "").lower()
    retired = "yes" if (last and last <= today) or "retired" in avail else "no"
    return {
        "number": str(s.get("number")), "name": s.get("name"),
        "theme": s.get("theme"), "subtheme": s.get("subtheme"),
        "year": s.get("year"), "pieces": s.get("pieces"),
        "rrp": price, "rrp_region": region,
        "first_available": first, "last_available": last, "retired": retired,
    }


def main():
    if not KEY:
        sys.exit("BRICKSET_API_KEY is not set")
    today = date.today().isoformat()
    themes, candidates = pick_themes(call("getThemes")["themes"])
    print("Themes selected:", themes)
    for term, names in candidates.items():
        print(f"  also contains '{term}' (NOT selected):", names)
    rows = {}
    for th in themes:
        sets = fetch_theme(th)
        print(f"  {th}: {len(sets)} sets")
        for s in sets:
            if s.get("numberVariant") not in (None, 1):
                continue
            rows[str(s.get("number"))] = to_row(s, today)
        time.sleep(1)
    ordered = sorted(rows.values(), key=lambda r: r["number"])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(ordered)
    priced = sum(1 for r in ordered if r["rrp"] is not None)
    retired = sum(1 for r in ordered if r["retired"] == "yes")
    print(f"\nSaved {len(ordered)} sets to {OUT} | with price: {priced} | retired: {retired}")
    for num in ("75192", "75257"):
        print("check", num, "->", rows.get(num))


if __name__ == "__main__":
    main()
