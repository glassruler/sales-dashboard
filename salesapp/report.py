"""Build and send the summary. Used by the scheduler and runnable by hand:

    python -m salesapp.report --dry-run
    python -m salesapp.report --channels telegram,whatsapp
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .ai import summarize
from .analytics import build_facts
from .data import load_sales
from . import notify

log = logging.getLogger("report")


ROOT = Path(__file__).resolve().parents[1]


def data_path() -> str:
    """DATA_PATH from .env, else data/sales.csv, else sales.csv dropped in the project folder."""
    if os.getenv("DATA_PATH"):
        return os.getenv("DATA_PATH")
    for candidate in (ROOT / "data" / "sales.csv", ROOT / "sales.csv"):
        if candidate.exists():
            return str(candidate)
    return str(ROOT / "data" / "sales.csv")


def build_message(lang: str | None = None, use_ai: bool = True) -> tuple[str, str]:
    lang = lang or os.getenv("SUMMARY_LANG", "id")
    df, _ = load_sales(data_path())
    text, source = summarize(build_facts(df), lang=lang, use_ai=use_ai)
    header = "📊 Ringkasan Penjualan" if lang == "id" else "📊 Sales Summary"
    return f"{header}\n\n{text}", source


def send(text: str, channels: list[str]) -> dict:
    results = {}
    for ch in channels:
        try:
            if ch == "telegram":
                results[ch] = f"terkirim ke {', '.join(notify.send_telegram(text))}"
            elif ch == "whatsapp":
                results[ch] = f"terkirim ke {', '.join(notify.send_whatsapp(text))}"
            else:
                results[ch] = "channel tidak dikenal"
        except Exception as e:
            results[ch] = f"GAGAL: {e}"
    return results


def run(channels: list[str] | None = None, dry_run: bool = False) -> dict:
    channels = channels or [c.strip() for c in os.getenv("REPORT_CHANNELS", "telegram,whatsapp").split(",") if c.strip()]
    text, source = build_message()
    log.info("summary source: %s", source)
    if dry_run:
        print(text)
        return {"dry_run": True, "source": source}
    res = send(text, channels)
    log.info("send results: %s", res)
    return res


def main() -> None:
    load_dotenv()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--channels", help="comma list: telegram,whatsapp")
    p.add_argument("--dry-run", action="store_true", help="print the message, send nothing")
    a = p.parse_args()
    print(run(a.channels.split(",") if a.channels else None, a.dry_run))


if __name__ == "__main__":
    main()
