"""Extra job sources through JobSpy (MIT, github.com/speedyapply/JobSpy): Indeed, LinkedIn, Glassdoor, Google Jobs.
With ?scraper=<name>, runs one of the collector's own scrapers (collector/sources.py) live for the Search page.

Same query parameters and response shape as api/jobs.js, so the app merges both. These sites have no
official public API; JobSpy reads their public search pages, which can be rate-limited or blocked.
"""
import hmac
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from jobspy import scrape_jobs
from jobspy.model import Country

# JobSpy raises on countries missing from its list (LinkedIn returns "Tunis, Tunis Governorate, Tunisia"),
# which fails the whole search. Fall back to "worldwide" instead; city and region are kept.
_from_string = Country.from_string.__func__


def _safe_from_string(cls, country_str):
    try:
        return _from_string(cls, country_str)
    except ValueError:
        return cls.WORLDWIDE


Country.from_string = classmethod(_safe_from_string)

SITES = {"indeed": "indeed", "linkedin": "linkedin", "glassdoor": "glassdoor", "google": "google",
         "zip_recruiter": "zip_recruiter", "bayt": "bayt"}
# Indeed and Glassdoor need a country; Tunisia is not one of theirs.
COUNTRY = {"fr": "france", "de": "germany", "ca": "canada", "ch": "switzerland", "gl": "usa"}
COUNTRY_NAME = {"fr": "France", "de": "Germany", "ca": "Canada", "ch": "Switzerland", "tn": "Tunisia"}
JOB_TYPES = {"fulltime", "parttime", "internship", "contract"}
REMOTE = re.compile(r"remote|télétravail|teletravail|homeoffice|home office", re.I)


# Collector scrapers the Search page can run live: plain HTTP ones only (the browser-based and home-IP ones cannot run here).
LIVE_SCRAPERS = {"HelloWork", "jobs.ch", "Job Bank", "Keejob", "Farojob", "jobs.ac.uk", "CNRS", "Inria", "Max Planck", "ELLIS",
                 "jobRxiv", "Himalayas", "Jobicy", "Working Nomads", "We Work Remotely", "LinkedIn posts", "Company boards",
                 "HN Who is hiring", "Free-Work", "Berlin Startup Jobs", "Remote First Jobs", "ETH Zurich", "academics.de"}
STOP = {"and", "or", "the", "of", "in", "for", "de", "des", "du", "la", "le", "les", "et", "en", "a", "an", "job", "jobs", "offre", "poste"}


def _light_fetcher():
    """On Vercel the full scraping stack (two browser engines) is over the 500 MB limit, so the collector's scrapers get
    this stand-in: the same Fetcher.get / Fetcher.post, built on requests and Scrapling's own HTML parser."""
    import sys
    import types
    if os.environ.get("LIGHT_FETCHER") != "1":
        try:
            import playwright  # noqa: F401  full Scrapling is installed (PC collector): use it
            return
        except ImportError:
            pass
    import requests
    from scrapling.parser import Selector
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36",
               "Accept-Language": "en,fr;q=0.9,de;q=0.8"}

    class Page(Selector):
        def __init__(self, r):
            super().__init__(content=r.content, url=r.url, encoding=r.encoding or "utf-8")
            self.status, self._r = r.status_code, r

        def json(self):
            return self._r.json()

    class Fetcher:
        @staticmethod
        def get(url, stealthy_headers=True, timeout=30, **kw):
            return Page(requests.get(url, headers=headers, timeout=timeout))

        @staticmethod
        def post(url, json=None, data=None, stealthy_headers=True, timeout=30, **kw):
            return Page(requests.post(url, json=json, data=data, headers=headers, timeout=timeout))

    mod = types.ModuleType("scrapling.fetchers")
    mod.Fetcher = Fetcher
    sys.modules["scrapling.fetchers"] = mod


def _live_scraper(name, q):
    """Runs one collector scraper with the query and keeps what matches it (all the words, in the title or text)."""
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(here, "..", "collector"), os.path.join(os.getcwd(), "collector")):
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)
    _light_fetcher()
    import sources
    sources.UA_PAUSE = 0.3  # one person's search, not a crawl
    if name == "LinkedIn posts":
        os.environ["POSTS_ANY_HOUR"] = "1"
        sources.POST_COUNTRIES = [q["c"]] if q["c"] in sources.POST_PLACES else list(sources.POST_PLACES)
        sources.POST_QUERIES = [q["q"]]
    fn = sources.SCRAPERS[name]
    words = [w for w in re.split(r"[^\w+#]+", q["q"].lower()) if len(w) > 1 and w not in STOP]
    out = []
    for x in fn([q["q"]]):
        text = (x.get("title", "") + " " + x.get("desc", "")).lower()
        hit = sum(w in text for w in words)
        if words and hit < (len(words) if len(words) <= 2 else len(words) - 1):  # 3+ words: one may be missing
            continue
        if q["c"] not in ("", "any") and x.get("c") not in (q["c"], "gl", "", None):
            continue
        out.append({"id": x["id"], "title": x["title"], "company": x.get("org", ""), "location": x.get("location", ""), "posted": x.get("posted", ""),
                    "type": x.get("type", ""), "url": x.get("url", ""), "source": name, "desc": (x.get("desc") or "")[:2500], "kind": x.get("kind", "job"),
                    "deadline": x.get("deadline", ""), "c": x.get("c") or q["c"]})
    return out


def _val(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return str(v).strip()


def _search(site, q, results=20, hours=24 * 30):
    remote = q["c"] == "gl" or bool(REMOTE.search(q["loc"]))
    if site in ("indeed", "glassdoor") and q["c"] not in COUNTRY:
        raise ValueError("Not available for this country")
    if site == "zip_recruiter" and q["c"] not in ("ca", "gl"):
        raise ValueError("Only covers the USA and Canada")
    loc = "" if remote else q["loc"]
    # Glassdoor looks the location up itself and fails on "City, Country"; the others need the country.
    if loc and site != "glassdoor" and q["c"] in COUNTRY_NAME and COUNTRY_NAME[q["c"]].lower() not in loc.lower():
        loc = loc + ", " + COUNTRY_NAME[q["c"]]
    args = dict(
        site_name=[site], search_term=q["q"], location=loc or None, results_wanted=results, hours_old=hours,
        country_indeed=COUNTRY.get(q["c"], "usa"), is_remote=remote, linkedin_fetch_description=False,
        description_format="markdown", verbose=0,
    )
    if q["type"] in JOB_TYPES:
        args["job_type"] = q["type"]
    if site == "google":
        args["google_search_term"] = f"{q['q']} jobs" + (" remote" if remote else (f" near {loc}" if loc else ""))
    df = scrape_jobs(**args)
    out = []
    for r in df.to_dict("records"):
        url = _val(r.get("job_url_direct")) or _val(r.get("job_url"))
        title = _val(r.get("title"))
        if not url.startswith("http") or not title:
            continue
        where = _val(r.get("location")) or ", ".join(x for x in (_val(r.get("city")), _val(r.get("state")), _val(r.get("country"))) if x)
        out.append({
            "id": f"{site}:{_val(r.get('id')) or url}", "title": title, "company": _val(r.get("company")),
            "location": where + (" (remote)" if r.get("is_remote") is True else ""),
            "posted": _val(r.get("date_posted"))[:10], "type": _val(r.get("job_type")).replace("_", "-"),
            "url": url, "source": site, "desc": _val(r.get("description"))[:2500],
        })
    return out


class handler(BaseHTTPRequestHandler):
    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _redis(self, *args):
        url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
        tok = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
        if not url or not tok:
            return None
        try:
            import requests
            return requests.post(url, headers={"Authorization": "Bearer " + tok}, json=list(args), timeout=5).json().get("result")
        except Exception:
            return None

    def do_GET(self):
        pw = os.environ.get("APP_PASSWORD", "")
        if not pw:
            return self._send(503, {"error": "APP_PASSWORD is not set on the server. Add it in Vercel, then redeploy."})
        # Same lockout as api/_lib.js: 10 wrong passwords in 15 minutes from one address.
        ip = (self.headers.get("x-forwarded-for") or self.headers.get("x-real-ip") or "unknown").split(",")[0].strip()
        key = "parcours:authfail:" + ip
        n = self._redis("GET", key)
        if n is not None and int(n) >= 10:
            return self._send(429, {"error": "Too many wrong passwords from this connection. Try again in 15 minutes."})
        if not hmac.compare_digest(self.headers.get("x-app-password", "").encode(), pw.encode()):
            self._redis("INCR", key)
            self._redis("EXPIRE", key, "900", "NX")
            return self._send(401, {"error": "Wrong or missing password."})

        p = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        q = {"q": p.get("q", "").strip()[:100], "c": p.get("c", "fr"), "loc": p.get("loc", "").strip()[:80], "type": p.get("type", "")}
        if not q["q"]:
            return self._send(400, {"error": "Add keywords."})
        if p.get("scraper"):
            name = p["scraper"]
            if name not in LIVE_SCRAPERS:
                return self._send(400, {"error": "Unknown source."})
            try:
                jobs = _live_scraper(name, q)
                return self._send(200, {"jobs": [dict(j, sources=[name]) for j in jobs], "sources": {name: {"ok": True, "count": len(jobs)}}})
            except Exception as e:
                return self._send(200, {"jobs": [], "sources": {name: {"ok": False, "error": (str(e) or e.__class__.__name__)[:160]}}})
        ids = [s for s in p.get("sources", "").split(",") if s in SITES] or list(SITES)

        status, merged = {}, {}
        with ThreadPoolExecutor(max_workers=len(ids)) as pool:
            futures = {s: pool.submit(_search, s, q) for s in ids}
            for s, f in futures.items():
                try:
                    jobs = f.result(timeout=50)
                    status[s] = {"ok": True, "count": len(jobs)}
                    for j in jobs:
                        key = re.sub(r"\s+", " ", (j["title"] + "|" + j["company"]).lower())
                        if key in merged:
                            if s not in merged[key]["sources"]:
                                merged[key]["sources"].append(s)
                        else:
                            merged[key] = dict(j, c=q["c"], sources=[s])
                except Exception as e:  # one blocked site should not fail the others
                    msg = str(e) or e.__class__.__name__
                    if "429" in msg or "blocked" in msg.lower():
                        msg = "Temporarily blocked by the site. Try again later."
                    status[s] = {"ok": False, "error": msg[:160]}
        jobs = sorted(merged.values(), key=lambda j: j["posted"], reverse=True)
        self._send(200, {"jobs": jobs, "sources": status})
