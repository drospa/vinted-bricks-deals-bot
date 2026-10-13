"""Vinted feasibility v4: fetch the catalog HTML page with Chrome TLS
impersonation and parse listings from the embedded Next.js payload.
Requires: py -m pip install curl_cffi"""
import json
import re
import sys

from curl_cffi import requests as cr

BASE = "https://www.vinted.es"
SEARCH = sys.argv[1] if len(sys.argv) > 1 else "lego 75192"
CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)
KEY = '"productItem":'


def decode_payload(html):
    chunks = CHUNK.findall(html)
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


def parse_items(html, limit=50):
    text = decode_payload(html)
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
        if obj.get("id") in seen or obj.get("isPromoted"):
            continue
        seen.add(obj.get("id"))
        price = obj.get("price") or {}
        rel = obj.get("url") or ""
        items.append({
            "id": obj.get("id"),
            "title": (obj.get("title") or "").strip(),
            "price": price.get("amount"),
            "currency": price.get("currencyCode", "EUR"),
            "url": rel if rel.startswith("http") else BASE + rel,
            "info": (obj.get("itemBox") or {}).get("secondLine"),
        })
    return items


def fetch(params):
    last = None
    for target in ("chrome", "chrome120", "chrome124"):
        try:
            s = cr.Session(impersonate=target)
            last = s.get(BASE + "/catalog", params=params, timeout=25,
                         headers={"Accept-Language": "es-ES,es;q=0.9,en;q=0.8"})
            if last.status_code == 200:
                return last, target
        except Exception as e:
            print(f"  {target}: {type(e).__name__}: {e}")
    return last, None


if __name__ == "__main__":
    r, target = fetch({"search_text": SEARCH, "order": "newest_first"})
    if r is None:
        sys.exit("Sin respuesta")
    html = r.text
    print(f"HTTP {r.status_code} | {len(r.content)} bytes | impersonate={target}")
    print("chunks RSC:", len(CHUNK.findall(html)), "| 'productItem' en HTML:", "productItem" in html)
    items = parse_items(html)
    print("anuncios parseados:", len(items))
    for it in items[:10]:
        print(f"  {it['id']} | {it['price']} {it['currency']} | {it['title'][:60]} | {it['info']}\n    {it['url']}")
