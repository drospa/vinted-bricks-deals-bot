"""Vinted catalogue search: fetch a page of newest listings and parse them from the page HTML.
Vinted has no public API; the catalogue page embeds its data in Next.js payload chunks."""
import json
import random
import re
import time

from curl_cffi import requests as cr

from .config import ACCEPT_LANGUAGE, BASE, IMPERSONATE, PAUSE, QUERY

CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)
KEY = '"productItem":'


class FetchError(Exception):
    pass


def decode_payload(page_html):
    chunks = CHUNK.findall(page_html)
    if not chunks:
        return ""
    try:
        return json.loads('"' + "".join(chunks) + '"')
    except json.JSONDecodeError:
        parts = []
        for c in chunks:
            try:
                parts.append(json.loads('"' + c + '"'))
            except json.JSONDecodeError:
                pass
        return "".join(parts)


def parse_items(page_html, limit=300):
    text = decode_payload(page_html)
    dec = json.JSONDecoder()
    items, seen, pos = [], set(), 0
    while len(items) < limit:
        i = text.find(KEY, pos)
        if i < 0:
            break
        pos = i + len(KEY)
        brace = text.find("{", pos)
        if brace < 0:
            break
        try:
            obj, _ = dec.raw_decode(text, brace)
        except json.JSONDecodeError:
            continue
        if obj.get("id") in seen or obj.get("isPromoted") or not obj.get("id"):
            continue
        seen.add(obj["id"])
        price = obj.get("price") or {}
        rel = obj.get("url") or ""
        info = (obj.get("itemBox") or {}).get("secondLine") or ""
        try:
            amount = float(price.get("amount"))
        except (TypeError, ValueError):
            amount = None
        items.append({
            "id": int(obj["id"]),
            "title": (obj.get("title") or "").strip(),
            "price": amount,
            "url": rel if rel.startswith("http") else BASE + rel,
            "condition": info.split("·")[-1].strip() if info else "?",
        })
    return items


_session = {"s": None}


def new_session(target):
    _session["s"] = cr.Session(impersonate=target)


def fetch_page(page, query=QUERY):
    """Return listings for a page ([] = no listings). Raise FetchError on failure."""
    last = "no response"
    for target in IMPERSONATE:
        if _session["s"] is None:
            new_session(target)
        try:
            r = _session["s"].get(
                BASE + "/catalog",
                params={"search_text": query, "order": "newest_first", "page": page},
                timeout=25, headers={"Accept-Language": ACCEPT_LANGUAGE},
            )
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            _session["s"] = None
            continue
        if r.status_code == 200:
            found = parse_items(r.text)
            print(f"  fetched '{query}' page {page}: {len(found)} listings", flush=True)
            return found
        last = f"HTTP {r.status_code}"
        _session["s"] = None
        time.sleep(random.uniform(*PAUSE))
    raise FetchError(last)
