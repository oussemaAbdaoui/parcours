"""Extra job sources through JobSpy (MIT, github.com/speedyapply/JobSpy): Indeed, LinkedIn, Glassdoor, Google Jobs.

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
            "url": url, "source": site, "desc": _val(r.get("description"))[:600],
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

    def do_GET(self):
        pw = os.environ.get("APP_PASSWORD", "")
        if not pw:
            return self._send(503, {"error": "APP_PASSWORD is not set on the server. Add it in Vercel, then redeploy."})
        if not hmac.compare_digest(self.headers.get("x-app-password", "").encode(), pw.encode()):
            return self._send(401, {"error": "Wrong or missing password."})

        p = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        q = {"q": p.get("q", "").strip()[:100], "c": p.get("c", "fr"), "loc": p.get("loc", "").strip()[:80], "type": p.get("type", "")}
        if not q["q"]:
            return self._send(400, {"error": "Add keywords."})
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
