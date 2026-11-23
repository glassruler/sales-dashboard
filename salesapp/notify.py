"""Send the summary to Telegram (Bot API) and WhatsApp (via the Baileys gateway service)."""
from __future__ import annotations

import os

import requests

TIMEOUT = 20


def _split(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and _split(os.getenv("TELEGRAM_CHAT_ID")))


def whatsapp_configured() -> bool:
    return bool(os.getenv("WA_GATEWAY_URL") and _split(os.getenv("WA_TO")))


def send_telegram(text: str, chat_ids: list[str] | None = None) -> list[str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_ids = chat_ids or _split(os.getenv("TELEGRAM_CHAT_ID"))
    if not token or not chat_ids:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum diisi")
    sent = []
    for cid in chat_ids:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": cid, "text": text}, timeout=TIMEOUT)
        if not r.ok:
            raise RuntimeError(f"Telegram {cid}: {r.status_code} {r.text[:200]}")
        sent.append(cid)
    return sent


def _wa_headers() -> dict:
    return {"Authorization": f"Bearer {os.getenv('WA_GATEWAY_TOKEN', '')}"}


def whatsapp_status() -> dict:
    url = os.getenv("WA_GATEWAY_URL")
    if not url:
        return {"connected": False, "error": "WA_GATEWAY_URL belum diisi"}
    try:
        r = requests.get(f"{url.rstrip('/')}/status", headers=_wa_headers(), timeout=5)
        return r.json()
    except Exception as e:
        return {"connected": False, "error": f"gateway tidak bisa dihubungi: {type(e).__name__}"}


def whatsapp_qr_png() -> bytes | None:
    url = os.getenv("WA_GATEWAY_URL")
    if not url:
        return None
    try:
        r = requests.get(f"{url.rstrip('/')}/qr.png", headers=_wa_headers(), timeout=5)
        return r.content if r.ok and r.headers.get("content-type", "").startswith("image") else None
    except Exception:
        return None


def send_whatsapp(text: str, recipients: list[str] | None = None) -> list[str]:
    url = os.getenv("WA_GATEWAY_URL")
    recipients = recipients or _split(os.getenv("WA_TO"))
    if not url or not recipients:
        raise RuntimeError("WA_GATEWAY_URL / WA_TO belum diisi")
    sent = []
    for to in recipients:
        r = requests.post(f"{url.rstrip('/')}/send", headers=_wa_headers(),
                          json={"to": to, "text": text}, timeout=TIMEOUT)
        if not r.ok:
            raise RuntimeError(f"WhatsApp {to}: {r.status_code} {r.text[:200]}")
        sent.append(to)
    return sent
