"""Collects new opportunities on a schedule (GitHub Actions) and saves them to Upstash for the app.

  python collector/collect.py            # run and save
  python collector/collect.py --dry-run  # run and print, without Upstash

Searches come from the app's saved searches (Opportunities page); defaults are used until you save some.
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
from boards import _search as jobspy_search  # noqa: E402  (same JobSpy code as the app's live search)
from sources import SCRAPERS, STEALTH_SCRAPERS  # noqa: E402

STATE_KEY, OPPS_KEY = "parcours:state", "parcours:opps"
MAX_ITEMS, MAX_AGE_DAYS = 600, 45
DEFAULT_SEARCHES = [
    {"search": "machine learning engineer", "c": "fr", "location": "Paris", "type": ""},
    {"search": "machine learning engineer", "c": "de", "location": "Berlin", "type": ""},
    {"search": "software engineer", "c": "tn", "location": "Tunis", "type": ""},
    {"search": "machine learning engineer", "c": "gl", "location": "Remote", "type": ""},
]
DEFAULT_KEYWORDS = ["machine learning", "NLP", "artificial intelligence", "deep learning"]
# Anything matching these counts as relevant on the academic boards, whatever the saved searches say.
TOPICS = ["machine learning", "deep learning", "artificial intelligence", "intelligence artificielle", " ai ", "nlp",
          "natural language", "language model", "llm", "computer vision", "data science", "apprentissage", "neural",
          "reinforcement learning", "traitement automatique", "speech", "robot", "data scien", " ia "]
# Words too generic to show that a job board result matches the search.
GENERIC = {"engineer", "engineering", "developer", "developpeur", "développeur", "ingenieur", "ingénieur", "senior", "junior",
           "lead", "stage", "intern", "internship", "stagiaire", "h/f", "f/h", "m/f", "m/w/d", "job", "jobs", "remote"}
# JobSpy sites per app country (Indeed does not cover Tunisia). Google Jobs returns nothing to datacenter IPs,
# so it is only offered in the app's live search.
SITES = {"fr": ["indeed", "linkedin"], "de": ["indeed", "linkedin"], "ca": ["indeed", "linkedin"],
         "ch": ["indeed", "linkedin"], "tn": ["linkedin"], "gl": ["indeed", "linkedin"]}
LABEL = {"indeed": "Indeed", "linkedin": "LinkedIn", "google": "Google Jobs", "glassdoor": "Glassdoor"}


class Store:
    def __init__(self):
        e = os.environ
        self.url = e.get("UPSTASH_REDIS_REST_URL") or e.get("KV_REST_API_URL")
        self.token = e.get("UPSTASH_REDIS_REST_TOKEN") or e.get("KV_REST_API_TOKEN")
        if not self.url or not self.token:
            sys.exit("Missing UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN (or use --dry-run).")

    def cmd(self, *args):
        r = requests.post(self.url, headers={"Authorization": "Bearer " + self.token}, json=list(args), timeout=30)
        r.raise_for_status()
        return r.json().get("result")

    def get_json(self, key):
        v = self.cmd("GET", key)
        return json.loads(v) if v else None


def relevant(item, words):
    text = f" {item['title']} {item.get('desc', '')} ".lower()
    return any(w.lower() in text for w in words) or any(t in text for t in TOPICS)


def matches_search(job, search):
    """Job boards return loose matches: keep a result only if its title has a meaningful search word
    or a known topic, or its description contains the whole search phrase."""
    title, desc = f" {job['title'].lower()} ", job.get("desc", "").lower()
    words = [w for w in re.split(r"[^\w+#/]+", search.lower()) if len(w) > 1 and w not in GENERIC]
    return any(w in title for w in words) or any(t in title for t in TOPICS) or search.lower() in desc


def run_jobspy(searches, status):
    items = []
    for s in searches:
        q = {"q": s["search"], "c": s["c"], "loc": s.get("location", ""), "type": s.get("type", "")}
        for site in SITES.get(s["c"], ["linkedin"]):
            name = LABEL[site]
            try:
                found = [j for j in jobspy_search(site, q, results=25, hours=24 * 7) if matches_search(j, s["search"])]
                st = status.setdefault(name, {"ok": True, "count": 0})
                st["count"] += len(found)
                for j in found:
                    low = j["title"].lower()
                    items.append({
                        "id": j["id"], "title": j["title"], "org": j["company"], "location": j["location"], "c": s["c"],
                        "kind": "phd" if re.search(r"\bph\.?d\b|doctora|doktorand|these\b|thèse", low) else "job",
                        "source": name, "url": j["url"], "posted": j["posted"], "deadline": "",
                        "desc": j.get("desc", ""), "type": j.get("type", ""), "query": s["search"],
                    })
            except Exception as e:  # a blocked site should not stop the others
                status.setdefault(name, {"ok": False, "count": 0})["error"] = str(e)[:160]
            time.sleep(2)
    return items


def run_scrapers(keywords, status):
    items = []
    scrapers = dict(SCRAPERS, **(STEALTH_SCRAPERS if os.environ.get("STEALTH") == "1" else {}))
    for name, fn in scrapers.items():
        try:
            found = [x for x in fn(keywords) if relevant(x, keywords)]
            status[name] = {"ok": True, "count": len(found)}
            items += found
        except Exception as e:
            status[name] = {"ok": False, "count": 0, "error": str(e)[:160]}
    return items


def merge(old_items, found, now):
    by_id = {x["id"]: x for x in old_items}
    same = {(x["title"].lower(), x.get("org", "").lower()): x["id"] for x in old_items}
    new = 0
    for x in found:
        if not x.get("url", "").startswith("http") or not x.get("title"):
            continue
        key = (x["title"].lower(), x.get("org", "").lower())
        if x["id"] not in by_id and key in same:  # same posting from another search or site
            continue
        same[key] = x["id"]
        if x["id"] in by_id:
            by_id[x["id"]].update({k: v for k, v in x.items() if v})  # refresh details, keep foundAt
        else:
            x["foundAt"] = now
            by_id[x["id"]] = x
            new += 1
    today = date.today().isoformat()
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).timestamp() * 1000)
    kept = [x for x in by_id.values() if x.get("foundAt", now) >= cutoff and not (x.get("deadline") and x["deadline"] < today)]
    kept.sort(key=lambda x: x["foundAt"], reverse=True)
    return kept[:MAX_ITEMS], new


def main():
    dry = "--dry-run" in sys.argv
    store = None if dry else Store()
    state = (store.get_json(STATE_KEY) if store else None) or {}
    searches = [s for s in state.get("searches", []) if s.get("search")] or DEFAULT_SEARCHES
    keywords = list(dict.fromkeys([s["search"] for s in searches] + DEFAULT_KEYWORDS))[:6]
    print(f"{len(searches)} searches, keywords: {keywords}")

    status, now = {}, int(time.time() * 1000)
    found = run_jobspy(searches, status) + run_scrapers(keywords, status)
    for name, st in status.items():
        print(f"  {name:12} {'ok ' if st['ok'] else 'ERR'} {st['count']:4}  {st.get('error', '')}")

    old = (store.get_json(OPPS_KEY) if store else None) or {}
    items, new = merge(old.get("items", []), found, now)
    print(f"{len(found)} found, {new} new, {len(items)} kept")
    if dry:
        for x in items[:15]:
            print(f"  [{x['kind']:5}] {x['source']:12} {x['title'][:60]:60} | {x['org'][:25]:25} | {x.get('deadline') or x.get('posted')}")
        return
    runs = ([{"at": now, "new": new, "sources": status}] + old.get("runs", []))[:10]
    store.cmd("SET", OPPS_KEY, json.dumps({"updatedAt": now, "runs": runs, "items": items}, ensure_ascii=False))
    print("saved")


if __name__ == "__main__":
    main()
