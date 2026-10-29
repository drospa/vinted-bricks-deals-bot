"""Listing classification: quality exclusions (knock-offs, accessories, incomplete sets, loose figures),
set identification, discount test, and routing into the digest blocks (deals, suspicious, Lord of the
Rings, Star Wars figures, Ideas, wanted list)."""
import re
from collections import Counter

from . import wanted as wl
from .catalogue import combine, find_sets, name_index
from .config import (EXCLUDE_SUBTHEMES, EXTRA_EXCLUDE_WORDS, IDEAS_THEME, MIN_DISCOUNT_NEW,
                     MIN_DISCOUNT_USED, NEW_PREFIX, TOO_GOOD)

EXCLUDE = re.compile(
    r"\b(compatible|compatibles|kompatibel|compatibile|moc|custom|clone|clon"
    r"|incompleto|incompleta|incomplete|incomplet|unvollst\w+"
    r"|lote|lot de|bundle"
    r"|caja vac\w+|empty box|bo[iî]te vide|leere? (box|schachtel|verpackung)"
    r"|solo (la )?caja|only (the )?box|box only|seule bo[iî]te"
    r"|(solo|only|nur|seulement|uniquement) (las? |le )?(instrucciones|instructions|manual|notice|anleitung|istruzioni)"
    r"|(instrucciones|instructions|manual|notice|anleitung|istruzioni) (only|seul\w*|solo|solamente|uniquement)"
    r"|caixa vazia|s[oó] (a )?caixa"
    r"|pi[eè]ces d[ée]tach[ée]es|piezas sueltas|pour pi[eè]ces|for parts|spare parts|repuestos?)\b",
    re.I,
)

# Extra exclusions (all themes): knock-offs, BrickHeadz LOTR, numbered instruction booklets
EXTRA_EXCLUDE = re.compile(
    r"\b(type lego|tipo lego|estilo lego|style lego|no ?lego|not lego|r[ée]plique|r[ée]plica|replica"
    r"|lepin|mould ?king|xingbao|compatibles?|compat[ií]vel|compatibili?e?|kompatibel|botanicals?|brick ?-?heads?|brickz?headz|(?:4063[0-2]){1,3}"  # BrickHeadz LOTR (40630-40632)
    r"|(istruzioni|instrucciones|instructions|anleitung|notice|manual)\s*(n[°º.]?\s*)?\d+)\b", re.I)
# Words added by the user in config.toml [filters] extra_exclude (None when the list is empty)
USER_EXCLUDE = re.compile(r"\b(?:" + "|".join(EXTRA_EXCLUDE_WORDS) + r")\b", re.I) if EXTRA_EXCLUDE_WORDS else None
# Loose figures: excluded for every theme EXCEPT Star Wars and Lord of the Rings
_FROM_SET = r"(from|out of|del|du|dal|aus dem)\s+(the\s+|el\s+|le\s+|il\s+)?(set|lot)"
FIG_EXCL = re.compile(
    r"\b(mini[ -]?fig\w*|figurines?|figurita\w*|personnages?|" + _FROM_SET + r"|(cty|twn|njo|hp|sh|col)\d{2,4})\b", re.I)
# Used to tag loose figures that are kept for Star Wars / LOTR
FIG_RE = re.compile(
    r"\b(mini[ -]?fig\w*|figurines?|figurita\w*|personnages?|figuras?|figures?|figuur|figuren|"
    + _FROM_SET + r"|(lor|sw)\d{2,4})\b", re.I)
# "sans figurine" / "sin minifiguras" / "without minifigs": the set without its figures, not a figure
NEG_FIG = re.compile(r"\b(sans|sin|without|senza|ohne|no)\s+(las?\s+|les?\s+|the\s+|le\s+)?"
                     r"(mini[ -]?fig\w*|figurines?|figuras?|figures?|personnages?)", re.I)
# "con minifiguras" / "with minifigures" / "avec figurines": describes a set that includes its figures
WITH_FIG = re.compile(r"\b(con|with|avec|mit|inclu\w*|incl)\s+(sus\s+|las\s+|les\s+|the\s+|all\s+|todas\s+las\s+|"
                      r"toutes\s+les\s+|alle\s+)?(\d+\s+)?(mini[ -]?fig\w*|figurines?|figuras?|figures?|personnages?)"
                      r"|\b(mini[ -]?fig\w*|figuras?|figurines?)\s+(incluid\w*|inclus\w*|included|incluse)", re.I)
# A title that says the set is complete is the set, not a loose figure ("minifigure set 11373 completo")
COMPLETE = re.compile(r"\b(complet[oaei]?s?|complete|compleet|komplett|completi)\b", re.I)
FIG_SET_MIN_SHARE = 0.30  # a "complete" listing priced under 30% of the official price is still treated as a figure

# Third-party accessories sold for a set (lighting kits, display cases, alternative builds): not the set itself
ACCESSORY = re.compile(
    r"\b(yeabricks|briksmax|vonado|lightailing|game ?of ?bricks|kyglaring|brickbling|lego ?lite"
    r"|kit\s+(de\s+)?(iluminaci\w+|luz|luces|led|lumi\w+|light\w*|eclairage|beleuchtung|illuminazione)"
    r"|(led|light|lighting|lumi[eè]re)\s+kit|iluminaci[oó]n\s+led|led\s+(lighting|light|lights|luces|iluminaci\w+)"
    r"|eclairage\s+led|led\s+beleuchtung|beleuchtungs\w*|illuminazione\s+led"
    r"|(vitrina|urna|vitrine|display\s+(case|box)|caja\s+expositora|acr[ií]lico|acrylic)\s+(para|for|pour|per|f[üu]r)"
    r"|support\s+mural|wall\s+mount|soporte\s+(de\s+)?pared|wandhalterung|cadre|cuadro|poster|p[oó]ster|affiche"
    r"|alternative?\s+build|alternate\s+build|alt\s+build|b[ -]model|modelo\s+alternativo)\b", re.I)
# Incomplete sets in the languages Vinted Spain shows (ES/EN/FR/DE are in EXCLUDE already)
INCOMPLETE = re.compile(
    r"\b(incompleet|onvolledig|incompleti|mancante|mancanti|mancano|niet\s+compleet"
    r"|(?<!no )(?<!no le )(?<!sin )falta(n)?\s+(algunas?\s+|unas?\s+|\d+\s+)?(piezas?|pe[cç]as?|minifig\w*|figuras?)"
    r"|(?<!no )missing\s+(pieces?|parts?|minifig\w*)|(?<!no )pieces?\s+missing|(?<!sans )pi[eè]ces?\s+manquantes?)\b", re.I)
SW_NAME = re.compile(r"\b(star ?wars|guerra de las galaxias|guerre des [eé]toiles)\b", re.I)

# Unidentified LOTR listings that are not LEGO sets (video games, puzzles, keychains, knock-off bricks)
LOTR_JUNK = re.compile(
    r"\b(ps[345]|ps ?vita|psp|xbox|playstation|nintendo|wii|3ds|2ds|ds|pc|jeu|juego|jogo|jogos|videojuego|game|puzzle|dimensions"
    r"|llavero|keychain|porte[- ]cl[eé]s?|bloques|bausteine)\b", re.I)

# Lord of the Rings: no discount filter, every finding is listed
LOTR_THEME = re.compile(r"lord of the rings", re.I)
LOTR_NAME = re.compile(
    r"\b(lord of the rings|se[ñn]or de los anillos|seigneur des anneaux"
    r"|herr der ringe|signore degli anelli|lotr)\b", re.I)


def new_stats(n):
    """Counters for one batch. Invariant: scanned == sum(excluded) + matched + unidentified."""
    return {"scanned": n, "excluded": Counter(), "matched": 0, "unidentified": 0, "no_price": 0}


def check_stats(stats, label):
    total = sum(stats["excluded"].values()) + stats["matched"] + stats["unidentified"]
    if total != stats["scanned"]:
        print(f"WARNING counters ({label}): scanned={stats['scanned']} but "
              f"excluded+matched+unidentified={total}", flush=True)


def evaluate(items, catalogue, ideas=None):
    """ideas: optional list; when given, identified Ideas listings go there with no discount filter
    instead of the deals path."""
    deals, lotr, sw_figs = [], [], []
    stats = new_stats(len(items))
    stats["by_name"] = 0
    for it in items:
        t = it["title"]
        ft = WITH_FIG.sub(" ", NEG_FIG.sub(" ", t))  # text for figure checks
        if EXCLUDE.search(t) or EXTRA_EXCLUDE.search(t) or (USER_EXCLUDE and USER_EXCLUDE.search(t)):
            stats["excluded"]["keywords"] += 1
            continue
        if ACCESSORY.search(t):
            stats["excluded"]["accessory"] += 1
            continue
        if INCOMPLETE.search(t):
            stats["excluded"]["incomplete"] += 1
            continue
        nums = find_sets(t, catalogue)
        by_name = False
        # No set number: try the set name, never for loose figures or non-Lego junk
        if not nums and not (FIG_RE.search(ft) or FIG_EXCL.search(ft) or LOTR_JUNK.search(t)):
            n = name_index(catalogue).match(t)
            if n:
                nums, by_name = [n], True
        if nums:
            kept = [n for n in nums if not any(s in catalogue[n]["subtheme"].lower() for s in EXCLUDE_SUBTHEMES)]
            if not kept:  # only Botanical Collection sets in the title
                stats["excluded"]["botanical"] += 1
                continue
            nums = kept
        num, c = combine(nums, catalogue) if nums else (None, None)
        is_lotr = bool((c and LOTR_THEME.search(f"{c['theme']} {c['subtheme']}")) or (not c and LOTR_NAME.search(t)))
        is_sw = bool((c and "Star Wars" in c["theme"]) or (not c and SW_NAME.search(t)))
        # Titles saying the set is complete describe the set even if they mention figures
        complete_set = bool(c and not by_name and COMPLETE.search(t) and (
            not c["rrp"] or (it["price"] or 0) >= FIG_SET_MIN_SHARE * c["rrp"]))
        if not (is_lotr or is_sw) and FIG_EXCL.search(ft) and not complete_set:
            stats["excluded"]["figure"] += 1
            continue
        if is_lotr and not c and LOTR_JUNK.search(t):
            stats["excluded"]["not Lego"] += 1
            continue
        is_fig = bool((is_lotr or is_sw) and FIG_RE.search(ft))
        if is_fig and complete_set:
            is_fig = False  # "minifigure set 11373 completo" at 60€ of 75€: the set
        if is_lotr:
            rrp = c["rrp"] if c else None
            disc = (1 - it["price"] / rrp) if rrp and it["price"] else None
            lotr.append({**it, "set_no": num or "?", "set_name": c["name"] if c else "set not identified",
                         "approx": bool(c and c.get("approx")), "promo": bool(c and c.get("promo")),
                         "rrp": rrp, "retired": bool(c and c["retired"]), "discount": disc, "figure": is_fig,
                         "lot": bool(c and c["lot"]),
                         "known_rrp": c["known_rrp"] if c else None,
                         "known_nums": c["known_nums"] if c else [], "by_name": by_name})
            stats["matched" if c else "unidentified"] += 1
            stats["by_name"] += by_name
            continue
        if not c:
            stats["unidentified"] += 1
            continue
        stats["matched"] += 1
        stats["by_name"] += by_name
        if ideas is not None and c["theme"] == IDEAS_THEME:  # all sets in the title are Ideas
            rrp = c["rrp"]
            disc = (1 - it["price"] / rrp) if rrp and it["price"] else None
            ideas.append({**it, "set_no": num, "set_name": c["name"], "theme": c["theme"], "rrp": rrp,
                          "approx": c.get("approx", False), "promo": c.get("promo", False),
                          "retired": c["retired"], "discount": disc, "figure": False, "lot": c["lot"],
                          "known_rrp": c["known_rrp"], "known_nums": c["known_nums"], "by_name": by_name})
            continue
        if is_fig:  # loose Star Wars figure: the set's official price says nothing about it, so no discount test
            sw_figs.append({**it, "set_no": num, "set_name": c["name"], "theme": c["theme"],
                            "rrp": c["rrp"], "retired": c["retired"], "discount": None})
            continue
        if not c["rrp"] or not it["price"] or it["price"] <= 0:
            stats["no_price"] += 1
            continue
        discount = 1 - it["price"] / c["rrp"]
        is_new = it["condition"].lower().startswith(NEW_PREFIX)
        if discount >= (MIN_DISCOUNT_NEW if is_new else MIN_DISCOUNT_USED):
            deals.append({**it, "set_no": num, "set_name": c["name"], "theme": c["theme"],
                          "rrp": c["rrp"], "retired": c["retired"], "discount": discount, "lot": c["lot"],
                          "approx": c.get("approx", False), "by_name": by_name})
    deals.sort(key=lambda d: d["discount"], reverse=True)
    lotr.sort(key=lambda d: (d["discount"] is None, -(d["discount"] or 0)))
    suspicious = [d for d in deals if d["discount"] >= TOO_GOOD]
    deals = [d for d in deals if d["discount"] < TOO_GOOD]
    sw_figs.sort(key=lambda d: d["id"], reverse=True)
    return deals, suspicious, lotr, sw_figs, stats


# Wanted list only: the set sold without its figures is not wanted (tolerates "personnnages"-style typos)
NO_FIGS = re.compile(r"\b(sans|sin|without|senza|ohne|sem|no)\s+(las?\s+|les?\s+|the\s+|os\s+|sus\s+)?"
                     r"(mini[ -]?fig\w*|figurin\w*|figuras?|figures?|personn+ages?)", re.I)


def evaluate_wanted(items, entries):
    """Every listing of a wanted set, no discount filter. Same quality exclusions as the main scan
    (knock-offs, accessories, incomplete, loose figures), so the block lists the set itself."""
    hits, excluded = [], Counter()
    for it in items:
        w = wl.match(it["title"], entries)
        if not w:
            continue
        t = it["title"]
        ft = WITH_FIG.sub(" ", NEG_FIG.sub(" ", t))
        rrp = w.get("rrp")
        if EXCLUDE.search(t) or EXTRA_EXCLUDE.search(t) or (USER_EXCLUDE and USER_EXCLUDE.search(t)):
            excluded["keywords"] += 1
            continue
        if ACCESSORY.search(t):
            excluded["accessory"] += 1
            continue
        if INCOMPLETE.search(t):
            excluded["incomplete"] += 1
            continue
        if NO_FIGS.search(t):
            excluded["no figures"] += 1
            continue
        is_fig = bool(FIG_EXCL.search(ft) or FIG_RE.search(ft))
        complete_set = bool(COMPLETE.search(t) and not re.search(r"\blot\b", t, re.I)
                            and (not rrp or (it["price"] or 0) >= FIG_SET_MIN_SHARE * rrp))
        if is_fig and not complete_set:
            excluded["figure"] += 1
            continue
        disc = (1 - it["price"] / rrp) if rrp and it["price"] else None
        hits.append({**it, "set_no": w["number"], "set_name": w["name"], "rrp": rrp, "discount": disc})
    hits.sort(key=lambda d: (d["set_no"], d["price"] or 0))
    return hits, excluded
