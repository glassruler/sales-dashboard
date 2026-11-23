"""Summary writer and Q&A.

Python computes every number (see analytics.build_facts). The LLM only rewrites the fact
sheet into a readable paragraph. Providers are tried in order: Gemini -> Cloudflare Workers
AI -> deterministic template, so a summary is always produced. AI output that contains a
number not present in the facts is rejected and the template is used instead.
"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

log = logging.getLogger(__name__)
TIMEOUT = 45


# --------------------------------------------------------------------------- template
def template_summary(f: dict, lang: str = "id") -> str:
    w = f["weak_outlets"]
    weak_txt = ", ".join(f"{o['name']} ({o['branch']}, {o['mom']})" for o in w[:5])
    if lang == "en":
        s = f"Sales update {f['period']}: net sales {f['net_sales']} from {f['invoices']} invoices"
        if "mom" in f:
            m = f["mom"]
            s += f", {m['cur_label']} {m['cur']} vs {m['prev_label']} {m['prev']} ({m['change']})"
        s += (f". {f['top_region']['name']} leads with {f['top_region']['share']} of sales, "
              f"{f['bottom_region']['name']} is smallest ({f['bottom_region']['share']}). "
              f"{f['top_brand']['name']} is the top brand ({f['top_brand']['share']}).")
        if "mom" in f:
            s += (f" Watch {f['region_worst_mom']['name']} ({f['region_worst_mom']['mom']}) and "
                  f"{f['brand_worst_mom']['name']} ({f['brand_worst_mom']['mom']}).")
        s += f" Weakest outlets: {weak_txt}. Action: schedule visits to these outlets this week."
        return s
    s = f"Update penjualan {f['period']}: net sales {f['net_sales']} dari {f['invoices']} invoice"
    if "mom" in f:
        m = f["mom"]
        s += f", {m['cur_label']} {m['cur']} vs {m['prev_label']} {m['prev']} ({m['change']})"
    s += (f". {f['top_region']['name']} memimpin dengan kontribusi {f['top_region']['share']}, "
          f"{f['bottom_region']['name']} terkecil ({f['bottom_region']['share']}). "
          f"{f['top_brand']['name']} tetap brand utama ({f['top_brand']['share']}).")
    if "mom" in f:
        s += (f" Perlu perhatian: {f['region_worst_mom']['name']} ({f['region_worst_mom']['mom']}) "
              f"dan {f['brand_worst_mom']['name']} ({f['brand_worst_mom']['mom']}).")
    s += f" Outlet terlemah: {weak_txt}. Saran: jadwalkan kunjungan salesman ke outlet tersebut minggu ini."
    return s


# --------------------------------------------------------------------------- providers
SYSTEM_SUMMARY = {
    "id": ("Kamu analis penjualan FMCG. Tulis SATU paragraf ringkas (maks 110 kata) dalam Bahasa "
           "Indonesia untuk sales manager yang membaca di WhatsApp/Telegram. Gunakan HANYA angka "
           "yang ada di data JSON, tulis persis seperti di data, jangan menghitung angka baru. "
           "Isi: total & perubahan bulanan, region/brand terkuat dan yang perlu perhatian, "
           "5 outlet terlemah, dan 1 saran tindakan konkret. Teks biasa, tanpa markdown, "
           "tanpa bullet, tanpa salam pembuka."),
    "en": ("You are an FMCG sales analyst. Write ONE concise paragraph (max 110 words) in English "
           "for a sales manager reading on WhatsApp/Telegram. Use ONLY numbers present in the JSON, "
           "written exactly as given; never compute new numbers. Cover: total and monthly change, "
           "strongest region/brand and those needing attention, the 5 weakest outlets, and one "
           "concrete action. Plain text, no markdown, no bullets, no greeting."),
}


def _gemini(system: str, user: str) -> str | None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.3},
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def _cloudflare(system: str, user: str) -> str | None:
    acct, token = os.getenv("CF_ACCOUNT_ID"), os.getenv("CF_API_TOKEN")
    if not (acct and token):
        return None
    model = os.getenv("CF_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
    r = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}",
        headers={"Authorization": f"Bearer {token}"},
        json={"messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}],
              "temperature": 0.3, "max_tokens": 600},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    res = r.json()["result"]
    return (res.get("response") or "").strip()


PROVIDERS = {"gemini": _gemini, "cloudflare": _cloudflare}


def _provider_order() -> list[str]:
    first = os.getenv("AI_PROVIDER", "gemini").lower()
    return [first] + [p for p in PROVIDERS if p != first]


def complete(system: str, user: str) -> tuple[str | None, str]:
    """Try providers in order. Returns (text, provider_name) or (None, error_summary)."""
    errors = []
    for name in _provider_order():
        try:
            out = PROVIDERS[name](system, user)
            if out:
                return out, name
            errors.append(f"{name}: tidak dikonfigurasi")
        except Exception as e:  # network/HTTP/shape errors: fall through to next provider
            log.warning("AI provider %s failed: %s", name, e)
            errors.append(f"{name}: {type(e).__name__}")
    return None, "; ".join(errors)


# --------------------------------------------------------------------------- guard
_NUM = re.compile(r"[-+]?\d[\d.,]*%?")


def unknown_numbers(text: str, facts: dict) -> list[str]:
    """Number tokens in `text` that do not appear in the facts (small counts <=10 allowed)."""
    hay = json.dumps(facts, ensure_ascii=False)
    bad = []
    for tok in _NUM.findall(text):
        t = tok.strip(".,").lstrip("+")
        if not t or t in hay or t.lstrip("-") in hay:
            continue
        if t.isdigit() and int(t) <= 10:
            continue
        bad.append(tok)
    return bad


def summarize(facts: dict, lang: str = "id", use_ai: bool = True) -> tuple[str, str]:
    """Return (paragraph, source) where source is 'gemini' | 'cloudflare' | 'template ...'."""
    if use_ai:
        text, src = complete(SYSTEM_SUMMARY[lang],
                             "DATA:\n" + json.dumps(facts, ensure_ascii=False, indent=1))
        if text:
            text = " ".join(text.replace("*", "").split())
            bad = unknown_numbers(text, facts)
            if not bad:
                return text, src
            log.warning("AI output rejected, unknown numbers: %s", bad)
            return template_summary(facts, lang), f"template (AI {src} menyebut angka di luar data: {', '.join(bad[:3])})"
        return template_summary(facts, lang), f"template ({src})"
    return template_summary(facts, lang), "template"


def ask(question: str, context: str, lang: str = "id") -> tuple[str, str]:
    system = ("Kamu asisten analis penjualan. Jawab hanya berdasarkan DATA. Jika data tidak cukup, "
              "katakan tidak tahu. Jawab singkat, Bahasa Indonesia." if lang == "id" else
              "You are a sales analyst assistant. Answer only from DATA. If the data is "
              "insufficient, say so. Be brief, English.")
    text, src = complete(system, f"DATA:\n{context}\n\nPERTANYAAN: {question}")
    if not text:
        return ("AI belum dikonfigurasi atau tidak bisa dihubungi. Isi GEMINI_API_KEY atau "
                "CF_ACCOUNT_ID + CF_API_TOKEN di file .env."), src
    return text, src
