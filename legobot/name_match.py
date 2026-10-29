"""Fallback set identification by name, for titles without a valid set number.

Deliberately conservative: a wrong match turns into a wrong discount, so a title is matched only when
- every word of one set name (catalogue English name or an alias from aliases.json) is in the title,
- and exactly one set remains after dropping names contained in a longer matched name
  (title "millennium falcon microfighter": the microfighter wins over plain "millennium falcon"),
- and that name is not shared by several sets (e.g. "Police Station" exists in many years).
Loose figures are never name-matched (caller's responsibility)."""
import json
import re
import unicodedata
from collections import defaultdict

STOPWORDS = set("""
lego set sets new nuevo nueva nuevos neuf neuve nuovo nuova neu novo complete completo completa complet
sealed precintado scelle misb nib box caja boite
the of a an and with for in on to from
el la los las de del en y con para un una
le les du des d l et un une au aux avec pour
il lo gli i di della dello dei e con per
der die das den dem von und mit fur
""".split())
SKIP_SUBTHEMES = {"magazine gift", "promotional", "product collection", "book parts"}
MIN_SINGLE_TOKEN = 5  # one-word names shorter than this ("Boat", "Jail") are too generic


def normalise(text):
    t = unicodedata.normalize("NFKD", (text or "").lower()).encode("ascii", "ignore").decode()
    return [w for w in re.sub(r"[^a-z0-9]+", " ", t).split() if w not in STOPWORDS]


def _tok(word):
    return word[:-1] if len(word) > 4 and word.endswith("s") else word  # light plural folding


class NameIndex:
    def __init__(self, catalogue, aliases=None):
        names = defaultdict(set)  # tuple of tokens -> set numbers
        for num, c in catalogue.items():
            if not num.isdigit() or (c.get("subtheme") or "").lower() in SKIP_SUBTHEMES:
                continue
            name = c["name"]
            # "The Lord of the Rings: Rivendell" -> "Rivendell" (prefix repeats the theme)
            if ":" in name:
                prefix, rest = name.split(":", 1)
                if prefix.strip().lower() in ((c.get("theme") or "").lower(), (c.get("subtheme") or "").lower()):
                    name = rest
            self._add(names, name, num)
        for num, alist in (aliases or {}).items():
            if num in catalogue:
                for a in alist:
                    self._add(names, a, num)
        self.names = {k: v for k, v in names.items() if len(k) > 1 or len(k[0]) >= MIN_SINGLE_TOKEN}
        self.by_token = defaultdict(list)
        for k in self.names:
            self.by_token[k[0]].append(k)

    @staticmethod
    def _add(names, text, num):
        toks = tuple(sorted({_tok(w) for w in normalise(text)}))
        if toks:
            names[toks].add(num)

    def match(self, title):
        """Set number, or None when no single unambiguous set name is in the title."""
        words = {_tok(w) for w in normalise(title)}
        hits = [k for w in words for k in self.by_token.get(w, ()) if set(k) <= words]
        if not hits:
            return None
        # drop names fully contained in another matched name (keep the most specific)
        hits = [k for k in set(hits) if not any(set(k) < set(o) for o in hits)]
        nums = set().union(*(self.names[k] for k in hits))
        return next(iter(nums)) if len(nums) == 1 else None


def load_aliases(path="aliases.json"):
    try:
        with open(path, encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except FileNotFoundError:
        return {}
