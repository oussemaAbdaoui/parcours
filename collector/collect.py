"""Collects new opportunities on a schedule (GitHub Actions) and saves them to Upstash for the app.

  python collector/collect.py            # run and save (GitHub Actions)
  python collector/collect.py --dry-run  # run and print, without Upstash
  python collector/collect.py --home --env=PATH  # PC collector: home-IP-only sources (Tanitjobs)

Searches come from the app's saved searches (Opportunities page); defaults are used until you save some.
"""
import json
import os
import re
import unicodedata
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
from sources import HOME_SCRAPERS, SCRAPERS, STEALTH_SCRAPERS, is_phd  # noqa: E402

STATE_KEY, OPPS_KEY, HOME_KEY = "parcours:state", "parcours:opps", "parcours:opps:home"  # the last two: old format
# Offers live in one hash (id -> offer JSON), so every write stays small; each offer records which collector found it.
ITEMS_KEY, META_KEY = "parcours:opps:items", "parcours:opps:meta"
HOME_KEYWORDS = ["développeur", "machine learning", "data scientist", "intelligence artificielle"]
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


# Text that says an offer no longer takes applications (matched on accent-stripped lowercase text).
CLOSED = re.compile(r"(no longer accepting applications|no longer available|this job has expired|job (?:posting )?has expired|position has been filled"
                    r"|applications? (?:are |is )?(?:now )?closed|closing date has passed|offre (?:n.est plus disponible|expiree|pourvue|cloturee)"
                    r"|candidatures? (?:sont )?(?:closes?|cloturees?)|annonce (?:expiree|n.est plus)|stelle (?:ist )?(?:nicht mehr|bereits) (?:verfugbar|besetzt)"
                    r"|bewerbungsfrist (?:ist )?abgelaufen)")


def relevant(item, words):
    """Keeps an offer that names one of your searches, profile skills, CV terms or roles, or an AI topic (whole words)."""
    text = f" {item['title']} {item.get('desc', '')} ".lower()
    pattern = _word_re(tuple(sorted({w.lower() for w in words if w})))
    return bool(pattern and pattern.search(text)) or any(t in text for t in TOPICS)


_RE_CACHE = {}


def _word_re(words):
    if words not in _RE_CACHE:
        _RE_CACHE[words] = re.compile(r"(?<![a-z0-9+#])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9+#])") if words else None
    return _RE_CACHE[words]


def matches_search(job, search):
    """Job boards return loose matches: keep a result only if its title has a meaningful search word
    or a known topic, or its description contains the whole search phrase."""
    title, desc = f" {job['title'].lower()} ", job.get("desc", "").lower()
    words = [w for w in re.split(r"[^\w+#/]+", search.lower()) if len(w) > 1 and w not in GENERIC]
    return any(w in title for w in words) or any(t in title for t in TOPICS) or search.lower() in desc


def run_jobspy(searches, status):
    from boards import _search as jobspy_search  # same JobSpy code as the app's live search
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
                    items.append({
                        "id": j["id"], "title": j["title"], "org": j["company"], "location": j["location"], "c": s["c"],
                        "kind": "phd" if is_phd(j["title"]) else "job",
                        "source": name, "url": j["url"], "posted": j["posted"], "deadline": "",
                        "desc": j.get("desc", ""), "type": j.get("type", ""), "query": s["search"],
                    })
            except Exception as e:  # a blocked site should not stop the others
                status.setdefault(name, {"ok": False, "count": 0})["error"] = str(e)[:160]
            time.sleep(2)
    return items


def run_scrapers(keywords, status, scrapers=None):
    items = []
    scrapers = scrapers or dict(SCRAPERS, **(STEALTH_SCRAPERS if os.environ.get("STEALTH") == "1" else {}))
    for name, fn in scrapers.items():
        try:
            found = [x for x in fn(keywords) if relevant(x, keywords)]
            status[name] = {"ok": True, "count": len(found)}
            items += found
        except Exception as e:
            status[name] = {"ok": False, "count": 0, "error": str(e)[:160]}
    return items


def profile_terms(state):
    """Words from your profile that make an academic or remote-board offer relevant, and words that exclude one."""
    p = state.get("profile") or {}
    words = [s for s in (p.get("skills") or []) if len(s) > 2 and s not in {"git", "research", "backend", "testing", "agile", "linux"}]
    words += [e for e in (p.get("extra") or []) if len(e) > 3]
    words += [r for r in (p.get("roles") or [])]
    exclude = [w.strip().lower() for w in (p.get("exclude") or []) if w.strip()]
    return words, exclude


# Job titles to search for, by the skills in the profile (first match wins per line, strongest areas first).
PROFILE_QUERIES = [
    ({"llm", "rag", "agents", "llm evaluation", "langchain", "hugging face"}, "LLM engineer"),
    ({"machine learning", "deep learning", "pytorch", "tensorflow", "scikit-learn"}, "machine learning engineer"),
    ({"nlp", "information retrieval", "embeddings"}, "NLP engineer"),
    ({"computer vision", "ocr", "vision-language", "cnn"}, "computer vision engineer"),
    ({"data engineering", "spark", "sql"}, "data engineer"),
    ({"backend", "rest api", "fastapi", "django", "spring", "node.js"}, "backend developer"),
]
LOCATIONS = {"fr": "Paris", "de": "Berlin", "ca": "Montreal", "ch": "Zurich", "tn": "Tunis", "gl": "Remote"}


def profile_searches(state):
    """Searches built from the profile when none are saved: the two strongest areas, in the preferred countries."""
    p = state.get("profile") or {}
    skills = set(p.get("skills") or [])
    ranked = sorted(((len(skills & keys), i, q) for i, (keys, q) in enumerate(PROFILE_QUERIES) if skills & keys), key=lambda t: (-t[0], t[1]))
    queries = [q for _, _, q in ranked[:2]]
    if not queries:
        return DEFAULT_SEARCHES
    order = [c for c in (p.get("countries") or ["fr", "de", "tn", "gl"]) if c in LOCATIONS]
    countries = order[:3] + (["tn"] if "tn" in order[3:] else [])  # home market stays in even when ranked lower
    out = [{"search": q, "c": countries[0], "location": LOCATIONS[countries[0]], "type": ""} for q in queries]  # first country: both
    out += [{"search": queries[i % len(queries)], "c": c, "location": LOCATIONS[c], "type": ""} for i, c in enumerate(countries[1:])]
    return out[:5]


def excluded(item, exclude):
    text = f" {item.get('title', '')} {item.get('org', '')} ".lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text) for w in exclude)


def merge(mine, others, found, now, origin):
    """mine: stored items from this collector; others: items from the other collector (only for de-duplication)."""
    by_id = {x["id"]: x for x in mine}
    same = {(x["title"].lower(), x.get("org", "").lower()): x["id"] for x in mine + others}
    new = 0
    for x in found:
        if not x.get("url", "").startswith("http") or not x.get("title"):
            continue
        key = (x["title"].lower(), x.get("org", "").lower())
        if x["id"] not in by_id and key in same:  # same posting from another search, site or collector
            continue
        same[key] = x["id"]
        if x["id"] in by_id:
            old = by_id[x["id"]]
            for k, v in x.items():  # refresh listing fields, keep foundAt and fetched details
                if v and not (k == "desc" and len(old.get("desc") or "") > len(v)):
                    old[k] = v
        else:
            x["foundAt"], x["origin"] = now, origin
            by_id[x["id"]] = x
            new += 1
    today = date.today().isoformat()
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).timestamp() * 1000)
    kept = [x for x in by_id.values() if x.get("foundAt", now) >= cutoff and not (x.get("deadline") and x["deadline"] < today)]
    kept.sort(key=lambda x: x["foundAt"], reverse=True)
    kept = kept[:MAX_ITEMS]
    kept_ids = {x["id"] for x in kept}
    removed = [i for i in by_id if i not in kept_ids]
    return kept, new, removed


def load_env(path):
    """KEY=value lines (like Vercel's .env.local), for the PC collector."""
    for line in open(path, encoding="utf8"):
        k, sep, v = line.strip().partition("=")
        if sep and k and not k.startswith("#"):
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def load_all(store):
    """All stored offers from the hash; migrates the old one-blob keys on first use."""
    flat = store.cmd("HGETALL", ITEMS_KEY) or []
    items = [json.loads(flat[i + 1]) for i in range(0, len(flat), 2)]
    if items:
        return items
    migrated = []
    for key, origin in ((OPPS_KEY, "cloud"), (HOME_KEY, "home")):
        blob = store.get_json(key) or {}
        for x in blob.get("items", []):
            x.setdefault("origin", origin)
            migrated.append(x)
    if migrated:
        save_items(store, migrated, [])
        store.cmd("DEL", OPPS_KEY, HOME_KEY)
        print(f"migrated {len(migrated)} offers to {ITEMS_KEY}")
    return migrated


def save_items(store, items, removed):
    batch = []
    for x in items:
        batch += [x["id"], json.dumps(x, ensure_ascii=False)]
        if len(batch) >= 80:  # about 40 offers, well under request size limits
            store.cmd("HSET", ITEMS_KEY, *batch)
            batch = []
    if batch:
        store.cmd("HSET", ITEMS_KEY, *batch)
    for i in range(0, len(removed), 100):
        store.cmd("HDEL", ITEMS_KEY, *removed[i:i + 100])


def dealbreakers(items, state, scores=None):
    """{id: [reasons]} for offers that hit a dealbreaker for your profile, using the app's own score.js via Node.
    Also tags each offer with the experience it asks for (item["exp"] = {min, max, label}, e.g. "3+ yrs")."""
    import shutil
    import subprocess
    if not items:
        return {}
    node = shutil.which("node")
    if not node:
        print("  (node not found: dealbreaker filter skipped)")
        return {}
    payload = json.dumps({"profile": state.get("profile"), "targets": [s.get("search", "") for s in state.get("searches", [])],
                          "items": items}, ensure_ascii=False)
    out = subprocess.run([node, os.path.join(os.path.dirname(__file__), "dealbreakers.js")], input=payload.encode("utf8"),
                         capture_output=True, timeout=120)
    if out.returncode:
        print("  dealbreaker filter failed:", out.stderr.decode("utf8", "replace")[:200])
        return {}
    res = json.loads(out.stdout or b"{}")
    if scores is not None:
        scores.update(res.get("scores", {}))
    exp = res.get("exp", {})
    for x in items:
        if x["id"] in exp:
            x["exp"] = exp[x["id"]]
    return res.get("blocked", {})


def report_blocked(blocked, label):
    if blocked:
        why = {}
        for reasons in blocked.values():
            for r in reasons:
                why[r] = why.get(r, 0) + 1
        print(f"  {label}: {len(blocked)} dropped ({', '.join(f'{k} {v}' for k, v in sorted(why.items(), key=lambda kv: -kv[1]))})")


def main():
    dry, home = "--dry-run" in sys.argv, "--home" in sys.argv
    origin = "home" if home else "cloud"
    env = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--env=")), "")
    if env:
        load_env(env)
    store = None if dry else Store()
    state = (store.get_json(STATE_KEY) if store else None) or {}
    searches = [s for s in state.get("searches", []) if s.get("search")] or profile_searches(state)
    pwords, exclude = profile_terms(state)
    if home:
        keywords = list(dict.fromkeys([s["search"] for s in searches if s.get("c") == "tn"] + HOME_KEYWORDS))[:4]
    else:
        keywords = list(dict.fromkeys([s["search"] for s in searches] + DEFAULT_KEYWORDS))[:6]
    print(f"{origin} run, {len(searches)} searches, keywords: {keywords}, profile terms: {len(pwords)}, exclusions: {exclude}")

    status, now = {}, int(time.time() * 1000)
    if home:
        found = run_scrapers(keywords + pwords, status, HOME_SCRAPERS)
    else:
        found = run_jobspy(searches, status) + run_scrapers(keywords + pwords, status)
    seen_now = list(found)  # every offer seen this run, dealbreakers included, for the hiring log
    before = len(found)
    found = [x for x in found if not excluded(x, exclude)]
    for name, st in status.items():
        print(f"  {name:16} {'ok ' if st['ok'] else 'ERR'} {st['count']:4}  {st.get('error', '')}")
    if before != len(found):
        print(f"  excluded by your words: {before - len(found)}")
    # Offers that are dealbreakers for you (too senior, language, work permit, internship after graduation...)
    # are not stored at all.
    blocked = dealbreakers(found, state)
    report_blocked(blocked, "dealbreakers in new results")
    found = [x for x in found if x["id"] not in blocked]

    stored = load_all(store) if store else []
    mine = [x for x in stored if x.get("origin", "cloud") == origin and not excluded(x, exclude)]
    others = [x for x in stored if x.get("origin", "cloud") != origin]
    removed_excl = [x["id"] for x in stored if x.get("origin", "cloud") == origin and excluded(x, exclude)]
    items, new, removed = merge(mine, others, found, now, origin)
    print(f"{len(found)} found, {new} new, {len(items)} kept")

    from enrich import company_ratings, details, linkedin_details
    steps = [("Offer details", lambda: details(items, stealth=os.environ.get("STEALTH") == "1" or home))]
    if not home:
        steps += [("LinkedIn details", lambda: linkedin_details(items))]
    # Indeed blocks company pages from datacenter IPs: company reviews are looked up from the PC, for every
    # stored offer (cloud and home), into the shared cache the cloud runs then read.
    if home and store:
        everything = load_all(store)
        steps += [("Company reviews", lambda: company_ratings(everything, store))]
    elif not home:
        steps += [("Company reviews", lambda: company_ratings(items, store, limit=0))]
    for name, fn in steps:
        try:
            n, err = fn()
            status[name] = {"ok": not err, "count": n, **({"error": err} if err else {})}
        except Exception as e:
            status[name] = {"ok": False, "count": 0, "error": str(e)[:160]}
        print(f"  {name:16} {'ok ' if status[name]['ok'] else 'ERR'} {status[name]['count']:4}  {status[name].get('error', '')}")
    # Contacts published in offers for applicants (also for offers read on earlier runs).
    from enrich import extract_contacts
    for x in items:
        if "contacts" not in x and x.get("desc"):
            found = extract_contacts(x["desc"])
            if found:
                x["contacts"] = found
    print(f"  offers naming a contact: {sum(1 for x in items if x.get('contacts'))}")
    # Full descriptions can reveal a dealbreaker the listing hid (fluent German, EU citizens only): drop those too,
    # along with stored offers that became dealbreakers after a profile change.
    scores = {}
    late = dealbreakers(items, state, scores)
    # Offers whose page says they are closed (no longer accepting applications, offre expirée...) go too.
    for x in items:
        if x["id"] not in late and CLOSED.search(unicodedata.normalize("NFD", f"{x.get('title', '')} {x.get('desc', '')}".lower()).encode("ascii", "ignore").decode()):
            late[x["id"]] = ["Closed"]
    report_blocked(late, "dealbreakers among stored offers")
    if late:
        removed += [x["id"] for x in items if x["id"] in late]
        items = [x for x in items if x["id"] not in late]
    rich = sum(1 for x in items if len(x.get("desc") or "") >= 400)
    print(f"  full description: {rich}/{len(items)}, applicants: {sum(1 for x in items if x.get('applicants'))}, company rating: {sum(1 for x in items if x.get('company'))}")

    if not home:  # master's programmes and scholarships, in their own store, refreshed once a day
        try:
            import masters
            status["Master's"] = masters.run(store, state, dry=dry, force="--masters" in sys.argv)
        except Exception as e:
            status["Master's"] = {"ok": False, "count": 0, "error": str(e)[:160]}
        st = status["Master's"]
        print(f"  Master's         {'ok ' if st['ok'] else 'ERR'} {st['count']:4}  {st.get('error', '')}")

    if dry:
        for x in items[:15]:
            print(f"  [{x['kind']:5}] {x['source']:12} {x['title'][:60]:60} | {x['org'][:25]:25} | {len(x.get('desc') or ''):4} chars")
        return
    save_items(store, items, removed + removed_excl)
    try:  # hiring log: when each company recruits (seeded from all stored offers on first use)
        import history
        for x in seen_now:
            x.setdefault("foundAt", now)
        n = history.record(store, seen_now)
        if store.cmd("HGET", "parcours:companies:history:meta", "seeded") is None:  # once: offers stored before the log
            n += history.record(store, load_all(store), backfill=True)
            store.cmd("HSET", "parcours:companies:history:meta", "seeded", str(now))
        status["Hiring log"] = {"ok": True, "count": n}
    except Exception as e:
        status["Hiring log"] = {"ok": False, "count": 0, "error": str(e)[:160]}
    print("  hiring log:", status["Hiring log"])
    try:
        from notify import notify
        status["Notifications"] = {"ok": True, "count": 0, "error": notify(store, items, scores, now, state, origin)}
    except Exception as e:
        status["Notifications"] = {"ok": False, "count": 0, "error": str(e)[:160]}
    print("  notifications:", status["Notifications"]["error"])
    meta = store.get_json(META_KEY) or {}
    runs = meta.get("runs") if isinstance(meta.get("runs"), dict) else {}
    runs[origin] = ([{"at": now, "new": new, "sources": status}] + runs.get(origin, []))[:10]
    store.cmd("SET", META_KEY, json.dumps({"updatedAt": now, "runs": runs}))
    print("saved")


if __name__ == "__main__":
    main()
