# Vinted LEGO Deals Bot

A Telegram bot that scans new LEGO listings on Vinted three times a day, compares each price with the
official retail price, and sends a digest of the real bargains: no knock-offs, accessories, incomplete
sets or loose figures. It runs free on GitHub Actions and needs no server.

```
🧱 Lego deals 29/10/2026: 3 found · 2 new Lord of the Rings · 🎯 1 wanted

1. 75257 Millennium Falcon
   85€ vs 169€ (-50%) · Nuevo sin etiquetas · Star Wars
   Open on Vinted

🧙 Lord of the Rings sets
10316 Rivendell · RRP 500€ 🏷️
   390€ -22% very good · 410€ -18% new

🎯 Wanted list (every new listing, no discount filter)
21367 Cohete Lunar de Tintin · RRP 160€
   • 120€ -25% new · Lego Tintin cohete lunar 21367

Vinted: 412 new listings · 230 matched · 61 unidentified · 121 excluded (keywords 70, figure 31, accessory 20) …
```
*(illustrative example)*

## Features

- **Deal detection**: the listing price is compared with the official price (RRP) from the
  [Brickset](https://brickset.com) catalogue (euro prices; older sets estimated from US/UK prices with a
  calibrated factor, marked `~`). The threshold is configurable (default ≥ 40% off). Discounts that look
  too good (default ≥ 75%) go into a separate "too good to be true" block.
- **Set identification**: by set number (including multi-set lots), or by name when the title has no
  number, with multilingual aliases (`aliases.json`). Name matching is deliberately conservative: a
  wrong match would produce a wrong discount.
- **Quality filters** in ES/EN/FR/DE/IT/NL/PT titles: knock-offs ("compatible", Lepin, Mould King…),
  third-party accessories (LED kits, display cases), incomplete sets, empty boxes, instructions only,
  loose figures. You can add your own exclusion words.
- **Theme scope**: only the Brickset themes you choose (default: Star Wars, Lord of the Rings, City,
  Icons, Ninjago, Super Mario, Ideas, BrickLink).
- **Special blocks**: Lord of the Rings and Lego Ideas are listed in full with dedicated searches;
  identified Star Wars loose figures get their own block.
- **Wanted list**: watch specific sets and get every new listing, managed from Telegram
  (`/want`, `/unwant`, `/wanted`).
- **Never twice**: each listing is reported once.
- **Reliable scheduling**: an external scheduler triggers the run, GitHub's own cron is the backup, and
  a slot guard makes sure each time slot runs exactly once.
- **Safe operation**: `dry-run` mode prints the digest without sending or saving anything; the unit
  tests run before every job.

## How it works

```
cron-job.org ──┐
GitHub cron ───┴─> daily.yml ─> tests ─> daily_deals.py
                                          │
   Telegram commands (/want…) ────────────┤  legobot/app.py
   Vinted catalogue pages (newest first) ─┤    vinted.py     fetch + parse listings
   sets.csv (Brickset RRP, monthly) ──────┤    filters.py    exclusions, identification, discount
                                          │    digest.py     message formatting
                                          └─>  telegram.py   send ─> your Telegram chat
   data branch: state.json, wanted.json <───   state.py      what was already reported
```

- **Code** lives on `main`. **Runtime data** (`state.json`: what was already reported; `wanted.json`:
  your wanted list) lives on a separate `data` branch, which the workflow checks out and updates. The
  code branch stays free of personal data and of bot commits.
- Vinted has no public API. The bot reads the catalogue page HTML with a browser-like TLS fingerprint
  (`curl_cffi`), pauses 2–5 seconds between pages and caps the pages per run.

## Set up your own

1. **Fork** this repository (the default "copy the main branch only" is what you want).
2. **Create a Telegram bot** with [@BotFather](https://t.me/BotFather) and keep the token. Send your bot
   any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
3. **Get a Brickset API key** (free) on [brickset.com](https://brickset.com) (account → API key request).
4. In your fork: **Settings → Secrets and variables → Actions**, add `TELEGRAM_TOKEN`,
   `TELEGRAM_CHAT_ID` and `BRICKSET_API_KEY`.
5. **Edit `config.toml`** (next section), then run the **build-catalogue** workflow once
   (Actions tab → build-catalogue → Run workflow) to build `sets.csv` for your themes.
6. Run **daily-deals** with mode `dry-run` and read the digest in the log. When it looks right, run it
   with `live`. The first run creates the `data` branch.
7. **Scheduling.** GitHub Actions enables the cron lines in `daily.yml` automatically, but GitHub's
   cron is UTC-only and can be delayed or skipped. For reliable timing, add an external scheduler such
   as [cron-job.org](https://cron-job.org) that calls:
   ```
   POST https://api.github.com/repos/<you>/<repo>/actions/workflows/daily.yml/dispatches
   Authorization: Bearer <fine-grained token: this repo only, Actions read/write>
   Body: {"ref": "main", "inputs": {"mode": "scheduled"}}
   ```
   Both triggers can stay on: the slot guard runs each slot once.

## Make it yours: `config.toml`

| Setting | What it does |
|---|---|
| `[vinted] domain` | Vinted site, e.g. `https://www.vinted.fr`. Also adapt `new_prefix` and `[vinted.conditions]` to that site's condition labels (`neuf`, `neu`…) and `accept_language`. |
| `[vinted] query`, `max_pages`, `pause_seconds` | Main search and how much / how politely to fetch. |
| `[deals] min_discount_new`, `min_discount_used` | Minimum discount vs RRP to report (0.40 = 40%). |
| `[deals] suspicious_above`, `max_items`, `max_suspicious` | "Too good to be true" threshold and digest length. |
| `[catalogue] themes` | Brickset themes to follow. Re-run build-catalogue after changing. |
| `[catalogue] price_regions` | Brickset regions for euro RRP, first with a price wins. |
| `[catalogue] exclude_subthemes` | Subthemes to ignore (default: Botanical Collection). |
| `[filters] extra_exclude` | Your own exclusion words or regular expressions, e.g. `["duplo", "polybag"]`. |
| `[lotr]`, `[ideas]`, `[star_wars]` | Dedicated searches and blocks; `[ideas] enabled = false` turns that block off. |
| `[wanted] pages` | Pages fetched per wanted-list search. |
| `[schedule] timezone`, `slots` | Local run times. Keep the cron lines in `daily.yml` consistent. |

Other tuning points:
- **Set names in other languages**: add them to `aliases.json` (`"10316": ["Rivendell", "Rivendel"]`).
- **Filter rules** (knock-off words, accessory brands, figure detection) are the regular expressions at
  the top of `legobot/filters.py`, with comments. `tests/test_quality.py` shows real titles each rule
  must keep or drop: add your cases there.
- **Lord of the Rings / Star Wars behaviour** (no discount filter, figure blocks) is in
  `legobot/filters.py`: to treat them like any other theme, empty the `[lotr] queries` list and adjust
  `evaluate()`.

## Wanted list

From the bot's Telegram chat (applied at the next run, the reply appears in that digest):

```
/want 21367 160 Tintin   add or update (price and name optional if the set is in sets.csv)
/unwant 21367            remove
/wanted                  show the list
```

Or edit `wanted.json` on the `data` branch on GitHub. Every new listing of a watched set is reported,
with no discount filter (knock-offs, accessories, incomplete sets and sets sold without figures are
still excluded).

## Run locally

```bash
pip install -r requirements.txt
python -m unittest discover -s tests          # 36 tests
DRY_RUN=1 python daily_deals.py               # prints the digest; state goes to ./data/
python wanted.py add 21367 --rrp 160 --name "Tintin" --keyword tintin
```

## Project structure

```
config.toml          settings
daily_deals.py       entry point of the daily run
build_catalogue.py   builds sets.csv from the Brickset API (monthly workflow)
wanted.py            wanted-list command line
legobot/             app, vinted, catalogue, filters, digest, telegram, state, schedule, wanted, name_match
aliases.json         extra set names for name matching
sets.csv             catalogue for the configured themes (generated)
tests/               unit tests, many built from real listing titles
```

## How this was built

This is a personal project developed with an AI pair programmer (Claude, by Anthropic). I set the goal,
the requirements and the decisions; the AI wrote most of the code; every change went through a pull
request with tests and a dry run before reaching the live bot. Some decisions along the way:

- **Feasibility first.** Probe scripts ran from GitHub Actions before any feature work. Wallapop returned
  HTTP 403 even with browser TLS impersonation, so it was parked; Vinted worked by parsing the catalogue
  HTML, so the bot was built around it.
- **Precision over recall.** A wrong set match means a wrong discount and a false alert, so
  identification is conservative and every false positive seen in a digest became a test case.
- **Operational reliability.** GitHub's cron proved unreliable, so an external scheduler became the
  primary trigger, with an idempotent slot guard so double triggers are harmless.
- **Refactor safely.** The move from one script to a package was verified by comparing the classifier
  and digest output on a 4,000-listing synthetic corpus, and a full simulated run, byte for byte before
  and after.

## Disclaimer

Unofficial personal project, for personal and educational use. Not affiliated with, endorsed or
sponsored by Vinted or the LEGO Group. LEGO is a trademark of the LEGO Group. Automated access may be
restricted by Vinted's terms of service: check them, keep the request rate low, and use at your own
risk. Set data comes from the [Brickset](https://brickset.com) API; follow its terms when you use it.

## Licence

[Apache License 2.0](LICENSE). If you redistribute this project or a derivative, keep the
[NOTICE](NOTICE) file with its attribution.
