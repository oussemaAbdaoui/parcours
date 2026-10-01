"""Daily refresh of the Companies section (GitHub Actions, .github/workflows/companies.yml).

For the companies the app shows (applications, saved jobs, notes, and the ones with 2+ stored offers):
- Indeed ratings missing or older than 30 days are looked up again (stealth browser) into parcours:companies,
  the cache the 6-hourly collector already uses, so companies without open offers get a rating too.
- Interview stories missing or older than 14 days are queued in parcours:insights:queue; the PC collector
  fetches them (Glassdoor and Reddit block datacenter IPs).
- A summary per company (open offers, newest offer, roles, last refresh) goes to parcours:companies:meta,
  which the Companies page reads through /api/opps?set=companies.

Usage: python collector/companies.py [--dry-run] [--env=path]
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from collect import ITEMS_KEY, STATE_KEY, Store, load_env  # noqa: E402
from enrich import CACHE_DAYS, COMPANIES_KEY, _indeed_lookup, _norm  # noqa: E402
import insights  # noqa: E402

META_KEY = "parcours:companies:meta"
RATING_LIMIT, STORY_LIMIT, STORY_DAYS = 25, 8, 14


def company_list(state, offers):
    """{norm: {name, apps, saved, note, offers, newestAt, roles, mine}} like the Companies page builds it."""
    cos = {}

    def add(name, mine=True):
        n = _norm(name)
        if not n or len(n) < 2:
            return None
        c = cos.setdefault(n, {"name": name, "apps": 0, "saved": 0, "note": False, "offers": 0, "newestAt": 0,
                               "roles": [], "mine": False, "phd": True})
        c["mine"] = c["mine"] or mine
        return c

    for a in state.get("apps", []):
        c = add(a.get("org"))
        if c:
            c["apps"] += 1
            c["phd"] = c["phd"] and a.get("d") == "phd"
            if a.get("role") and a.get("result") != "withdrawn":
                c["roles"].insert(0, a["role"])
    for j in state.get("saved", []):
        c = add(j.get("company"))
        if c:
            c["saved"] += 1
            c["phd"] = False
            if j.get("title"):
                c["roles"].append(j["title"])
    for k, n in (state.get("companyNotes") or {}).items():
        if n and (n.get("text") or "").strip():
            c = add(n.get("name") or k.replace("-", " "))
            if c:
                c["note"], c["phd"] = True, False
    counts = {}
    for x in offers:
        n = _norm(x.get("org"))
        if n:
            counts[n] = counts.get(n, 0) + 1
    for x in offers:
        n = _norm(x.get("org"))
        if not n:
            continue
        if n not in cos and counts[n] >= 2:  # "Hiring most for you"
            add(x["org"], mine=False)
        if n in cos:
            c = cos[n]
            c["offers"] += 1
            c["newestAt"] = max(c["newestAt"], x.get("foundAt") or 0)
            if x.get("kind") != "phd":
                c["phd"] = False
            if x.get("title") and len(c["roles"]) < 6:
                c["roles"].append(x["title"])
    return cos


def refresh_ratings(store, cos, dry):
    now = time.time()
    keys = list(cos)
    cached = store.cmd("HMGET", COMPANIES_KEY, *keys) if keys else []
    recs, todo = {}, []
    for k, v in zip(keys, cached or []):
        rec = json.loads(v) if v else None
        if rec:
            recs[k] = rec
        if not rec or now - rec.get("at", 0) >= CACHE_DAYS * 86400:
            todo.append(k)
    # Your own companies first, then the ones hiring most.
    todo.sort(key=lambda k: (not cos[k]["mine"], -cos[k]["offers"]))
    looked, err = 0, ""
    if todo and not dry:
        from scrapling.fetchers import StealthySession
        try:
            with StealthySession(headless=True, solve_cloudflare=True, timeout=60000) as session:
                for k in todo[:RATING_LIMIT]:
                    try:
                        rec = _indeed_lookup(session, cos[k]["name"])
                    except Exception as e:  # one company failing should not stop the rest
                        print(f"  rating {cos[k]['name']}: {str(e)[:80]}")
                        continue
                    rec["at"] = now
                    recs[k] = rec
                    store.cmd("HSET", COMPANIES_KEY, k, json.dumps(rec))
                    looked += 1
                    time.sleep(1.5)
        except Exception as e:  # browser blocked or broken: keep the cache
            err = str(e)[:160]
    return recs, looked, len(todo), err


def queue_stories(store, cos, dry):
    have = {}
    for k in store.cmd("HKEYS", insights.STORE) or []:
        rec = json.loads(store.cmd("HGET", insights.STORE, k) or "{}")
        have[k] = rec.get("fetchedAt", 0)
    now_ms = time.time() * 1000
    queued, status = 0, {}
    for n, c in sorted(cos.items(), key=lambda kv: (-kv[1]["apps"], -kv[1]["saved"])):
        if not c["mine"] or c["phd"]:  # stories exist for companies, rarely for PhD labs
            continue
        role = c["roles"][0] if c["roles"] else ""
        k = insights.key(c["name"], role)
        fetched = have.get(k, 0)
        status[n] = fetched
        if now_ms - fetched < STORY_DAYS * 86400 * 1000 or queued >= STORY_LIMIT:
            continue
        if dry:
            print(f"  would queue stories: {c['name']} / {role}")
            queued += 1
            continue
        if store.cmd("SADD", insights.QUEUE + ":pending", k):
            store.cmd("LPUSH", insights.QUEUE, json.dumps({"company": c["name"], "role": role}))
            queued += 1
    return status, queued


def main():
    dry = "--dry-run" in sys.argv
    env = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--env=")), "")
    if env:
        load_env(env)
    store = Store()
    state = store.get_json(STATE_KEY) or {}
    flat = store.cmd("HGETALL", ITEMS_KEY) or []
    offers = [json.loads(flat[i + 1]) for i in range(0, len(flat), 2)]
    cos = company_list(state, offers)
    mine = sum(1 for c in cos.values() if c["mine"])
    print(f"{len(cos)} companies ({mine} yours, {len(cos) - mine} hiring most) from {len(offers)} stored offers")

    recs, looked, stale, err = refresh_ratings(store, cos, dry)
    print(f"  ratings: {looked} looked up, {stale} were missing or older than {CACHE_DAYS} days{', error: ' + err if err else ''}")
    stories, queued = queue_stories(store, cos, dry)
    print(f"  interview stories: {queued} queued for the PC collector")

    now = int(time.time() * 1000)
    summary = {}
    for n, c in cos.items():
        r = recs.get(n) or {}
        summary[n] = {"name": c["name"], "offers": c["offers"], "newestAt": c["newestAt"], "mine": c["mine"],
                      "rating": {k: r[k] for k in ("rating", "count", "source", "url") if k in r} if r.get("rating") is not None else None,
                      "ratingAt": int(r.get("at", 0) * 1000), "storiesAt": stories.get(n, 0)}
    if dry:
        for n, c in list(summary.items())[:15]:
            print(f"  {c['name'][:30]:30} offers {c['offers']:3}  rating {c['rating'] and c['rating'].get('rating')}  yours {c['mine']}")
        return
    store.cmd("SET", META_KEY, json.dumps({"at": now, "ratingsLooked": looked, "storiesQueued": queued,
                                           **({"error": err} if err else {}), "companies": summary}, ensure_ascii=False))
    print("saved")


if __name__ == "__main__":
    main()
