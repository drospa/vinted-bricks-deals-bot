"""Telegram digest formatting (HTML parse mode), split into messages under Telegram's length limit."""
import html
import re

from .config import (COND_SHORT, IDEAS_EXPERIMENT, MAX_ITEMS, MAX_SUSPICIOUS, MAX_SW_FIGURES,
                     MIN_DISCOUNT_NEW)

def eur(price):
    """Listing price for the digest; '?€' when Vinted gave none (wanted and Star Wars figure blocks
    have no discount test, so they can hold listings without a price)."""
    return f"{price:.0f}€" if price else "?€"


def wanted_blocks(hits):
    """Wanted list: every new listing, grouped by set, cheapest first."""
    if not hits:
        return []
    esc = html.escape
    blocks = ["\n\n🎯 <b>Wanted list</b> (every new listing, no discount filter)"]
    groups = {}
    for d in hits:
        groups.setdefault(d["set_no"], []).append(d)
    for no, g in groups.items():
        ref = f"RRP {g[0]['rrp']:.0f}€" if g[0]["rrp"] else "no RRP"
        entries = "\n".join(
            f"   • <a href=\"{esc(x['url'], quote=True)}\">{eur(x['price'])}</a>"
            + (f" {fmt_pct(x['discount'])}" if x["discount"] is not None else "")
            + f" {cond_short(x['condition'])} · {esc(short_title(x['title']))}" for x in g)
        blocks.append(f"\n<b>{esc(no)} {esc(g[0]['set_name'])}</b> · {ref}\n{entries}")
    return blocks


def fmt_pct(discount):
    """Price change vs official price, one format everywhere: '-62%', '+7%'. ASCII minus only."""
    change = -discount * 100
    return f"{'+' if change > 0 else '-' if change < 0 else ''}{abs(change):.0f}%"


def rrp_str(d):
    """Official price; '~' marks a price estimated from the US/UK/CA price (no euro price published)."""
    return f"{'~' if d.get('approx') else ''}{d['rrp']:.0f}€"


def cond_short(cond):
    return COND_SHORT.get((cond or "").strip().lower(), cond or "?")


def short_title(t, n=45):
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def set_label(d):
    name = re.sub(r"^The Lord of the Rings:\s*", "", d["set_name"])
    return f"{d['set_no']} {name}"


def grouped_set_blocks(sets, header):
    """Identified listings grouped by set, best discount first; each set lists every listing by price."""
    esc = html.escape
    link = lambda d, text: f"<a href=\"{esc(d['url'], quote=True)}\">{esc(text)}</a>"
    price = lambda d: f"{d['price']:.0f}€" if d["price"] else "?€"
    blocks, groups = [], {}
    for d in sets:
        groups.setdefault(d["set_no"], []).append(d)
    def best(g):
        ds = [x["discount"] for x in g if x["discount"] is not None]
        return (not ds, -(max(ds) if ds else 0), g[0]["set_no"])
    if groups:
        blocks.append(header)
    for g in sorted(groups.values(), key=best):
        g.sort(key=lambda x: x["price"] or 0)
        d0 = g[0]
        if d0["rrp"]:
            ref = f"RRP {rrp_str(d0)}"
        elif d0.get("lot") and d0.get("known_rrp"):
            ref = f"RRP known only for {' + '.join(d0['known_nums'])}: {d0['known_rrp']:.0f}€"
        else:
            ref = "GWP, no RRP" if d0.get("promo") else "no RRP"
        flags = (" 🏷️" if d0["retired"] else "") + (" 📦 lot" if d0.get("lot") else "")
        entries = " · ".join(
            link(x, price(x)) + (f" {fmt_pct(x['discount'])}" if x["discount"] is not None else "")
            + f" {cond_short(x['condition'])}" + (" 🔎" if x.get("by_name") else "") for x in g)
        blocks.append(f"\n<b>{esc(set_label(d0))}</b> · {ref}{flags}\n   {entries}")
    return blocks


def ideas_blocks(ideas):
    """Lego Ideas experiment: every identified listing, no discount filter."""
    return grouped_set_blocks(ideas, "\n\n💡 <b>Lego Ideas</b> (experiment, no discount filter)")


def lotr_blocks(lotr):
    """Lord of the Rings, every listing, grouped: complete sets by set, then unidentified, then figures."""
    esc = html.escape
    link = lambda d, text: f"<a href=\"{esc(d['url'], quote=True)}\">{esc(text)}</a>"
    price = lambda d: f"{d['price']:.0f}€" if d["price"] else "?€"
    sets = [d for d in lotr if d["set_no"] != "?" and not d["figure"]]
    unid = [d for d in lotr if d["set_no"] == "?" and not d["figure"]]
    figs = [d for d in lotr if d["figure"]]
    blocks = grouped_set_blocks(sets, "\n\n🧙 <b>Lord of the Rings sets</b>")
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


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def fmt_excluded(c):
    if not c:
        return "0 excluded"
    return f"{sum(c.values())} excluded (" + ", ".join(f"{k} {v}" for k, v in c.most_common()) + ")"


def build_messages(deals, suspicious, lotr, sw_figs, stats, lotr_info, warnings, today,
                   wanted_hits=(), wanted_info=None, ideas=()):
    esc = html.escape
    head = f"🧱 <b>Lego deals {today}</b>: {len(deals)} found" + (
        f" · {len(lotr)} new Lord of the Rings" if lotr else "") + (
        f" · {len(sw_figs)} Star Wars figures" if sw_figs else "") + (
        f" · 💡 {len(ideas)} Ideas" if ideas else "") + (
        f" · 🎯 {len(wanted_hits)} wanted" if wanted_hits else "")
    blocks = []
    for i, d in enumerate(deals[:MAX_ITEMS], 1):
        flags = (" 🏷️ retired" if d["retired"] else "") + (" 📦 lot" if d.get("lot") else "") + (
            " 🔎 matched by name" if d.get("by_name") else "")
        blocks.append(
            f"\n{i}. <b>{esc(d['set_no'])} {esc(d['set_name'])}</b>\n"
            f"{d['price']:.0f}€ vs {rrp_str(d)} ({fmt_pct(d['discount'])}) · "
            f"{esc(d['condition'])} · {esc(d['theme'])}{flags}\n"
            f"<a href=\"{esc(d['url'], quote=True)}\">Open on Vinted</a>"
        )
    if len(deals) > MAX_ITEMS:
        blocks.append(f"\n… and {len(deals) - MAX_ITEMS} more")
    if sw_figs:
        blocks.append("\n\n🧍 <b>Star Wars loose figures</b> (set number found in title; no discount filter, newest first):")
        for d in sw_figs[:MAX_SW_FIGURES]:
            blocks.append(
                f"\n• <b>{esc(d['set_no'])} {esc(d['set_name'])}</b>: {eur(d['price'])} · {esc(d['condition'])} · "
                f"<a href=\"{esc(d['url'], quote=True)}\">link</a>")
        if len(sw_figs) > MAX_SW_FIGURES:
            blocks.append(f"\n… and {len(sw_figs) - MAX_SW_FIGURES} more")
    blocks += lotr_blocks(lotr)
    blocks += ideas_blocks(list(ideas))
    if suspicious:
        blocks.append("\n\n⚠️ <b>Too good to be true</b> (likely parts, minifigs or mis-titled):")
        for d in suspicious[:MAX_SUSPICIOUS]:
            blocks.append(
                f"\n• {esc(d['set_no'])} {esc(d['set_name'])}: {d['price']:.0f}€ vs {rrp_str(d)} "
                f"({fmt_pct(d['discount'])}) · <a href=\"{esc(d['url'], quote=True)}\">link</a>")
        if len(suspicious) > MAX_SUSPICIOUS:
            blocks.append(f"\n… and {len(suspicious) - MAX_SUSPICIOUS} more")
    blocks += wanted_blocks(list(wanted_hits))
    n_figs = sum(1 for d in lotr if d["figure"])
    n_unid = sum(1 for d in lotr if d["set_no"] == "?" and not d["figure"])
    foot = (f"\n\n<i>Vinted: {stats['scanned']} new listings · {stats['matched']} matched"
            f"{' (' + str(stats['by_name']) + ' by name 🔎)' if stats.get('by_name') else ''} · "
            f"{stats['unidentified']} unidentified · {esc(fmt_excluded(stats['excluded']))} · "
            f"{len(deals) + len(suspicious)} at ≥{MIN_DISCOUNT_NEW * 100:.0f}% off\n"
            f"LotR: {len(lotr)} new ({plural(len(lotr) - n_figs - n_unid, 'set')}, {plural(n_figs, 'figure')}, {n_unid} unidentified)"
            f" · {lotr_info['already']} already reported, still listed"
            + (f"\nIdeas (experiment): {len(ideas)} new, no discount filter" if IDEAS_EXPERIMENT else "")
            + (f"\nWanted: {plural(wanted_info['watched'], 'set')} watched · {len(wanted_hits)} new"
               f" · {esc(fmt_excluded(wanted_info['excluded']))}" if wanted_info else "")
            + (("\n" + esc(wanted_info["replies"])) if wanted_info and wanted_info.get("replies") else "")
            +
            f"\nPrices exclude shipping and buyer fee. ~ = RRP estimated from US/UK price.</i>")
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
