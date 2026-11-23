"""Send the summary to Telegram (Bot API) and WhatsApp (via the Baileys gateway service)."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests

TIMEOUT = 20


def _split(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


# --------------------------------------------------------------------------- WA recipients
# Kept in data/recipients.json (same volume as the sales CSV) so the dashboard and the
# scheduler share one list. WA_TO in .env only seeds the list the first time.

def recipients_path() -> Path:
    default = Path(os.getenv("DATA_PATH", "data/sales.csv")).parent / "recipients.json"
    return Path(os.getenv("RECIPIENTS_PATH", str(default)))


def normalize_wa(to: str) -> str:
    """'0812-3456 789' -> '628123456789'; group ids (...@g.us) pass through. Raises ValueError."""
    t = str(to or "").strip()
    if not t:
        raise ValueError("kosong")
    if "@" in t:
        if not re.fullmatch(r"[\w.-]+@(g\.us|s\.whatsapp\.net)", t):
            raise ValueError(f"id tidak valid: {t}")
        return t
    d = re.sub(r"\D", "", t)
    if d.startswith("0"):
        d = "62" + d[1:]
    if not 9 <= len(d) <= 15:
        raise ValueError(f"nomor tidak valid: {t}")
    return d


def load_recipients() -> list[dict]:
    p = recipients_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return [{"name": str(r.get("name", "")), "number": str(r["number"]),
                     "active": bool(r.get("active", True))} for r in data if r.get("number")]
        except Exception:
            pass
    seeded = []
    for n in _split(os.getenv("WA_TO")):
        try:
            seeded.append({"name": "", "number": normalize_wa(n), "active": True})
        except ValueError:
            continue
    return seeded


def save_recipients(rows: list[dict]) -> list[dict]:
    """Validate, de-duplicate and save. Raises ValueError listing every bad row."""
    clean, errors, seen = [], [], set()
    for i, r in enumerate(rows, 1):
        raw = str(r.get("number") or "").strip()
        if not raw:
            continue
        try:
            n = normalize_wa(raw)
        except ValueError as e:
            errors.append(f"baris {i}: {e}")
            continue
        if n in seen:
            continue
        seen.add(n)
        clean.append({"name": str(r.get("name") or "").strip(), "number": n,
                      "active": bool(r.get("active", True))})
    if errors:
        raise ValueError("; ".join(errors))
    p = recipients_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return clean


def active_wa_recipients() -> list[str]:
    return [r["number"] for r in load_recipients() if r["active"]]


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and _split(os.getenv("TELEGRAM_CHAT_ID")))


def whatsapp_configured() -> bool:
    return bool(os.getenv("WA_GATEWAY_URL") and active_wa_recipients())


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
    recipients = recipients or active_wa_recipients()
    if not url or not recipients:
        raise RuntimeError("Belum ada penerima WhatsApp aktif")
    # One failing number must not stop the others: send to all, then report failures.
    sent, failed = [], []
    for i, to in enumerate(recipients):
        if i:
            time.sleep(1.5)  # gentle pacing; WhatsApp dislikes bursts from linked devices
        try:
            r = requests.post(f"{url.rstrip('/')}/send", headers=_wa_headers(),
                              json={"to": to, "text": text}, timeout=TIMEOUT)
            if r.ok:
                sent.append(to)
            else:
                try:
                    reason = r.json().get("error", r.status_code)
                except ValueError:
                    reason = r.status_code
                failed.append(f"{to}: {reason}")
        except Exception as e:
            failed.append(f"{to}: {type(e).__name__}")
    if failed:
        raise RuntimeError(f"terkirim {len(sent)}/{len(recipients)}; gagal: " + "; ".join(failed))
    return sent


def whatsapp_logout() -> None:
    url = os.getenv("WA_GATEWAY_URL")
    r = requests.post(f"{url.rstrip('/')}/logout", headers=_wa_headers(), timeout=TIMEOUT)
    r.raise_for_status()
