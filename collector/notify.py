"""Push notifications from the collectors (standard Web Push, keys in VAPID_* secrets).

- After each run: new offers scoring at or above a device's threshold ("3 new strong matches: ...").
- Weekly digest (cloud collector, first run after Monday 05:00 UTC): strong matches of the week,
  deadlines in the next 7 days, applications waiting over 14 days for a reply.
Subscriptions live in the Redis hash parcours:push:subs; ones the push service reports gone are removed.
"""
import json
import os
from datetime import date, datetime, timedelta, timezone

SUBS, DIGEST_KEY = "parcours:push:subs", "parcours:push:digest-week"


def _sender():
    priv = os.environ.get("VAPID_PRIVATE_KEY")
    if not priv:
        return None
    from py_vapid import Vapid01
    from pywebpush import WebPushException, webpush
    vapid = Vapid01.from_raw(priv.encode())
    claims = {"sub": os.environ.get("VAPID_SUBJECT", "https://parcours-swart.vercel.app")}

    def send(sub, payload):
        try:
            webpush(subscription_info=sub, data=json.dumps(payload), vapid_private_key=vapid, vapid_claims=dict(claims), ttl=86400)
            return "ok"
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            return "gone" if code in (404, 410) else f"error {code}"
    return send


def _subs(store):
    flat = store.cmd("HGETALL", SUBS) or []
    return [(flat[i], json.loads(flat[i + 1])) for i in range(0, len(flat), 2)]


def notify(store, items, scores, now, state, origin):
    """Returns a short status string for the run report."""
    send = _sender()
    if not send or not store:
        return "not configured"
    subs = _subs(store)
    if not subs:
        return "no devices"
    sent = gone = 0
    fresh = [x for x in items if x.get("foundAt") == now and x["id"] in scores]
    for endpoint, rec in subs:
        strong = sorted((x for x in fresh if scores[x["id"]] >= rec.get("threshold", 80)), key=lambda x: -scores[x["id"]])
        if not strong:
            continue
        top = strong[0]
        body = f"{top['title']} at {top.get('org') or top['source']} ({scores[top['id']]})"
        if len(strong) > 1:
            body += f" and {len(strong) - 1} more"
        r = send(rec["subscription"], {"title": f"{len(strong)} new strong match{'es' if len(strong) > 1 else ''}", "body": body,
                                       "url": "/#/opps/all", "tag": "matches"})
        sent += r == "ok"
        if r == "gone":
            store.cmd("HDEL", SUBS, endpoint)
            gone += 1
    out = f"{sent} match alert{'s' if sent != 1 else ''}"
    if origin == "cloud":
        out += ", " + digest(store, items, scores, state, send, [s for s in subs if s[1].get("digest", True)])
    return out + (f", {gone} expired devices removed" if gone else "")


def digest(store, items, scores, state, send, subs):
    now = datetime.now(timezone.utc)
    week = now.strftime("%G-W%V")
    if now.weekday() != 0 or now.hour < 5 or not subs or store.cmd("GET", DIGEST_KEY) == week:
        return "no digest due"
    week_ago = int((now - timedelta(days=7)).timestamp() * 1000)
    strong = [x for x in items if x.get("foundAt", 0) >= week_ago and scores.get(x["id"], 0) >= 75]
    today, soon = date.today(), (date.today() + timedelta(days=7)).isoformat()
    deadlines = [x for x in items if x.get("deadline") and today.isoformat() <= x["deadline"] <= soon and scores.get(x["id"], 0) >= 60]
    follow = [a for a in state.get("apps", []) if a.get("stage") == "applied" and a.get("result") == "open"
              and a.get("date") and (today - date.fromisoformat(a["date"])).days >= 14]
    parts = [f"{len(strong)} new strong match{'es' if len(strong) != 1 else ''}"]
    if deadlines:
        parts.append(f"{len(deadlines)} deadline{'s' if len(deadlines) != 1 else ''} this week")
    if follow:
        parts.append(f"{len(follow)} application{'s' if len(follow) != 1 else ''} to follow up")
    payload = {"title": "Your week in Parcours", "body": ", ".join(parts) + ".", "url": "/#/", "tag": "digest"}
    sent = sum(send(rec["subscription"], payload) == "ok" for _, rec in subs)
    store.cmd("SET", DIGEST_KEY, week)
    return f"digest sent to {sent}"
