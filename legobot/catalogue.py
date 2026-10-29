"""Official set catalogue (sets.csv, built from Brickset by build_catalogue.py) and set identification
from listing titles: by set number, by several numbers (lots), or by name as a fallback."""
import csv
import re

from .config import CATALOGUE
from .name_match import NameIndex, load_aliases

NUM_RE = re.compile(
    r"(?<![\d.,])(\d{4,6})(?:-\d{1,2})?(?!\d)"
    r"(?!\s*(?:€|eur|pcs|pzs|pz|piezas|pieces|pièces|teile))",
    re.I,
)


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
                "year": int(row["year"]) if (row.get("year") or "").isdigit() else None,
                "retired": row["retired"] == "yes",
                "approx": (row.get("rrp_approx") or "") == "yes",
                "promo": (row.get("promo") or "") == "yes",
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
    # lot: approximate if any part is; promo only if every part is
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
        "approx": any(c.get("approx") for c in cs),
        "promo": all(c.get("promo") for c in cs),
        "subtheme": " / ".join(dict.fromkeys(c["subtheme"] for c in cs if c["subtheme"])),
        "lot": True,
    }


_name_index = {}


def name_index(catalogue):
    key = id(catalogue)
    if key not in _name_index:
        _name_index[key] = NameIndex(catalogue, load_aliases())
    return _name_index[key]
