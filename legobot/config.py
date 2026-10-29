"""Settings from config.toml, exposed as module constants.

The file is found at $LEGOBOT_CONFIG or, by default, config.toml at the repository root.
Runtime data (state.json, wanted.json) lives in $DATA_DIR (default: data/), which the daily
workflow checks out from the `data` branch, so that personal data never lands on the code branch."""
import os
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.environ.get("LEGOBOT_CONFIG") or os.path.join(ROOT, "config.toml")
DATA_DIR = os.environ.get("DATA_DIR") or "data"

with open(CONFIG_FILE, "rb") as _f:
    _c = tomllib.load(_f)


def _hhmm(s):
    h, m = s.split(":")
    return int(h), int(m)


# Vinted
BASE = _c["vinted"]["domain"].rstrip("/")
QUERY = _c["vinted"]["query"]
ACCEPT_LANGUAGE = _c["vinted"]["accept_language"]
MAX_PAGES = _c["vinted"]["max_pages"]
PAUSE = tuple(_c["vinted"]["pause_seconds"])
IMPERSONATE = list(_c["vinted"]["impersonate"])
NEW_PREFIX = _c["vinted"]["new_prefix"].lower()
COND_SHORT = {k.lower(): v for k, v in _c["vinted"].get("conditions", {}).items()}

# Deals
MIN_DISCOUNT_NEW = _c["deals"]["min_discount_new"]
MIN_DISCOUNT_USED = _c["deals"]["min_discount_used"]
TOO_GOOD = _c["deals"]["suspicious_above"]
MAX_SUSPICIOUS = _c["deals"]["max_suspicious"]
MAX_ITEMS = _c["deals"]["max_items"]

# Catalogue
CATALOGUE = _c["catalogue"]["file"]
THEMES = list(_c["catalogue"]["themes"])
PRICE_REGIONS = list(_c["catalogue"]["price_regions"])
EXCLUDE_SUBTHEMES = [s.lower() for s in _c["catalogue"].get("exclude_subthemes", [])]

# Filters
EXTRA_EXCLUDE_WORDS = list(_c.get("filters", {}).get("extra_exclude", []))

# Special blocks
LOTR_QUERIES = list(_c["lotr"]["queries"])
LOTR_PAGES = _c["lotr"]["pages"]
MAX_SW_FIGURES = _c["star_wars"]["max_figures"]
IDEAS_EXPERIMENT = bool(_c["ideas"]["enabled"])
IDEAS_THEME = _c["ideas"]["theme"]
IDEAS_QUERIES = list(_c["ideas"]["queries"])
IDEAS_PAGES = _c["ideas"]["pages"]
WANTED_PAGES = _c["wanted"]["pages"]

# Schedule and state
TIMEZONE = _c["schedule"]["timezone"]
SLOTS = [(name, _hhmm(start)) for name, start in _c["schedule"]["slots"]]
ALERTED_CAP = _c["state"]["alerted_cap"]
STATE_FILE = os.path.join(DATA_DIR, "state.json")
WANTED_FILE = os.path.join(DATA_DIR, "wanted.json")
