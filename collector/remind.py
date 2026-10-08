"""Daily goal reminders: a push notification every two hours through the day (.github/workflows/remind.yml)
until today's applications and contacts reach the goal, then one "done" message.

Reads the app's state from Redis (parcours:state, mirrored by api/state.js after every save) and the device
subscriptions from parcours:push:subs; each message replaces the previous one (same notification tag).
Times are local to REMIND_TZ (default Africa/Tunis). python collector/remind.py [--dry-run] [--force]
"""
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, os.path.dirname(__file__))
from notify import SUBS, _sender  # noqa: E402

STATE_KEY, DONE_KEY = "parcours:state", "parcours:push:goal-done"
DAY_START, DAY_END = 9, 21  # the hours the goal is paced over


class Store:
    def __init__(self):
        e = os.environ
        self.url = e.get("UPSTASH_REDIS_REST_URL") or e.get("KV_REST_API_URL")
        self.token = e.get("UPSTASH_REDIS_REST_TOKEN") or e.get("KV_REST_API_TOKEN")
        if not self.url or not self.token:
            sys.exit("Missing UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN.")

    def cmd(self, *args):
        r = requests.post(self.url, headers={"Authorization": "Bearer " + self.token}, json=list(args), timeout=30)
        r.raise_for_status()
        return r.json().get("result")


def counts(state, day):
    apps = [a for a in state.get("apps") or [] if a.get("date") == day]
    contacts = [c for c in state.get("contacts") or [] if c.get("date") == day]
    by = {k: sum(1 for a in apps if a.get("d") == k) for k in ("job", "phd", "master")}
    return dict(by, contacts=len(contacts), total=len(apps) + len(contacts))


def streak(state, today, goal):
    n, d = 0, today - timedelta(days=1)
    while n < 400 and counts(state, d.isoformat())["total"] >= goal:
        n, d = n + 1, d - timedelta(days=1)
    return n


def message(state, now, goal):
    day = now.date().isoformat()
    c = counts(state, day)
    left = goal - c["total"]
    queued = sum(1 for q in state.get("queue") or [] if q.get("status") == "todo")
    run = streak(state, now.date(), goal)
    if left <= 0:
        return {"title": f"Goal done: {c['total']}/{goal} today", "body": f"{c['job']} jobs, {c['phd']} PhDs, {c['master']} master's, {c['contacts']} contacts. "
                + (f"That makes {run + 1} days in a row." if run else "Same again tomorrow."), "url": "/#/", "tag": "goal"}, "done"
    span = max(1, DAY_END - DAY_START)
    should = round(goal * min(1, max(0, (now.hour + now.minute / 60 - DAY_START) / span)))
    nxt = f"{queued} offer{'s' if queued != 1 else ''} waiting in your apply queue." if queued else "Open Discover for offers, or email a professor."
    if now.hour < DAY_START + 2 and c["total"] == 0:
        title, body = f"Today: {goal} to send", f"Start now and it is easy by tonight. {nxt}"
    elif now.hour >= DAY_END - 1:
        title, body = f"Last push: {left} left", f"{c['total']}/{goal} so far. " + (f"Keep your {run}-day streak alive. " if run else "") + nxt
    elif c["total"] >= should:
        title, body = f"{c['total']}/{goal} · on track", f"{left} to go, you are ahead of pace. {nxt}"
    else:
        title, body = f"{c['total']}/{goal} · {left} to go", f"You should be near {should} by now: {should - c['total']} behind. " + (f"Don't break your {run}-day streak. " if run else "") + nxt
    return {"title": title, "body": body, "url": "/#/queue" if queued else "/#/", "tag": "goal"}, "remind"


def main():
    dry, force = "--dry-run" in sys.argv, "--force" in sys.argv
    store = Store()
    state = json.loads(store.cmd("GET", STATE_KEY) or "{}")
    goal = max(1, min(500, int(((state.get("goal") or {}).get("daily")) or 60)))
    now = datetime.now(ZoneInfo(os.environ.get("REMIND_TZ") or "Africa/Tunis"))
    if not force and not (DAY_START <= now.hour <= DAY_END):
        print(f"{now:%H:%M}: outside {DAY_START}:00-{DAY_END}:00, nothing sent")
        return
    payload, kind = message(state, now, goal)
    day = now.date().isoformat()
    if kind == "done" and store.cmd("GET", DONE_KEY) == day and not force:
        print("goal met, already congratulated today")
        return
    print(f"{now:%Y-%m-%d %H:%M} {payload['title']} | {payload['body']}")
    if dry:
        return
    send = _sender()
    if not send:
        sys.exit("VAPID_PRIVATE_KEY is not set.")
    flat = store.cmd("HGETALL", SUBS) or []
    sent = 0
    for i in range(0, len(flat), 2):
        rec = json.loads(flat[i + 1])
        if rec.get("goal") is False:
            continue
        r = send(rec["subscription"], payload)
        sent += r == "ok"
        if r == "gone":
            store.cmd("HDEL", SUBS, flat[i])
    if kind == "done":
        store.cmd("SET", DONE_KEY, day)
    print(f"sent to {sent} device{'s' if sent != 1 else ''}")


if __name__ == "__main__":
    main()
