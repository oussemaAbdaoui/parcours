"""Hiring log: every offer ever seen, per company, with the date it was posted (or first seen).

Stored offers are pruned after 45 days, so this log is what makes recruitment periods visible over time
(busiest months and weekdays, how often a company posts, when its next wave is likely). Both collectors
add to it on every run, including offers dropped as dealbreakers: they still show when a company recruits.

Redis hash parcours:companies:history, one field per company (normalised name):
  {"name": "Inria", "seen": {"<offer id>": "2026-10-02|phd|p", ...}}   (newest 400 offers per company)
The last letter says where the date comes from: p = posted date given by the source, s = first seen by a
collector run (within hours of posting), b = seeded from offers stored before the log existed (their first-seen
day is when collection started, so weekday and rhythm figures leave them out).
"""
import json
import re
from datetime import date, datetime, timezone

from enrich import _norm

HISTORY_KEY = "parcours:companies:history"
MAX_PER_COMPANY = 400


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
    by_co = {}
    for x in offers:
        n = _norm(x.get("org"))
        if n and len(n) >= 2 and x.get("id"):
            by_co.setdefault(n, []).append(x)
    if not by_co:
        return 0
    keys = list(by_co)
    added, batch = 0, []
    for i in range(0, len(keys), 100):
        chunk = keys[i:i + 100]
        current = store.cmd("HMGET", HISTORY_KEY, *chunk) or [None] * len(chunk)
        for k, raw in zip(chunk, current):
            rec = json.loads(raw) if raw else {"name": by_co[k][0]["org"], "seen": {}}
            before = len(rec["seen"])
            for x in by_co[k]:
                day, src = _day(x, backfill)
                rec["seen"].setdefault(x["id"], f"{day}|{x.get('kind') or 'job'}|{src}")
            if len(rec["seen"]) == before:
                continue
            added += len(rec["seen"]) - before
            if len(rec["seen"]) > MAX_PER_COMPANY:  # keep the newest
                rec["seen"] = dict(sorted(rec["seen"].items(), key=lambda kv: kv[1], reverse=True)[:MAX_PER_COMPANY])
            batch += [k, json.dumps(rec, ensure_ascii=False)]
            if len(batch) >= 80:
                store.cmd("HSET", HISTORY_KEY, *batch)
                batch = []
    if batch:
        store.cmd("HSET", HISTORY_KEY, *batch)
    return added
