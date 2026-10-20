# Vinted-Lego-scrapper
Vinted Lego scrapper

## Wanted list
Sets in `wanted.json` are searched on Vinted at every run (same 09:30 / 14:00 / 19:00 cadence) and every
new listing is appended to the digest in a 🎯 *Wanted list* block, with no discount filter. Knock-offs,
accessories, incomplete sets and loose figures are excluded, as in the main scan. Each listing is reported once.

Manage the list from the bot's Telegram chat (applied at the next run; the reply appears in that digest):
- `/want 21257 160 Tintin` add or update (price and name optional if the set is in `sets.csv`)
- `/unwant 21257` remove
- `/wanted` show the list

Or locally: `python wanted.py add 21257 --rrp 160 --name "Tintin" --keyword tintin`,
`python wanted.py remove 21257`, `python wanted.py list`. Or edit `wanted.json` on GitHub.
