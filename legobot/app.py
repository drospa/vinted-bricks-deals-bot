"""Daily run: read Telegram commands, scan Vinted, classify, send the digest, save state.
Env: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, RUN_MODE (dry-run | live | scheduled), DRY_RUN (true = print only),
DATA_DIR (where state.json / wanted.json live; default data/)."""
import html
import os
import random
import sys
import time

import requests

from . import wanted as wl
from .catalogue import load_catalogue
from .config import (ALERTED_CAP, IDEAS_EXPERIMENT, IDEAS_PAGES, IDEAS_QUERIES, LOTR_PAGES, LOTR_QUERIES,
                     MAX_PAGES, PAUSE, WANTED_PAGES)
from .digest import build_messages
from .filters import check_stats, evaluate, evaluate_wanted
from .schedule import schedule_slot, today_str
from .state import load_state, save_state
from .telegram import send_safe
from .vinted import FetchError, fetch_page

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
    # Wanted list: apply /want, /unwant, /wanted sent to the bot since the last run
    wanted = wl.load()
    wanted_changed, replies, tg_offset = False, [], state.get("tg_offset")
    cmd_warning = None
    if os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        try:
            texts, tg_offset = wl.fetch_commands(os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT_ID"],
                                                 tg_offset, requests.get)
            for t in texts:
                before = list(wanted)
                wanted, reply = wl.apply_command(wanted, t, catalogue)
                if reply:
                    replies.append(reply)
                    wanted_changed |= wanted != before
        except Exception as e:  # e.g. 409 when a webhook is set: the digest still goes out
            cmd_warning = f"Wanted-list commands not read: {e}"
    print(f"wanted: {len(wanted)} sets | commands: {replies}")
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
    if cmd_warning:
        warnings.append(cmd_warning)

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

    # Targeted Ideas searches (experiment)
    ideas_found = {}
    for q in (IDEAS_QUERIES if IDEAS_EXPERIMENT else []):
        for page in range(1, IDEAS_PAGES + 1):
            try:
                items = fetch_page(page, q)
            except FetchError as e:
                warnings.append(f"Ideas search '{q}' page {page}: {e}")
                break
            if not items:
                break
            for it in items:
                ideas_found[it["id"]] = it
            time.sleep(random.uniform(*PAUSE))
    print(f"Ideas search listings: {len(ideas_found)}")

    # Targeted wanted-list searches (one per set number / keyword set)
    wanted_found = {}
    for q in wl.search_queries(wanted):
        for page in range(1, WANTED_PAGES + 1):
            try:
                items = fetch_page(page, q)
            except FetchError as e:
                warnings.append(f"Wanted search '{q}' page {page}: {e}")
                break
            if not items:
                break
            for it in items:
                wanted_found[it["id"]] = it
            time.sleep(random.uniform(*PAUSE))
    print(f"wanted search listings: {len(wanted_found)}")

    new_items = [it for it in by_id.values() if it["id"] > last_id and it["id"] not in alerted]
    ideas = [] if IDEAS_EXPERIMENT else None
    deals, suspicious, lotr, sw_figs, stats = evaluate(new_items, catalogue, ideas=ideas)
    seen = {d["id"] for d in lotr}
    fresh = [it for it in extra.values() if it["id"] not in alerted and it["id"] not in seen]
    _, _, lotr_extra, _, lotr_stats = evaluate(fresh, catalogue)
    lotr += lotr_extra
    lotr.sort(key=lambda d: (d["discount"] is None, -(d["discount"] or 0)))
    ideas_stats = None
    if IDEAS_EXPERIMENT:
        seen = {it["id"] for it in new_items} | {d["id"] for d in lotr}
        fresh = [it for it in ideas_found.values() if it["id"] not in alerted and it["id"] not in seen]
        ideas_stats = evaluate(fresh, catalogue, ideas=ideas)[4]
        ideas = list({d["id"]: d for d in ideas}.values())
    # Wanted list: any not-yet-reported listing from any of the scans; it is shown only in that block
    pool = {**by_id, **extra, **ideas_found, **wanted_found}
    wanted_hits, wanted_excl = evaluate_wanted([it for i, it in pool.items() if i not in alerted], wanted)
    wanted_ids = {d["id"] for d in wanted_hits}
    deals = [d for d in deals if d["id"] not in wanted_ids]
    suspicious = [d for d in suspicious if d["id"] not in wanted_ids]
    sw_figs = [d for d in sw_figs if d["id"] not in wanted_ids]
    lotr = [d for d in lotr if d["id"] not in wanted_ids]
    ideas = [d for d in (ideas or []) if d["id"] not in wanted_ids]
    wanted_info = {"watched": len(wanted), "excluded": wanted_excl, "replies": "\n".join(replies)}
    check_stats(stats, "main scan")
    check_stats(lotr_stats, "LotR searches")
    if ideas_stats:
        check_stats(ideas_stats, "Ideas searches")
    print(f"Ideas: {len(ideas)} new | Ideas search stats {ideas_stats}")
    # Count only search results that are actually LotR listings (the searches also return other Lego)
    old = [it for i, it in extra.items() if i in alerted]
    lotr_info = {"active": len(extra), "already": len(evaluate(old, catalogue)[2])}
    print(f"LotR: {len(lotr)} new, {lotr_info['already']} already reported | main stats {stats} | "
          f"LotR search stats {lotr_stats}")
    for m in build_messages(deals, suspicious, lotr, sw_figs, stats, lotr_info, warnings, today_str(),
                            wanted_hits, wanted_info, ideas):
        out(m)

    if not dry:
        if not error and by_id:
            state["last_id"] = max(by_id)
        if slot and not error:
            state["last_slot"] = slot
        sent = [d["id"] for d in deals + suspicious + lotr + sw_figs + ideas + wanted_hits]
        if tg_offset is not None:
            state["tg_offset"] = tg_offset
        if wanted_changed:
            wl.save(wanted)
        # Ordered list, oldest first, so the cap evicts the oldest IDs (a set lost the order)
        state["alerted"] = list(dict.fromkeys(alerted_order + sent))[-ALERTED_CAP:]
        save_state(state)
