"""Adds what the match score needs and the listings do not carry:

- LinkedIn applicant count and full description, from LinkedIn's public job page (plain HTTP).
- Company rating and review count, from Indeed's company search (stealth browser). Cached in the
  Redis hash parcours:companies for 30 days, "not found" included, so each company is looked up rarely.

Both are capped per run and stop at the first sign of blocking; a failed enrichment never fails the run.
"""
import json
import re
import time
import unicodedata

from scrapling.fetchers import Fetcher

COMPANIES_KEY = "parcours:companies"
CACHE_DAYS = 30


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\b(sas|sa|sarl|gmbh|ag|inc|ltd|llc|group|groupe|france|deutschland|tunisie|tunisia)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _t(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def linkedin_details(items, limit=40):
    """Fills applicants / applicantsCapped / desc for LinkedIn items that lack them."""
    done = 0
    for x in items:
        if done >= limit:
            break
        m = re.search(r"li-(\d+)", x.get("id", ""))
        if x.get("source") != "LinkedIn" or not m or "applicants" in x:
            continue
        page = Fetcher.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}", stealthy_headers=True, timeout=20)
        done += 1
        if page.status == 429:
            return done, "rate-limited"
        if page.status != 200:
            x["applicants"] = None
            continue
        text = _t(" ".join(page.css("::text").getall()))
        a = re.search(r"(Over\s+)?(\d[\d,.]*)\s+applicants", text, re.I)
        first = re.search(r"Be among the first (\d+) applicants", text, re.I)
        if a:
            x["applicants"] = int(re.sub(r"[,.]", "", a.group(2)))
            x["applicantsCapped"] = bool(a.group(1))
        elif first:
            x["applicants"] = max(1, int(first.group(1)) // 2)  # "among the first 25" = fewer than 25 so far
        else:
            x["applicants"] = None
        desc = page.css(".show-more-less-html__markup")
        if desc:
            x["desc"] = _t(desc[0].get_all_text())[:1500]
        level = re.search(r"Seniority level\s+([A-Za-z -]+?)\s+Employment type", text)
        if level:
            x["type"] = (x.get("type") or "") + (" · " if x.get("type") else "") + level.group(1)
        time.sleep(1.5)
    return done, ""


def _indeed_lookup(session, name):
    page = session.fetch("https://fr.indeed.com/companies/search?q=" + name.replace(" ", "+"), network_idle=True)
    if page.status != 200:
        raise RuntimeError(f"HTTP {page.status} from Indeed")
    want = _norm(name)
    for row in page.css('[data-testid="CompanyRow"]'):
        label = row.css('a[href$="/reviews"]::attr(aria-label)').get() or ""
        m = re.search(r"([\d.,]+) out of 5 stars based on ([\d,.\s]+) reviews for (.+)$", label)
        if not m:
            continue
        found = _norm(m.group(3))
        if found == want or (len(want) >= 4 and (found.startswith(want) or want.startswith(found))):
            href = row.css('a[href$="/reviews"]::attr(href)').get() or ""
            return {"rating": float(m.group(1).replace(",", ".")), "count": int(re.sub(r"\D", "", m.group(2)) or 0),
                    "source": "Indeed", "url": page.urljoin(href)}
    return {"rating": None}


def company_ratings(items, store, limit=30):
    """Attaches item['company'] = {rating, count, source, url} from cache or fresh lookups."""
    names = {}
    for x in items:
        n = _norm(x.get("org"))
        if n and len(n) >= 2 and x.get("kind") == "job":
            names.setdefault(n, x["org"])
    if not names:
        return 0, ""
    keys = list(names)
    cached = store.cmd("HMGET", COMPANIES_KEY, *keys) if store else [None] * len(keys)
    now = time.time()
    info = {}
    todo = []
    for k, v in zip(keys, cached or []):
        rec = json.loads(v) if v else None
        if rec and now - rec.get("at", 0) < CACHE_DAYS * 86400:
            info[k] = rec
        else:
            todo.append(k)
    looked, err = 0, ""
    if todo:
        from scrapling.fetchers import StealthySession
        try:
            with StealthySession(headless=True, solve_cloudflare=True, timeout=60000) as session:
                for k in todo[:limit]:
                    rec = _indeed_lookup(session, names[k])
                    rec["at"] = now
                    info[k] = rec
                    looked += 1
                    if store:
                        store.cmd("HSET", COMPANIES_KEY, k, json.dumps(rec))
                    time.sleep(1.5)
        except Exception as e:  # blocked or broken: keep what we have
            err = str(e)[:120]
    for x in items:
        rec = info.get(_norm(x.get("org")))
        if rec and rec.get("rating") is not None:
            x["company"] = {k: rec[k] for k in ("rating", "count", "source", "url") if k in rec}
    return looked, err
