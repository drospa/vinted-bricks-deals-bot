"""Daily Lego deals digest.
Vinted (newest 'lego' listings) -> set number from title -> sets.csv official
price -> discount filter -> Telegram message.
Env: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DRY_RUN (true = print only, keep state).
Requires: pip install curl_cffi requests"""
import csv
import html
import json
import os
import random
import re
import sys
import time
from datetime import datetime

import requests
from curl_cffi import requests as cr

# ---------------- configuration ----------------
BASE = "https://www.vinted.es"
QUERY = "lego"
MIN_DISCOUNT_NEW = 0.40   # new listings (with / without tags)
MIN_DISCOUNT_USED = 0.40  # used listings (Muy bueno, Bueno, Satisfactorio)
TOO_GOOD = 0.75           # at or above this: listed separately as suspicious
MAX_SUSPICIOUS = 3        # suspicious listings shown at the bottom
LOTR_QUERIES = ["lego señor de los anillos", "lego lord of the rings", "lego lotr"]
LOTR_PAGES = 3           # pages fetched per extra LOTR search
MAX_ITEMS = 10           # max deals listed in the message
MAX_PAGES = 15           # safety cap on pages fetched per run
PAUSE = (2.0, 5.0)       # random pause between pages (seconds)
STATE_FILE = "state.json"
CATALOGUE = "sets.csv"
IMPERSONATE = ["chrome", "chrome120", "chrome124"]

EXCLUDE = re.compile(
    r"\b(compatible|compatibles|kompatibel|compatibile|moc|custom|clone|clon"
    r"|incompleto|incompleta|incomplete|incomplet|unvollst\w+"
    r"|lote|lot de|bundle"
    r"|caja vac\w+|empty box|bo[iî]te vide|leere? (box|schachtel|verpackung)"
    r"|solo (la )?caja|only (the )?box|box only|seule bo[iî]te"
    r"|(solo|only|nur|seulement|uniquement) (las? )?(instrucciones|instructions|manual|notice|anleitung)"
    r"|(instrucciones|instructions|manual|notice|anleitung) only"
    r"|pi[eè]ces d[ée]tach[ée]es|piezas sueltas|pour pi[eè]ces|for parts|spare parts|repuestos?)\b",
    re.I,
)
NUM_RE = re.compile(
    r"(?<![\d.,])(\d{4,6})(?:-\d{1,2})?(?!\d)"
    r"(?!\s*(?:€|eur|pcs|pzs|pz|piezas|pieces|pièces|teile))",
    re.I,
)

# Extra exclusions (all themes): knock-offs, BrickHeadz LOTR, numbered instruction booklets
EXTRA_EXCLUDE = re.compile(
    r"\b(type lego|tipo lego|estilo lego|style lego|no ?lego|not lego|r[ée]plique|r[ée]plica|replica"
    r"|brick ?-?heads?|brickz?headz|(?:4063[0-2]){1,3}"  # BrickHeadz LOTR (40630-40632)
    r"|(istruzioni|instrucciones|instructions|anleitung|notice|manual)\s*(n[°º.]?\s*)?\d+)\b", re.I)
# Loose figures: excluded for every theme EXCEPT Star Wars and Lord of the Rings
_FROM_SET = r"(from|out of|del|du|dal|aus dem)\s+(the\s+|el\s+|le\s+|il\s+)?(set|lot)"
FIG_EXCL = re.compile(
    r"\b(mini[ -]?fig\w*|figurines?|figurita\w*|personnages?|" + _FROM_SET + r"|(cty|twn|njo|hp|sh|col)\d{2,4})\b", re.I)
# Used to tag loose figures that are kept for Star Wars / LOTR
FIG_RE = re.compile(
    r"\b(mini[ -]?fig\w*|figurines?|figurita\w*|personnages?|figuras?|figures?|figuur|figuren|"
    + _FROM_SET + r"|(lor|sw)\d{2,4})\b", re.I)
SW_NAME = re.compile(r"\b(star ?wars|guerra de las galaxias|guerre des [eé]toiles)\b", re.I)
MAX_SW_FIGURES = 15       # identified Star Wars loose figures shown per message

# Unidentified LOTR listings that are not LEGO sets (video games, puzzles, keychains, knock-off bricks)
LOTR_JUNK = re.compile(
    r"\b(ps[345]|xbox|playstation|nintendo|wii|3ds|2ds|ds|pc|jeu|juego|videojuego|game|puzzle|dimensions"
    r"|llavero|keychain|porte[- ]cl[eé]s?|bloques|bausteine)\b", re.I)

# Lord of the Rings: no discount filter, every finding is listed
LOTR_THEME = re.compile(r"lord of the rings", re.I)
LOTR_NAME = re.compile(
    r"\b(lord of the rings|se[ñn]or de los anillos|seigneur des anneaux"
    r"|herr der ringe|signore degli anelli|lotr)\b", re.I)

# ---------------- Vinted ----------------
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
                timeout=25, headers={"Accept-Language": "es-ES,es;q=0.9,en;q=0.8"},
            )
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            _session["s"] = None
            continue
        if r.status_code == 200:
            return parse_items(r.text)
        last = f"HTTP {r.status_code}"
        _session["s"] = None
        time.sleep(random.uniform(*PAUSE))
    raise FetchError(last)


# ---------------- matching ----------------
def load_catalogue(path=CATALOGUE):
    cat = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rrp = float(row["rrp"]) if row["rrp"] else None
            except ValueError:
                rrp = None
            cat[row["number"]] = {
                "name": row["name"], "theme": row["theme"], "rrp": rrp,
                "retired": row["retired"] == "yes",
            }
    return cat


def find_set(title, catalogue):
    found = []
    for m in NUM_RE.finditer(title):
        n = m.group(1)
        if len(n) == 4 and 1990 <= int(n) <= 2030:  # looks like a year
            continue
        if n in catalogue and n not in found:
            found.append(n)
    return found[0] if len(found) == 1 else None


def evaluate(items, catalogue):
    deals, lotr, sw_figs = [], [], []
    stats = {"scanned": len(items), "excluded": 0, "matched": 0, "no_price": 0}
    for it in items:
        t = it["title"]
        if EXCLUDE.search(t) or EXTRA_EXCLUDE.search(t):
            stats["excluded"] += 1
            continue
        num = find_set(t, catalogue)
        c = catalogue.get(num) if num else None
        is_lotr = bool((c and LOTR_THEME.search(c["theme"] or "")) or (not c and LOTR_NAME.search(t)))
        is_sw = bool((c and c["theme"] == "Star Wars") or (not c and SW_NAME.search(t)))
        if not (is_lotr or is_sw) and FIG_EXCL.search(t):
            stats["excluded"] += 1
            continue
        if is_lotr and not c and LOTR_JUNK.search(t):
            stats["excluded"] += 1
            continue
        is_fig = bool((is_lotr or is_sw) and FIG_RE.search(t))
        if is_lotr:
            rrp = c["rrp"] if c else None
            disc = (1 - it["price"] / rrp) if rrp and it["price"] else None
            lotr.append({**it, "set_no": num or "?", "set_name": c["name"] if c else "set not identified",
                         "rrp": rrp, "retired": bool(c and c["retired"]), "discount": disc, "figure": is_fig})
            if c:
                stats["matched"] += 1
            continue
        if not c:
            continue
        stats["matched"] += 1
        if is_fig:  # loose Star Wars figure: the set's official price says nothing about it, so no discount test
            sw_figs.append({**it, "set_no": num, "set_name": c["name"], "theme": c["theme"],
                            "rrp": c["rrp"], "retired": c["retired"], "discount": None})
            continue
        if not c["rrp"] or not it["price"] or it["price"] <= 0:
            stats["no_price"] += 1
            continue
        discount = 1 - it["price"] / c["rrp"]
        is_new = it["condition"].lower().startswith("nuevo")
        if discount >= (MIN_DISCOUNT_NEW if is_new else MIN_DISCOUNT_USED):
            deals.append({**it, "set_no": num, "set_name": c["name"], "theme": c["theme"],
                          "rrp": c["rrp"], "retired": c["retired"], "discount": discount})
    deals.sort(key=lambda d: d["discount"], reverse=True)
    lotr.sort(key=lambda d: (d["discount"] is None, -(d["discount"] or 0)))
    suspicious = [d for d in deals if d["discount"] >= TOO_GOOD]
    deals = [d for d in deals if d["discount"] < TOO_GOOD]
    sw_figs.sort(key=lambda d: d["id"], reverse=True)
    return deals, suspicious, lotr, sw_figs, stats


# ---------------- message / telegram ----------------
def build_messages(deals, suspicious, lotr, sw_figs, stats, warnings, today):
    esc = html.escape
    head = f"🧱 <b>Lego deals {today}</b>: {len(deals)} found" + (
        f" · {len(lotr)} Lord of the Rings" if lotr else "") + (
        f" · {len(sw_figs)} Star Wars figures" if sw_figs else "")
    blocks = []
    for i, d in enumerate(deals[:MAX_ITEMS], 1):
        flags = " 🏷️ retired" if d["retired"] else ""
        blocks.append(
            f"\n{i}. <b>{esc(d['set_no'])} {esc(d['set_name'])}</b>\n"
            f"{d['price']:.0f}€ vs {d['rrp']:.0f}€ (−{d['discount'] * 100:.0f}%) · "
            f"{esc(d['condition'])} · {esc(d['theme'])}{flags}\n"
            f"<a href=\"{esc(d['url'], quote=True)}\">Open on Vinted</a>"
        )
    if len(deals) > MAX_ITEMS:
        blocks.append(f"\n… and {len(deals) - MAX_ITEMS} more")
    if sw_figs:
        blocks.append("\n🧍 <b>Star Wars loose figures</b> (set number found in title; no discount filter, newest first):")
        for d in sw_figs[:MAX_SW_FIGURES]:
            blocks.append(
                f"\n• <b>{esc(d['set_no'])} {esc(d['set_name'])}</b>: {d['price']:.0f}€ · {esc(d['condition'])} · "
                f"<a href=\"{esc(d['url'], quote=True)}\">link</a>")
        if len(sw_figs) > MAX_SW_FIGURES:
            blocks.append(f"\n… and {len(sw_figs) - MAX_SW_FIGURES} more")
    if lotr:
        blocks.append("\n🧙 <b>Lord of the Rings</b> (all listings, no discount filter):")
        for d in lotr:
            price = f"{d['price']:.0f}€" if d["price"] else "?"
            ref = (f" vs {d['rrp']:.0f}€ ({-d['discount'] * 100:+.0f}%)" if d["discount"] is not None
                   else ("" if d["set_no"] == "?" else " (no official price)"))
            blocks.append(
                f"\n• <b>{esc(d['set_no'])} {esc(d['set_name'])}</b>: {price}{ref} · {esc(d['condition'])}"
                f"{' 🏷️ retired' if d['retired'] else ''}{' 🧍 figure' if d.get('figure') else ''} · <a href=\"{esc(d['url'], quote=True)}\">link</a>")
    if suspicious:
        blocks.append("\n⚠️ <b>Too good to be true</b> (likely parts, minifigs or mis-titled):")
        for d in suspicious[:MAX_SUSPICIOUS]:
            blocks.append(
                f"\n• {esc(d['set_no'])} {esc(d['set_name'])}: {d['price']:.0f}€ vs {d['rrp']:.0f}€ "
                f"(−{d['discount'] * 100:.0f}%) · <a href=\"{esc(d['url'], quote=True)}\">link</a>")
        if len(suspicious) > MAX_SUSPICIOUS:
            blocks.append(f"\n… and {len(suspicious) - MAX_SUSPICIOUS} more")
    foot = (f"\n<i>Scanned {stats['scanned']} new listings · {stats['matched']} matched to a set "
            f"· {stats['excluded']} excluded. Prices exclude shipping and buyer fee.</i>")
    for w in warnings:
        foot += f"\n⚠️ {esc(w)}"
    messages, cur = [], head
    for b in blocks + [foot]:
        if len(cur) + len(b) > 3800:
            messages.append(cur)
            cur = ""
        cur += b
    messages.append(cur)
    return messages


def send_telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
        data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": "true"},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text[:200]}")


# ---------------- state ----------------
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


# ---------------- main ----------------
def today_str():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Madrid")).strftime("%d/%m/%Y")
    except Exception:
        return datetime.now().strftime("%d/%m/%Y")


def main():
    dry = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    out = (lambda t: print("\n--- MESSAGE ---\n" + t)) if dry else send_telegram
    catalogue = load_catalogue()
    state = load_state()
    last_id = int(state.get("last_id", 0))
    alerted = set(state.get("alerted", []))

    by_id, error, complete, reached = {}, None, False, False
    for page in range(1, MAX_PAGES + 1):
        try:
            items = fetch_page(page)
        except FetchError as e:
            error = f"Vinted page {page}: {e}"
            break
        if not items:
            if page == 1:
                error = "Vinted page 1 returned no listings (blocked or page structure changed)"
            else:
                complete = True
            break
        for it in items:
            by_id[it["id"]] = it
        if last_id and min(it["id"] for it in items) <= last_id:
            complete = reached = True
            break
        time.sleep(random.uniform(*PAUSE))
    print(f"pages fetched: {page} | listings: {len(by_id)} | complete={complete} | error={error}")

    if error and not by_id:
        out(f"⚠️ <b>Lego bot error</b>: {html.escape(error)}")
        sys.exit(1)

    warnings = []
    if error:
        warnings.append(f"Partial scan: {error}")
    elif last_id and not reached:
        warnings.append(f"Coverage incomplete: {len(by_id)} listings fetched without reaching the previous run; "
                        "older new listings may be missed (run more often)")
    if not last_id:
        warnings.append("First run: no previous watermark, scanned the latest pages only")

    # Targeted LOTR searches: these sets are rare, so the generic "lego" scan would miss most of them
    extra = {}
    for q in LOTR_QUERIES:
        for page in range(1, LOTR_PAGES + 1):
            try:
                items = fetch_page(page, q)
            except FetchError as e:
                warnings.append(f"LOTR search '{q}' page {page}: {e}")
                break
            if not items:
                break
            for it in items:
                extra[it["id"]] = it
            time.sleep(random.uniform(*PAUSE))
    print(f"LOTR search listings: {len(extra)}")

    new_items = [it for it in by_id.values() if it["id"] > last_id and it["id"] not in alerted]
    deals, suspicious, lotr, sw_figs, stats = evaluate(new_items, catalogue)
    seen = {d["id"] for d in lotr}
    fresh = [it for it in extra.values() if it["id"] not in alerted and it["id"] not in seen]
    lotr += evaluate(fresh, catalogue)[2]
    lotr.sort(key=lambda d: (d["discount"] is None, -(d["discount"] or 0)))
    for m in build_messages(deals, suspicious, lotr, sw_figs, stats, warnings, today_str()):
        out(m)

    if not dry:
        if not error and by_id:
            state["last_id"] = max(by_id)
        state["alerted"] = (list(alerted) + [d["id"] for d in deals + suspicious + lotr + sw_figs])[-1000:]
        save_state(state)


if __name__ == "__main__":
    main()
