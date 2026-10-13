"""Fase 1+2: prueba de viabilidad. Consulta Wallapop y Vinted desde el runner
y envia el resultado (codigo HTTP + inicio de la respuesta) a Telegram."""
import os
import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def summarise(name, r):
    body = r.text[:150].replace("\n", " ")
    return f"{name}: HTTP {r.status_code} | {r.headers.get('content-type', '?')} | {len(r.content)} bytes\n{body}"


def probe_wallapop():
    # Endpoint interno no documentado: puede haber cambiado.
    r = requests.get(
        "https://api.wallapop.com/api/v3/general/search",
        params={"keywords": "lego 75192", "source": "search_box", "order_by": "newest"},
        headers={"User-Agent": UA, "X-DeviceOS": "0", "Accept": "application/json"},
        timeout=20,
    )
    return summarise("Wallapop", r)


def probe_vinted():
    # Vinted exige una cookie de sesion: primero se visita la home.
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
    s.get("https://www.vinted.es/", timeout=20)
    r = s.get(
        "https://www.vinted.es/api/v2/catalog/items",
        params={"search_text": "lego 75192", "per_page": 5},
        timeout=20,
    )
    return summarise("Vinted", r)


def main():
    lines = []
    for fn in (probe_wallapop, probe_vinted):
        try:
            lines.append(fn())
        except Exception as e:  # el fallo tambien es informacion
            lines.append(f"{fn.__name__}: ERROR {type(e).__name__}: {e}")
    text = "Probe Lego bot\n\n" + "\n\n".join(lines)
    resp = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text[:4000]},
        timeout=20,
    )
    print(resp.status_code, text)


if __name__ == "__main__":
    main()
