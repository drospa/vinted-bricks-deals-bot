"""One digest per schedule slot, in local time, whatever triggered the run."""
from datetime import datetime

from .config import SLOTS, TIMEZONE

def schedule_slot(state, now=None):
    """Scheduled runs only. GitHub cron is UTC-only, so several UTC crons fire and this guard keeps
    exactly one run per local-time slot (config.toml [schedule]), whatever the daylight-saving offset.
    Returns the slot id to run, or None to skip."""
    from zoneinfo import ZoneInfo
    now = now or datetime.now(ZoneInfo(TIMEZONE))
    started = [name for name, start in SLOTS if (now.hour, now.minute) >= start]
    if not started:
        print(f"Skipping: {TIMEZONE} time {now:%H:%M}, before the first slot")
        return None
    slot = f"{now:%Y-%m-%d}-{started[-1]}"
    if state.get("last_slot") == slot:
        print(f"Skipping: {TIMEZONE} time {now:%H:%M}, slot {slot} already done")
        return None
    return slot


def today_str():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TIMEZONE)).strftime("%d/%m/%Y")
    except Exception:
        return datetime.now().strftime("%d/%m/%Y")
