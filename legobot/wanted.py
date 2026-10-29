"""Wanted list: sets to report on every new Vinted listing, with no discount filter.

The list lives in wanted.json and can be changed three ways:
  1. Telegram (from the bot's chat; applied at the next run, reply included in that run's digest):
       /want 21257 160 Tintin     add (price and name optional when the set is in sets.csv)
       /unwant 21257              remove
       /wanted                    show the list
  2. Command line:  python wanted.py add 21257 --rrp 160 --name "Tintin" [--year 2026] [--keyword tintin]
                    python wanted.py remove 21257
                    python wanted.py list
  3. Editing wanted.json directly on GitHub.
"""
import argparse
import json
import os
import re

from .config import WANTED_FILE

NUM = re.compile(r"(?<![\d.,])(\d{4,6})(?:-\d{1,2})?(?!\d)")
SET_NO = re.compile(r"^\d{4,6}$")


# ---------------- storage ----------------
def load(path=WANTED_FILE):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    for w in data:
        w["number"] = str(w["number"])
    return data


def save(entries, path=WANTED_FILE):
    entries = sorted(entries, key=lambda w: w["number"])
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[\n" + ",\n".join("  " + json.dumps(w, ensure_ascii=False) for w in entries) + "\n]\n")


def parse_price(s):
    try:
        return round(float(s.replace("€", "").replace(",", ".")), 2)
    except (AttributeError, ValueError):
        return None


def add(entries, number, name=None, rrp=None, year=None, keywords=None, catalogue=None):
    """Add or update a set. Missing name/price/year are taken from the catalogue when it has the set.
    Returns (entries, message)."""
    number = str(number).strip()
    if not SET_NO.match(number):
        return entries, f"'{number}' is not a set number (4-6 digits)"
    c = (catalogue or {}).get(number) or {}
    old = next((w for w in entries if w["number"] == number), None)
    entry = {
        "number": number,
        "name": name or (old or {}).get("name") or c.get("name") or f"Set {number}",
        "year": year if year is not None else (old or {}).get("year") or c.get("year"),
        "rrp": rrp if rrp is not None else (old or {}).get("rrp") or c.get("rrp"),
    }
    kw = keywords if keywords is not None else (old or {}).get("keywords")
    if kw:
        entry["keywords"] = [k.lower() for k in kw]
    entries = [w for w in entries if w["number"] != number] + [entry]
    price = f"{entry['rrp']:.2f}€" if entry["rrp"] else "no RRP"
    return entries, f"{'Updated' if old else 'Added'} {number} {entry['name']} ({price})"


def remove(entries, number):
    number = str(number).strip()
    kept = [w for w in entries if w["number"] != number]
    if len(kept) == len(entries):
        return entries, f"{number} is not in the wanted list"
    gone = next(w for w in entries if w["number"] == number)
    return kept, f"Removed {number} {gone['name']}"


def describe(entries):
    if not entries:
        return "Wanted list is empty"
    return "Wanted list:\n" + "\n".join(
        f"• {w['number']} {w['name']}" + (f" · {w['rrp']:.2f}€" if w.get("rrp") else "") for w in entries)


# ---------------- matching ----------------
def search_queries(entries):
    """Vinted searches for the wanted sets: one per set number, plus one per keyword set."""
    qs = []
    for w in entries:
        qs.append(f"lego {w['number']}")
        if w.get("keywords"):
            qs.append("lego " + " ".join(w["keywords"]))
    return list(dict.fromkeys(qs))


def match(title, entries):
    """Wanted entry the title refers to, or None. A set number in the title wins; otherwise every
    keyword of an entry plus the word 'lego' must appear (avoids comics, films, etc.)."""
    by_no = {w["number"]: w for w in entries}
    for m in NUM.finditer(title):
        if m.group(1) in by_no:
            return by_no[m.group(1)]
    t = title.lower()
    if "lego" in t:
        for w in entries:
            kw = w.get("keywords")
            if kw and all(re.search(r"\b" + re.escape(k) + r"\b", t) for k in kw):
                return w
    return None


# ---------------- Telegram commands ----------------
CMD = re.compile(r"^/(want|unwant|wanted)(?:@\w+)?\b\s*(.*)$", re.I | re.S)


def apply_command(entries, text, catalogue=None):
    """Apply one chat message. Returns (entries, reply) or (entries, None) when it is not a command."""
    m = CMD.match((text or "").strip())
    if not m:
        return entries, None
    cmd, args = m.group(1).lower(), m.group(2).split()
    if cmd == "wanted":
        return entries, describe(entries)
    if not args:
        return entries, f"Usage: /{cmd} <set number>" + (" [price] [name]" if cmd == "want" else "")
    if cmd == "unwant":
        return remove(entries, args[0])
    rest = args[1:]
    rrp = parse_price(rest[0]) if rest else None
    if rrp is not None:
        rest = rest[1:]
    return add(entries, args[0], name=" ".join(rest) or None, rrp=rrp, catalogue=catalogue)


def fetch_commands(token, chat_id, offset, get):
    """Messages sent to the bot since `offset`, from the configured chat only.
    `get` is requests.get (injected for tests). Returns (texts, next_offset)."""
    r = get(f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": offset, "timeout": 0, "allowed_updates": json.dumps(["message"])}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram getUpdates {r.status_code}: {r.text[:200]}")
    texts, nxt = [], offset
    for u in r.json().get("result", []):
        nxt = max(nxt or 0, u["update_id"] + 1)
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) == str(chat_id) and msg.get("text"):
            texts.append(msg["text"])
    return texts, nxt


# ---------------- CLI ----------------
def main():
    p = argparse.ArgumentParser(description="Manage the Vinted wanted list (wanted.json)")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("number")
    a.add_argument("--name")
    a.add_argument("--rrp")
    a.add_argument("--year", type=int)
    a.add_argument("--keyword", action="append", help="title words that identify the set without its number")
    r = sub.add_parser("remove")
    r.add_argument("number")
    sub.add_parser("list")
    args = p.parse_args()
    entries = load()
    if args.cmd == "list":
        print(describe(entries))
        return
    if args.cmd == "remove":
        entries, msg = remove(entries, args.number)
    else:
        try:
            from daily_deals import load_catalogue
            cat = load_catalogue()
        except Exception:
            cat = {}
        entries, msg = add(entries, args.number, args.name, parse_price(args.rrp), args.year, args.keyword, cat)
    save(entries)
    print(msg)


if __name__ == "__main__":
    main()
