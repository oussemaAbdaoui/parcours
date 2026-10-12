"""Hiring log: every offer ever seen, per company, with the date it was posted (or first seen).

Stored offers are pruned after 45 days, so this log is what makes recruitment periods visible over time
(busiest months and weekdays, how often a company posts, when its next wave is likely). Both collectors
add to it on every run, including offers dropped as dealbreakers: they still show when a company recruits.

Postgres table company_seen, one row per company and offer: (company, offer id, day, kind, src).
src says says where the date comes from: p = posted date given by the source, s = first seen by a
collector run (within hours of posting), b = seeded from offers stored before the log existed (their first-seen
day is when collection started, so weekday and rhythm figures leave them out).
"""
import re
import time
from datetime import date, datetime, timezone

from enrich import _norm



def _day(x, backfill=False):
    """(day, source): the posted date when the source gives a recent ISO date, else the day it was first seen."""
    p = str(x.get("posted") or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
        try:
            d = date.fromisoformat(p)
            if 0 <= (date.today() - d).days <= 120:
                return p, "p"
        except ValueError:
            pass
    ms = x.get("foundAt")
    day = datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat() if ms else date.today().isoformat()
    return day, "b" if backfill else "s"


def record(store, offers, backfill=False):
    """Adds offers to the log (idempotent: an offer id counts once). Returns how many were new."""
    import pg
    rows = []
    for x in offers:
        n = _norm(x.get("org"))
        if n and len(n) >= 2 and x.get("id"):
            day, src = _day(x, backfill)
            rows.append((n, x.get("org") or n, x["id"], day, x.get("kind") or "job", src))
    return pg.company_seen(rows, int(time.time() * 1000))
