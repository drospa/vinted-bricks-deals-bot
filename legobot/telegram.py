"""Sending messages to the Telegram chat. Needs TELEGRAM_TOKEN and TELEGRAM_CHAT_ID."""
import os

import requests

def send_telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
        data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": "true"},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text[:200]}")


def send_safe(text):
    """Send; if Telegram rejects the length, split on line boundaries by raw size and retry."""
    try:
        send_telegram(text)
    except RuntimeError as e:
        if "too long" not in str(e).lower():
            raise
        print("Message too long for Telegram, re-splitting by raw length", flush=True)
        cur = ""
        for line in text.split("\n"):
            if cur and len(cur) + len(line) + 1 > 3800:
                send_telegram(cur)
                cur = ""
            cur += ("\n" if cur else "") + line
        if cur:
            send_telegram(cur)
