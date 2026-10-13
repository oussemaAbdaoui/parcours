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

# Offers live in one hash (id -> offer JSON), so every write stays small; each offer records which collector found it.
META_KEY = "parcours:opps:meta"  # run reports (Redis); the offers themselves are in Postgres
HOME_KEYWORDS = ["développeur", "machine learning", "data scientist", "intelligence artificielle"]
# Stored offers per collector: the app downloads them all (Vercel answers up to 4.5 MB), so cloud + home stay near 1200.
MAX_ITEMS, MAX_ITEMS_HOME, MAX_AGE_DAYS = 900, 300, 45
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
         "ch": ["indeed", "linkedin"], "tn": ["linkedin"], "gl": ["indeed", "linkedin"], "be": ["indeed", "linkedin"],
         "nl": ["indeed", "linkedin"], "lu": ["indeed", "linkedin"], "se": ["indeed", "linkedin"], "dk": ["indeed", "linkedin"],
         "fi": ["indeed", "linkedin"], "no": ["indeed", "linkedin"], "ma": ["indeed", "linkedin"],
         "ie": ["indeed", "linkedin"], "uk": ["indeed", "linkedin"]}
LABEL = {"indeed": "Indeed", "linkedin": "LinkedIn", "google": "Google Jobs", "glassdoor": "Glassdoor"}


class Store:
    def __init__(self):
        e = os.environ
        self.url = e.get("UPSTASH_REDIS_REST_URL") or e.get("KV_REST_API_URL")
        self.token = e.get("UPSTASH_REDIS_REST_TOKEN") or e.get("KV_REST_API_TOKEN")
        if not self.url or not self.token:
            sys.exit("Missing UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN (or use --dry-run).")

    def cmd(self, *args):
        # The home connection drops now and then (DNS failures): retry for about 5 minutes before giving up,
        # so a long scraping run is not lost at the save.
        for attempt in range(8):
            try:
                r = requests.post(self.url, headers={"Authorization": "Bearer " + self.token}, json=list(args), timeout=30)
                break
            except requests.ConnectionError:
                if attempt == 7:
                    raise
                time.sleep(min(10 * 2 ** attempt, 60))
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
    # Short words ("IA", "AI") count only as whole words, or "ia" would match "media" and "social".
    hit = lambda w: (_word_re((w,)).search(title) is not None) if len(w) <= 3 else w in title
    return any(hit(w) for w in words) or any(t in title for t in TOPICS) or search.lower() in desc


def run_jobspy(searches, status):
    from boards import COUNTRY_NAME, REMOTE, _search as jobspy_search  # same JobSpy code as the app's live search
    items = []
    for s in searches:
        q = {"q": s["search"], "c": s["c"], "loc": s.get("location", ""), "type": s.get("type", "")}
        for site in SITES.get(s["c"], ["linkedin"]):
            name = LABEL[site]
            # LinkedIn searches the whole country (a city search misses every other city) and goes deeper.
            qs = dict(q, loc=COUNTRY_NAME[s["c"]]) if site == "linkedin" and s["c"] in COUNTRY_NAME and not REMOTE.search(q["loc"]) else q
            try:
                found = [j for j in jobspy_search(site, qs, results=50 if site == "linkedin" else 25, hours=24 * 7) if matches_search(j, s["search"])]
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
LOCATIONS = {"fr": "Paris", "de": "Berlin", "ca": "Montreal", "ch": "Zurich", "tn": "Tunis", "gl": "Remote", "be": "Brussels",
             "nl": "Amsterdam", "lu": "Luxembourg", "se": "Stockholm", "dk": "Copenhagen", "fi": "Helsinki", "no": "Oslo", "ma": "Casablanca", "ie": "Dublin", "uk": "London"}
# French titles find offers the English ones miss in French-speaking markets.
FRENCH_QUERIES = {"fr": ["ingénieur IA", "développeur IA"], "tn": ["ingénieur IA", "développeur IA"], "ch": ["ingénieur IA"],
                  "be": ["ingénieur IA"], "lu": ["ingénieur IA"], "ma": ["ingénieur IA", "développeur IA"]}
AI_SKILLS = {"machine learning", "deep learning", "llm", "rag", "agents", "pytorch", "tensorflow", "nlp", "computer vision"}


def profile_searches(state):
    """Searches built from the profile when none are saved: the two strongest areas, "AI engineer" and your roles,
    in each of your countries (four per country; Tunisia, on LinkedIn only, gets them all). Remote / Global is left
    to the remote boards: JobSpy's global Indeed is the US site, whose offers the location rule drops."""
    p = state.get("profile") or {}
    skills = set(p.get("skills") or [])
    ranked = sorted(((len(skills & keys), i, q) for i, (keys, q) in enumerate(PROFILE_QUERIES) if skills & keys), key=lambda t: (-t[0], t[1]))
    queries = [q for _, _, q in ranked[:2]]
    if not queries:
        return DEFAULT_SEARCHES
    if skills & AI_SKILLS:
        queries.append("AI engineer")
    for r in p.get("roles") or []:  # "backend developer intern" searches as "backend developer"
        r = re.sub(r"\b(intern|internship|stage|stagiaire)\b", "", r, flags=re.I).strip()
        if len(r.split()) >= 2:
            queries.append(r)
    queries = list({q.lower(): q for q in reversed(queries)}.values())[::-1]  # dedupe, first spelling and order kept
    out = []
    for c in [c for c in (p.get("countries") or ["fr", "de", "tn"]) if c in LOCATIONS and c != "gl"]:
        mine = queries + FRENCH_QUERIES.get(c, []) if c == "tn" else queries[:3] + (FRENCH_QUERIES.get(c) or queries[3:])[:1]
        out += [{"search": q, "c": c, "location": LOCATIONS[c], "type": ""} for q in mine]
    return out or DEFAULT_SEARCHES


def excluded(item, exclude):
    text = f" {item.get('title', '')} {item.get('org', '')} ".lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text) for w in exclude)


def _dup_keys(x):
    """Keys that identify one posting across sites: title and org, and a long title alone, since aggregators
    (jobRxiv's "Jobfront Academia") repost PhDs under their own name. Short titles ("Software Engineer") need the org."""
    plain = lambda s: re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFD", (s or "").lower()).encode("ascii", "ignore").decode()).strip()
    from enrich import _norm  # the company key everything else uses: "Odido Nederland" and "Telavox AB" are Odido, Telavox
    title = plain(x.get("title"))
    keys = [(title, _norm(x.get("org")))]
    if len(title.split()) >= 6:
        keys.append((title, ""))
    return keys


def merge(mine, others, found, now, origin):
    """mine: stored items from this collector; others: items from the other collector (only for de-duplication)."""
    by_id = {x["id"]: x for x in mine}
    same = {k: x["id"] for x in mine + others for k in _dup_keys(x)}
    new = 0
    for x in found:
        if not x.get("url", "").startswith("http") or not x.get("title"):
            continue
        keys = _dup_keys(x)
        if x["id"] not in by_id and any(k in same for k in keys):  # same posting from another search, site or collector
            continue
        for k in keys:
            same[k] = x["id"]
        if x["id"] in by_id:
            old = by_id[x["id"]]
            for k, v in x.items():  # refresh listing fields, keep foundAt and fetched details
                if v and not (k == "desc" and len(old.get("desc") or "") > len(v)):
                    old[k] = v
        else:
            x["foundAt"], x["origin"] = now, origin
            by_id[x["id"]] = x
            new += 1
    # Copies stored twice before company names were compared normalised ("Odido" and "Odido Nederland"): the one
    # with the longer text stays.
    first, twice = {}, set()
    for x in sorted(by_id.values(), key=lambda x: -len(x.get("desc") or "")):
        k = _dup_keys(x)[0]
        if k[1] and k in first:
            twice.add(x["id"])
        first.setdefault(k, x["id"])
    today = date.today().isoformat()
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).timestamp() * 1000)
    kept = [x for x in by_id.values() if x.get("foundAt", now) >= cutoff and not (x.get("deadline") and x["deadline"] < today)
            and x["id"] not in twice]
    kept.sort(key=lambda x: x["foundAt"], reverse=True)  # the store cap applies later, by score (keep_best)
    kept_ids = {x["id"] for x in kept}
    removed = [i for i in by_id if i not in kept_ids]
    return kept, new, removed


BACKUP_DIR, BACKUP_DAYS = os.path.join(os.path.expanduser("~"), "parcours-collector", "backups"), 30


def backup_state(state):
    """A dated copy of your synced data on the PC, once a day, the last 30 kept. The data was wiped once and came
    back only because another device still had it."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"state-{date.today().isoformat()}.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf8") as f:
            json.dump(state, f, ensure_ascii=False)
    old = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("state-") and f.endswith(".json"))[:-BACKUP_DAYS]
    for f in old:
        os.remove(os.path.join(BACKUP_DIR, f))


def load_env(path):
    """KEY=value lines (like Vercel's .env.local), for the PC collector."""
    for line in open(path, encoding="utf8"):
        k, sep, v = line.strip().partition("=")
        if sep and k and not k.startswith("#"):
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def load_state(store=None):
    """Your profile, searches and lists, read from Postgres (the app saves them there through api/state.js)."""
    import pg
    return pg.state() if pg.conn() else {}


def load_all(store=None):
    """All stored offers (Postgres table offers)."""
    import pg
    return pg.offers_all()


ENRICHED = ("desc", "req", "applicants", "applicantsCapped", "applicantsAt", "contacts")
COUNT = ("applicants", "applicantsCapped", "applicantsAt")


def keep_enriched(store, items):
    """A run holds the offers as they were when it started (30-50 min for the cloud run); meanwhile the other
    collector may have filled their descriptions (the PC fills the cloud's LinkedIn offers). Before saving, each
    offer takes the stored copy's description, reading and applicant count when those are richer than its own,
    so a run never writes an older, emptier copy over a newer one."""
    import pg
    for i in range(0, len(items), 300):
        chunk = items[i:i + 300]
        stored = pg.offers_get([x["id"] for x in chunk])
        for x in chunk:
            s = stored.get(x["id"])
            if not s:
                continue
            mine = {k: x[k] for k in COUNT if k in x} if x.get("applicantsAt", 0) > s.get("applicantsAt", 0) else None
            if len(s.get("desc") or "") > len(x.get("desc") or ""):
                for k in ENRICHED:
                    if k in s:
                        x[k] = s[k]
                    else:
                        x.pop(k, None)
            elif "applicants" in s and "applicants" not in x:
                x["applicants"] = s["applicants"]
            if mine:  # this run counted the applicants more recently: its count wins
                x.update(mine)


def save_items(store, items, removed):
    """Writes the run's offers to Postgres (table offers) and deletes the removed ones."""
    import pg
    keep_enriched(store, items)
    pg.offers_save(items, removed, int(time.time() * 1000))


def linkedin_home(everything, store, origin, limit=150):
    """The cloud run's LinkedIn offers mostly come without a description (LinkedIn refuses GitHub's IPs). The PC
    fills them, has their requirements read again from the full text, and saves just those offers; the cloud
    run's dealbreaker check then drops the ones that do not fit."""
    from enrich import linkedin_details
    import requirements
    todo = [x for x in everything if x.get("origin", "cloud") != origin and x.get("source") == "LinkedIn"
            and len(x.get("desc") or "") < 400 and "applicants" not in x]
    before = {x["id"]: x.get("desc") for x in todo}
    n, err = linkedin_details(todo, limit=limit, stealth=True)
    filled = [x for x in todo if x.get("desc") != before[x["id"]] or "applicants" in x]
    if filled:
        requirements.extract([x for x in filled if "req" not in x])
        save_items(store, filled, [])
    print(f"  LinkedIn descriptions: {sum(1 for x in filled if len(x.get('desc') or '') >= 400)} filled, {len(todo) - n} left")
    return n, err


PROXY_KEY = "parcours:proxy:bytes:"  # + YYYY-MM: bytes sent through the paid proxy this month


def linkedin_cloud(items, store):
    """LinkedIn descriptions in the cloud run. Without a proxy LinkedIn refuses GitHub's IPs after a few pages;
    with PROXY_URL (rotating residential, paid by the GB) it reads them all, up to PROXY_MB_MONTH a month."""
    from enrich import linkedin_details
    proxy = os.environ.get("PROXY_URL")
    if not proxy or not store:
        return linkedin_details(items)
    key = PROXY_KEY + time.strftime("%Y-%m")
    spent = int(store.cmd("GET", key) or 0)
    left_month = int(os.environ.get("PROXY_MB_MONTH") or 800) * 1024 * 1024 - spent
    if left_month <= 0:
        return 0, "proxy allowance used up this month"
    # Paced over the month: each run gets an even share of what is left (about 6 runs a day: cloud and PC triggers),
    # so the allowance lasts to the 1st instead of running out in the first week (20 MB a run spent 138 MB in a day).
    import calendar
    today = time.gmtime()
    days_left = calendar.monthrange(today.tm_year, today.tm_mon)[1] - today.tm_mday + 1
    meter = {"left": min(left_month, max(3 * 1024 * 1024, left_month // (days_left * 6)))}
    try:
        n, err = linkedin_details(items, limit=400, proxy=proxy, meter=meter)
    finally:
        if meter.get("used"):
            store.cmd("INCRBY", key, meter["used"])
            store.cmd("EXPIRE", key, 70 * 86400)
    print(f"  proxy: {meter.get('used', 0) / 1048576:.1f} MB this run, {(spent + meter.get('used', 0)) / 1048576:.0f} MB this month")
    return n, err


def dealbreakers(items, state, scores=None, potential=None):
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
    # UK offers carry whether the employer is on the UK sponsor register (scoring only, not stored on the offer).
    try:
        import pg
        uk = pg.uk_sponsor_flags({x.get("org") for x in items if x.get("c") == "uk"})
    except Exception as e:
        print("  UK sponsor flags:", str(e)[:120])
        uk = {}
    scored = [{**x, "ukSponsor": uk[x.get("org")]} if x.get("c") == "uk" and x.get("org") in uk else x for x in items]
    payload = json.dumps({"profile": state.get("profile"), "targets": [s.get("search", "") for s in state.get("searches", [])],
                          "items": scored}, ensure_ascii=False)
    out = subprocess.run([node, os.path.join(os.path.dirname(__file__), "dealbreakers.js")], input=payload.encode("utf8"),
                         capture_output=True, timeout=120)
    if out.returncode:
        print("  dealbreaker filter failed:", out.stderr.decode("utf8", "replace")[:200])
        return {}
    res = json.loads(out.stdout or b"{}")
    if scores is not None:
        scores.update(res.get("scores", {}))
    if potential is not None:  # unread offers: the score their listing suggests (they are capped until read)
        potential.update(res.get("potential", {}))
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
    state = load_state()
    if home and state:
        backup_state(state)
    searches = [s for s in state.get("searches", []) if s.get("search")]
    # Countries in your profile with no saved search (one just added) get the searches built from your profile.
    covered = {s.get("c") for s in searches}
    searches += [s for s in profile_searches(state) if s["c"] not in covered] if searches else profile_searches(state)
    pwords, exclude = profile_terms(state)
    if home:
        # Your Tunisia searches plus the French defaults: Tanitjobs offers are mostly in French.
        keywords = list(dict.fromkeys([s["search"] for s in searches if s.get("c") == "tn"][:4] + HOME_KEYWORDS))
    else:
        keywords = list(dict.fromkeys([s["search"] for s in searches] + DEFAULT_KEYWORDS))[:6]
    print(f"{origin} run, {len(searches)} searches, keywords: {keywords}, profile terms: {len(pwords)}, exclusions: {exclude}")

    status, now = {}, int(time.time() * 1000)
    import sources  # countries the LinkedIn posts search covers (sources.linkedin_posts)
    sources.POST_COUNTRIES = list(dict.fromkeys(s.get("c") for s in searches if s.get("c") in sources.POST_PLACES)) or list(sources.POST_PLACES)
    sources.POST_QUERIES = keywords[:2]
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
    if not home and not dry:  # UK register of licensed sponsors: downloaded weekly, companies re-marked every run
        try:
            import uk_register
            n, err = uk_register.refresh()
            status["UK sponsor register"] = {"ok": not err, "count": n, **({"error": err} if err else {})}
        except Exception as e:
            status["UK sponsor register"] = {"ok": False, "count": 0, "error": str(e)[:160]}
        try:  # French company register: staff, age, sector and closed companies, for employers with French offers
            import fr_register
            n, err = fr_register.refresh()
            status["French company register"] = {"ok": not err, "count": n, **({"error": err} if err else {})}
        except Exception as e:
            status["French company register"] = {"ok": False, "count": 0, "error": str(e)[:160]}
    blocked = dealbreakers(found, state)
    report_blocked(blocked, "dealbreakers in new results")
    found = [x for x in found if x["id"] not in blocked]
    # Offers already read and dropped under this same profile are not opened, read or scored again for 30 days.
    import hashlib
    fingerprint = hashlib.md5(json.dumps(state.get("profile") or {}, sort_keys=True).encode()).hexdigest()[:16]
    try:
        import pg
        again = pg.dropped_ids([x["id"] for x in found], fingerprint, now - 30 * 86400 * 1000) if store else set()
    except Exception as e:
        print("  dropped offers memory:", str(e)[:120])
        again = set()
    if again:
        print(f"  skipped {len(again)} offers already read and dropped under this profile, or deleted by you")
        found = [x for x in found if x["id"] not in again]

    stored = load_all(store) if store else []
    mine = [x for x in stored if x.get("origin", "cloud") == origin and not excluded(x, exclude)]
    others = [x for x in stored if x.get("origin", "cloud") != origin]
    removed_excl = [x["id"] for x in stored if x.get("origin", "cloud") == origin and excluded(x, exclude)]
    items, new, removed = merge(mine, others, found, now, origin)
    print(f"{len(found)} found, {new} new, {len(items)} kept")

    from enrich import company_ratings, details, mark_teasers
    mark_teasers(items)  # listing excerpts count as unread until their page is tried
    # Pages are opened in the order of what each listing promises (the score before the unread cap), so the offers
    # most likely to be strong are read first instead of whichever came first.
    early, early_pot = {}, {}
    dealbreakers(items, state, early, early_pot)
    priority = {i: max(v, early_pot.get(i, 0)) for i, v in early.items()}
    # The PC opens more pages in the stealth browser: Tanitjobs, Duunitori and Emploi.ma list far more than 20 a run.
    steps = [("Offer details", lambda: details(items, stealth=os.environ.get("STEALTH") == "1" or home, priority=priority,
                                               **({"stealth_limit": 40, "budget": 600} if home else {})))]
    if not home:
        steps += [("LinkedIn details", lambda: linkedin_cloud(items, store))]
    # Indeed blocks company pages from datacenter IPs: company reviews are looked up from the PC, for every
    # stored offer (cloud and home), into the shared cache the cloud runs then read.
    if home and store:
        everything = load_all(store)
        steps += [("LinkedIn details", lambda: linkedin_home(everything, store, origin))]
        steps += [("Company reviews", lambda: company_ratings(everything, store))]
    elif not home:
        steps += [("Company reviews", lambda: company_ratings(items, store, limit=0))]
    # What each offer asks of the candidate, read once by Claude once its full description is in (dealbreakers below use it).
    import requirements
    steps += [("Requirements", lambda: requirements.extract(items))]
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
    potential = {}
    late = dealbreakers(items, state, scores, potential)
    # Offers whose page says they are closed (no longer accepting applications, offre expirée...) go too.
    for x in items:
        if x["id"] not in late and CLOSED.search(unicodedata.normalize("NFD", f"{x.get('title', '')} {x.get('desc', '')}".lower()).encode("ascii", "ignore").decode()):
            late[x["id"]] = ["Closed"]
    report_blocked(late, "dealbreakers among stored offers")
    if late and store:
        try:
            import pg
            pg.dropped_save(late, fingerprint, now)
        except Exception as e:
            print("  dropped offers memory:", str(e)[:120])
    if late:
        removed += [x["id"] for x in items if x["id"] in late]
        items = [x for x in items if x["id"] not in late]
    # Over the cap, the lowest-scoring offers go, not the oldest: a good offer stays until it closes or ages out.
    cap = MAX_ITEMS_HOME if home else MAX_ITEMS
    if len(items) > cap:
        # An unread offer competes with what its listing promises, not the 65 it is capped at until read: else it is
        # dropped before any run opens its page, found again as "new" next run, and never read.
        rank = lambda x: max(scores.get(x["id"], 0), potential.get(x["id"], 0))
        items.sort(key=lambda x: (rank(x), x.get("foundAt", 0)), reverse=True)
        print(f"  store cap {cap}: {len(items) - cap} lowest-ranked offers dropped (kept down to {rank(items[cap - 1])})")
        removed += [x["id"] for x in items[cap:]]
        items = items[:cap]
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
        try:  # Poli sponsor directory and sponsored employees, in their own store, refreshed every run
            import poli
            status["Poli directory"] = poli.run(store, dry=dry, force="--poli" in sys.argv)
        except Exception as e:
            status["Poli directory"] = {"ok": False, "count": 0, "error": str(e)[:160]}
        st = status["Poli directory"]
        print(f"  Poli directory   {'ok ' if st['ok'] else 'ERR'} {st['count']:4}  {st.get('error', '')}")

    if dry:
        for x in items[:15]:
            print(f"  [{x['kind']:5}] {x['source']:12} {x['title'][:60]:60} | {x['org'][:25]:25} | {len(x.get('desc') or ''):4} chars")
        return
    save_items(store, items, removed + removed_excl)
    try:  # hiring log: when each company recruits
        import history
        for x in seen_now:
            x.setdefault("foundAt", now)
        n = history.record(store, seen_now)
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
