"""Long-running scheduler: sends the summary on REPORT_CRON (Asia/Jakarta time).

Default: every Monday 08:00 WIB. Set REPORT_CRON="" to disable.
"""
from __future__ import annotations

import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from .report import run


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("scheduler")
    cron = os.getenv("REPORT_CRON", "0 8 * * 1")
    tz = os.getenv("TZ_REPORT", "Asia/Jakarta")
    sched = BlockingScheduler(timezone=tz)
    if not cron.strip():
        log.warning("REPORT_CRON kosong: scheduler idle")
    else:
        sched.add_job(run, CronTrigger.from_crontab(cron, timezone=tz), name="sales-summary",
                      misfire_grace_time=3600, coalesce=True)
        log.info("Laporan dijadwalkan: '%s' (%s)", cron, tz)
    sched.start()


if __name__ == "__main__":
    main()
