"""Daily Lego deals digest.
Vinted (newest 'lego' listings) -> set number from title -> sets.csv official
price -> discount filter -> Telegram message.
Env: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, RUN_MODE (dry-run | live | scheduled), DRY_RUN (true = print only).
Requires: pip install curl_cffi requests"""
import csv
import html
import json
import os
import random
import re
import sys
import time
from collections import Counter
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
    r"|compatibles?|compat[ií]vel|compatibili?e?|kompatibel|botanicals?|brick ?-?heads?|brickz?headz|(?:4063[0-2]){1,3}"  # BrickHeadz LOTR (40630-40632)
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
ALERTED_CAP = 5000        # listing IDs remembered as already reported (older ones may be re-sent)

# Unidentified LOTR listings that are not LEGO sets (video games, puzzles, keychains, knock-off bricks)
LOTR_JUNK = re.compile(
    r"\b(ps[345]|ps ?vita|psp|xbox|playstation|nintendo|wii|3ds|2ds|ds|pc|jeu|juego|jogo|jogos|videojuego|game|puzzle|dimensions"
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
            found = parse_items(r.text)
            print(f"  fetched '{query}' page {page}: {len(found)} listings", flush=True)
            return found
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
                "subtheme": row.get("subtheme") or "",
                "retired": row["retired"] == "yes",
            }
    return cat


def find_sets(title, catalogue):
    """All distinct catalogue set numbers in the title, in order of appearance."""
    found = []
    for m in NUM_RE.finditer(title):
        n = m.group(1)
        if len(n) == 4 and 1990 <= int(n) <= 2030:  # looks like a year
            continue
        if n in catalogue and n not in found:
            found.append(n)
    return found


def combine(nums, catalogue):
    """One entry for a title with one or several sets. For a lot the price reference is the sum
    of the official prices, but only when every set in the lot has one."""
    cs = [catalogue[n] for n in nums]
    if len(cs) == 1:
        return nums[0], {**cs[0], "lot": False, "known_rrp": cs[0]["rrp"], "known_nums": nums[:]}
    rrps = [c["rrp"] for c in cs]
    known = [(n, c["rrp"]) for n, c in zip(nums, cs) if c["rrp"]]
    themes = list(dict.fromkeys(c["theme"] for c in cs))
    return " + ".join(nums), {
        "name": " + ".join(dict.fromkeys(c["name"] for c in cs)),
        "theme": " / ".join(themes),
        "rrp": sum(rrps) if all(rrps) else None,
        "known_rrp": sum(r for _, r in known) if known else None,
        "known_nums": [n for n, _ in known],
        "retired": all(c["retired"] for c in cs),
        "subtheme": " / ".join(dict.fromkeys(c["subtheme"] for c in cs if c["subtheme"])),
        "lot": True,
    }


def new_stats(n):
    """Counters for one batch. Invariant: scanned == sum(excluded) + matched + unidentified."""
    return {"scanned": n, "excluded": Counter(), "matched": 0, "unidentified": 0, "no_price": 0}


def check_stats(stats, label):
    total = sum(stats["excluded"].values()) + stats["matched"] + stats["unidentified"]
    if total != stats["scanned"]:
        print(f"WARNING counters ({label}): scanned={stats['scanned']} but "
              f"excluded+matched+unidentified={total}", flush=True)


def evaluate(items, catalogue):
    deals, lotr, sw_figs = [], [], []
    stats = new_stats(len(items))
    for it in items:
        t = it["title"]
        if EXCLUDE.search(t) or EXTRA_EXCLUDE.search(t):
            stats["excluded"]["keywords"] += 1
            continue
        nums = find_sets(t, catalogue)
        if nums:
            kept = [n for n in nums if "botanical" not in catalogue[n]["subtheme"].lower()]
            if not kept:  # only Botanical Collection sets in the title
                stats["excluded"]["botanical"] += 1
                continue
            nums = kept
        num, c = combine(nums, catalogue) if nums else (None, None)
        is_lotr = bool((c and LOTR_THEME.search(f"{c['theme']} {c['subtheme']}")) or (not c and LOTR_NAME.search(t)))
        is_sw = bool((c and "Star Wars" in c["theme"]) or (not c and SW_NAME.search(t)))
        if not (is_lotr or is_sw) and FIG_EXCL.search(t):
            stats["excluded"]["figure"] += 1
            continue
        if is_lotr and not c and LOTR_JUNK.search(t):
            stats["excluded"]["not Lego"] += 1
            continue
        is_fig = bool((is_lotr or is_sw) and FIG_RE.search(t))
        if is_lotr:
            rrp = c["rrp"] if c else None
            disc = (1 - it["price"] / rrp) if rrp and it["price"] else None
            lotr.append({**it, "set_no": num or "?", "set_name": c["name"] if c else "set not identified",
                         "rrp": rrp, "retired": bool(c and c["retired"]), "discount": disc, "figure": is_fig,
                         "lot": bool(c and c["lot"]),
                         "known_rrp": c["known_rrp"] if c else None,
                         "known_nums": c["known_nums"] if c else []})
            stats["matched" if c else "unidentified"] += 1
            continue
        if not c:
            stats["unidentified"] += 1
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
                          "rrp": c["rrp"], "retired": c["retired"], "discount": discount, "lot": c["lot"]})
    deals.sort(key=lambda d: d["discount"], reverse=True)
    lotr.sort(key=lambda d: (d["discount"] is None, -(d["discount"] or 0)))
    suspicious = [d for d in deals if d["discount"] >= TOO_GOOD]
    deals = [d for d in deals if d["discount"] < TOO_GOOD]
    sw_figs.sort(key=lambda d: d["id"], reverse=True)
    return deals, suspicious, lotr, sw_figs, stats


# ---------------- message / telegram ----------------
def fmt_pct(discount):
    """Price change vs official price, one format everywhere: '-62%', '+7%'. ASCII minus only."""
    change = -discount * 100
    return f"{'+' if change > 0 else '-' if change < 0 else ''}{abs(change):.0f}%"


COND_SHORT = {"nuevo con etiquetas": "new, tags", "nuevo sin etiquetas": "new",
              "muy bueno": "very good", "bueno": "good", "satisfactorio": "fair"}


def cond_short(cond):
    return COND_SHORT.get((cond or "").strip().lower(), cond or "?")


def short_title(t, n=45):
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def set_label(d):
    name = re.sub(r"^The Lord of the Rings:\s*", "", d["set_name"])
    return f"{d['set_no']} {name}"


def lotr_blocks(lotr):
    """Lord of the Rings, every listing, grouped: complete sets by set, then unidentified, then figures."""
    esc = html.escape
    link = lambda d, text: f"<a href=\"{esc(d['url'], quote=True)}\">{esc(text)}</a>"
    price = lambda d: f"{d['price']:.0f}€" if d["price"] else "?€"
    sets = [d for d in lotr if d["set_no"] != "?" and not d["figure"]]
    unid = [d for d in lotr if d["set_no"] == "?" and not d["figure"]]
    figs = [d for d in lotr if d["figure"]]
    blocks = []
    groups = {}
    for d in sets:
        groups.setdefault(d["set_no"], []).append(d)
    def best(g):
        ds = [x["discount"] for x in g if x["discount"] is not None]
        return (not ds, -(max(ds) if ds else 0), g[0]["set_no"])
    if groups:
        blocks.append("\n\n🧙 <b>Lord of the Rings sets</b>")
    for g in sorted(groups.values(), key=best):
        g.sort(key=lambda x: x["price"] or 0)
        d0 = g[0]
        if d0["rrp"]:
            ref = f"RRP {d0['rrp']:.0f}€"
        elif d0.get("lot") and d0.get("known_rrp"):
            ref = f"RRP known only for {' + '.join(d0['known_nums'])}: {d0['known_rrp']:.0f}€"
        else:
            ref = "no RRP"
        flags = (" 🏷️" if d0["retired"] else "") + (" 📦 lot" if d0.get("lot") else "")
        entries = " · ".join(
            link(x, price(x)) + (f" {fmt_pct(x['discount'])}" if x["discount"] is not None else "")
            + f" {cond_short(x['condition'])}" for x in g)
        blocks.append(f"\n<b>{esc(set_label(d0))}</b> · {ref}{flags}\n   {entries}")
    if unid:
        unid.sort(key=lambda x: x["price"] or 0)
        blocks.append(f"\n\n❓ <b>LotR, set not identified</b> ({len(unid)})")
        blocks += [f"\n• {link(x, short_title(x['title']))} {price(x)} {cond_short(x['condition'])}" for x in unid]
    if figs:
        figs.sort(key=lambda x: x["price"] or 0)
        blocks.append(f"\n\n🧍 <b>LotR figures</b> ({len(figs)}, no discount shown)")
        blocks += [f"\n• {link(x, short_title(x['title']))} {price(x)} {cond_short(x['condition'])}"
                   + (f" · {esc(x['set_no'])}" if x["set_no"] != "?" else "") for x in figs]
    return blocks


def fmt_excluded(c):
    if not c:
        return "0 excluded"
    return f"{sum(c.values())} excluded (" + ", ".join(f"{k} {v}" for k, v in c.most_common()) + ")"


def build_messages(deals, suspicious, lotr, sw_figs, stats, lotr_info, warnings, today):
    esc = html.escape
    head = f"🧱 <b>Lego deals {today}</b>: {len(deals)} found" + (
        f" · {len(lotr)} new Lord of the Rings" if lotr else "") + (
        f" · {len(sw_figs)} Star Wars figures" if sw_figs else "")
    blocks = []
    for i, d in enumerate(deals[:MAX_ITEMS], 1):
        flags = (" 🏷️ retired" if d["retired"] else "") + (" 📦 lot" if d.get("lot") else "")
        blocks.append(
            f"\n{i}. <b>{esc(d['set_no'])} {esc(d['set_name'])}</b>\n"
            f"{d['price']:.0f}€ vs {d['rrp']:.0f}€ ({fmt_pct(d['discount'])}) · "
            f"{esc(d['condition'])} · {esc(d['theme'])}{flags}\n"
            f"<a href=\"{esc(d['url'], quote=True)}\">Open on Vinted</a>"
        )
    if len(deals) > MAX_ITEMS:
        blocks.append(f"\n… and {len(deals) - MAX_ITEMS} more")
    if sw_figs:
        blocks.append("\n\n🧍 <b>Star Wars loose figures</b> (set number found in title; no discount filter, newest first):")
        for d in sw_figs[:MAX_SW_FIGURES]:
            blocks.append(
                f"\n• <b>{esc(d['set_no'])} {esc(d['set_name'])}</b>: {d['price']:.0f}€ · {esc(d['condition'])} · "
                f"<a href=\"{esc(d['url'], quote=True)}\">link</a>")
        if len(sw_figs) > MAX_SW_FIGURES:
            blocks.append(f"\n… and {len(sw_figs) - MAX_SW_FIGURES} more")
    blocks += lotr_blocks(lotr)
    if suspicious:
        blocks.append("\n\n⚠️ <b>Too good to be true</b> (likely parts, minifigs or mis-titled):")
        for d in suspicious[:MAX_SUSPICIOUS]:
            blocks.append(
                f"\n• {esc(d['set_no'])} {esc(d['set_name'])}: {d['price']:.0f}€ vs {d['rrp']:.0f}€ "
                f"({fmt_pct(d['discount'])}) · <a href=\"{esc(d['url'], quote=True)}\">link</a>")
        if len(suspicious) > MAX_SUSPICIOUS:
            blocks.append(f"\n… and {len(suspicious) - MAX_SUSPICIOUS} more")
    n_figs = sum(1 for d in lotr if d["figure"])
    n_unid = sum(1 for d in lotr if d["set_no"] == "?" and not d["figure"])
    foot = (f"\n\n<i>Vinted: {stats['scanned']} new listings · {stats['matched']} matched · "
            f"{stats['unidentified']} unidentified · {esc(fmt_excluded(stats['excluded']))} · "
            f"{len(deals) + len(suspicious)} at ≥{MIN_DISCOUNT_NEW * 100:.0f}% off\n"
            f"LotR: {len(lotr)} new ({len(lotr) - n_figs - n_unid} sets, {n_figs} figures, {n_unid} unidentified)"
            f" · {lotr_info['already']} already reported, still listed"
            f"\nPrices exclude shipping and buyer fee.</i>")
    for w in warnings:
        foot += f"\n⚠️ {esc(w)}"
    # Telegram's 4096 limit counts the text after HTML parsing, so link URLs do not count
    messages, cur = [], head
    for b in blocks + [foot]:
        if visible_len(cur) + visible_len(b) > 3800:
            messages.append(cur)
            cur = b.lstrip("\n")
            continue
        cur += b
    messages.append(cur)
    return messages


def visible_len(s):
    return len(html.unescape(re.sub(r"<[^>]+>", "", s)))


def send_telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
        data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": "true"},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text[:200]}")


def send_safe(text):
    """Send; if Telegram rejects the length, split on line boundaries by raw size and retry."""
    try:
        send_telegram(text)
    except RuntimeError as e:
        if "too long" not in str(e).lower():
            raise
        print("Message too long for Telegram, re-splitting by raw length", flush=True)
        cur = ""
        for line in text.split("\n"):
            if cur and len(cur) + len(line) + 1 > 3800:
                send_telegram(cur)
                cur = ""
            cur += ("\n" if cur else "") + line
        if cur:
            send_telegram(cur)


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
SLOTS = {"am": (9, 30), "pm": (14, 0)}  # Madrid local times of the two daily runs


def schedule_slot(state):
    """Scheduled runs only. GitHub cron is UTC-only, so several UTC crons fire and this guard keeps
    exactly one run per Madrid-time slot (09:30 / 14:00), whatever the daylight-saving offset.
    Returns the slot id to run, or None to skip."""
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Europe/Madrid"))
    name = "am" if now.hour < 12 else "pm"
    slot = f"{now:%Y-%m-%d}-{name}"
    if (now.hour, now.minute) < SLOTS[name] or state.get("last_slot") == slot:
        print(f"Skipping: Madrid time {now:%H:%M}, slot {slot} not due or already done")
        return None
    return slot

def today_str():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Madrid")).strftime("%d/%m/%Y")
    except Exception:
        return datetime.now().strftime("%d/%m/%Y")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)  # show progress live in the Actions log
    mode = os.environ.get("RUN_MODE", "").strip().lower()  # set by the GitHub workflow
    dry = mode == "dry-run" or os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    out = (lambda t: print("\n--- MESSAGE ---\n" + t)) if dry else send_safe
    catalogue = load_catalogue()
    state = load_state()
    slot = None
    # The Madrid-time slot guard applies to GitHub cron runs and to the external scheduler ("scheduled")
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" or mode == "scheduled":
        slot = schedule_slot(state)
        if slot is None:
            return
    last_id = int(state.get("last_id", 0))
    alerted_order = list(dict.fromkeys(state.get("alerted", [])))  # oldest first
    alerted = set(alerted_order)

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
    _, _, lotr_extra, _, lotr_stats = evaluate(fresh, catalogue)
    lotr += lotr_extra
    lotr.sort(key=lambda d: (d["discount"] is None, -(d["discount"] or 0)))
    check_stats(stats, "main scan")
    check_stats(lotr_stats, "LotR searches")
    lotr_info = {"active": len(extra), "already": sum(1 for i in extra if i in alerted)}
    print(f"LotR: {len(lotr)} new, {lotr_info['already']} already reported | main stats {stats} | "
          f"LotR search stats {lotr_stats}")
    for m in build_messages(deals, suspicious, lotr, sw_figs, stats, lotr_info, warnings, today_str()):
        out(m)

    if not dry:
        if not error and by_id:
            state["last_id"] = max(by_id)
        if slot and not error:
            state["last_slot"] = slot
        sent = [d["id"] for d in deals + suspicious + lotr + sw_figs]
        # Ordered list, oldest first, so the cap evicts the oldest IDs (a set lost the order)
        state["alerted"] = list(dict.fromkeys(alerted_order + sent))[-ALERTED_CAP:]
        save_state(state)


if __name__ == "__main__":
    main()
