"""Poli (withpoli.com): UK jobs at licensed visa sponsors, the sponsor directory, and employees likely sponsored there.

Signs in with a Poli account (POLI_EMAIL / POLI_PASSWORD; Pro unlocks the full feed) and reads the JSON API the
Poli web app itself uses:
- Jobs: the personalised "For you" feed, which follows the preferences saved in the Poli account. Returned as offers
  by sources.poli, so they go through the usual dealbreaker and scoring pipeline. Without an account, sources.poli
  reads the signed-out visitor feed instead (10 offers per category and level).
- Companies: the whole sponsor directory (licence, size, Certificates of Sponsorship used, open jobs), in the
  Postgres table poli_companies.
- People: employees likely sponsored by their employer, from each company that lists some and from the account's
  personalised network, in poli_people. Useful for referrals and advice.
Companies and people are refreshed on every collector run (every 6 hours); parcours:poli:meta holds the run report and Poli's totals.
"""
import json
import os
import time

import requests

BASE = "https://app.withpoli.com/api/"
META_KEY = "parcours:poli:meta"  # run report and Poli's totals (Redis); the data is in Postgres (collector/pg.py)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"}
PAUSE = 0.6  # seconds between requests
JOB_PAGES, NETWORK_PAGES = 30, 30  # 10 per page

_session = None


def session():
    """Signed-in requests session, or None when no account is configured. Signs in once per run."""
    global _session
    if _session is None:
        email, password = os.environ.get("POLI_EMAIL"), os.environ.get("POLI_PASSWORD")
        if not email or not password:
            return None
        s = requests.Session()
        s.headers.update(UA)
        r = s.post(BASE + "auth/sign-in", json={"emailAddress": email, "password": password}, timeout=30)
        err = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("error")
        if r.status_code != 200 or err:
            raise RuntimeError(f"Poli sign-in failed: {(err or {}).get('message') or r.status_code}")
        _session = s
    return _session


def call(s, path, body=None):
    """GET (no body) or POST to the Poli API; returns its data field."""
    # Poli's network endpoint sometimes takes over 30 s: one retry with a longer wait before the step counts as failed.
    for wait in (30, 90):
        try:
            r = s.post(BASE + path, json=body, timeout=wait) if body is not None else s.get(BASE + path, timeout=wait)
            break
        except requests.exceptions.Timeout:
            if wait == 90:
                raise
            time.sleep(5)
    time.sleep(PAUSE)
    j = r.json()
    if r.status_code != 200 or j.get("error"):
        raise RuntimeError(f"Poli {path}: {(j.get('error') or {}).get('message') or r.status_code}")
    return j.get("data")


def _t(s):
    return " ".join(str(s or "").split())


def unmangle(s):
    """Poli stores some text double-encoded ('Â£28,392', 'â€“'): undo it when that is what happened."""
    s = _t(s)
    try:
        return s.encode("cp1252").decode("utf8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def offer(j):
    """A Poli job -> the collector's offer format."""
    co = j.get("company") or {}
    status = ((j.get("sponsorship_status") or {}).get("name") or "").replace("_", " ")
    bits = [f"Visa sponsorship: {status}" if status else "", unmangle(j.get("salary")),
            (j.get("seniority") or {}).get("display_name", ""), "Licensed UK sponsor" if co.get("licensed_sponsor") else "",
            "Suitable for Graduate visa holders" if j.get("suitable_for_graduates") else "",
            "Relocation support" if j.get("relocation_support_available") else "",
            "Salary below the visa minimum" if j.get("below_gov_min_salary_threshold") else ""]
    bits += [unmangle(m.get("text")) for m in j.get("sponsorship_mentions") or []]
    loc = j.get("location") or "Other"
    return {
        "id": "poli:" + str(j["id"]), "title": unmangle(j.get("title")), "org": unmangle(co.get("trading_name")),
        "location": "Remote / UK" if "Other" in loc else loc + ", UK", "c": "gl", "kind": "job",
        "source": "Poli", "url": j["url"], "posted": str(j.get("created_at") or "")[:10], "deadline": "",
        "type": (j.get("type") or {}).get("display_name", ""), "desc": " · ".join(b for b in bits if b)[:600],
        "poli": {"companyId": co.get("id"), "sponsorship": status, "graduates": bool(j.get("suitable_for_graduates")),
                 "relocation": bool(j.get("relocation_support_available")), "cos2025": co.get("cos_used_count_2025"),
                 "sponsoredEmployees": co.get("sponsored_employees_count") or 0},
    }


def jobs(s, pages=JOB_PAGES):
    """The signed-in "For you" feed. The server keeps the paging position for the session. It only shows jobs matching
    the preferences saved in the Poli account (99 for Software Engineering, of Poli's 19,500), so all_jobs() adds
    the visitor feed, asked for in narrow slices."""
    out, seen = [], set()
    for i in range(pages):
        data = call(s, "jobs/", {"initialFetch": i == 0})
        for j in data.get("jobs") or []:
            if j.get("id") not in seen and j.get("active", True) and j.get("url"):
                seen.add(j["id"])
                out.append(offer(j))
        if not data.get("moreJobsExist"):
            break
    return out


# The visitor feed returns 10 jobs per set of preferences and no further page, so it is asked once per category,
# seniority, location and sponsorship need: 144 requests, about 300 jobs (3 times the signed-in feed).
# Ids from app.withpoli.com/api/jobs/{categories,seniorities,locations}.
CATEGORIES = (6, 8, 3)  # Engineering (Software), Data, Research (Technical)
SENIORITIES = (1, 2, 3, 5)  # Entry-level, Junior, Mid-level, Unclear (Senior left out)
LOCATIONS = (1, 2, 3, 4, 5, 6)  # London, Scotland, Wales, Northern Ireland, Rest of UK, Other (remote)


def visitor_jobs():
    import itertools
    out, failed = {}, 0
    for cat, sen, loc, spon in itertools.product(CATEGORIES, SENIORITIES, LOCATIONS, (True, False)):
        prefs = {"jobTypes": [1, 3], "jobCategories": [cat], "jobSeniorities": [sen], "jobLocations": [loc],
                 "immediateSponsorshipRequired": spon}
        try:
            r = requests.post(BASE + "jobs", json={"initialFetch": True, "visitorPreferences": prefs}, headers=UA, timeout=30)
            r.raise_for_status()
            for j in (r.json().get("data") or {}).get("jobs") or []:
                if j.get("active", True) and j.get("url"):
                    out[j["id"]] = j
        except (requests.RequestException, ValueError):
            failed += 1
        time.sleep(0.3)
    if failed > 20:
        raise RuntimeError(f"Poli visitor feed: {failed} of 144 requests failed")
    return [offer(j) for j in out.values()]


_all = None


def all_jobs():
    """The signed-in feed (when there is an account) and the visitor slices, once per run (the offers source and the
    jobs archive both use it)."""
    global _all
    if _all is None:
        s = session()
        mine = jobs(s) if s else []
        _all = list({x["id"]: x for x in visitor_jobs() + mine}.values())
    return _all


def company(c):
    return {
        "id": c["id"], "name": unmangle(c.get("trading_name")), "legalName": c.get("companies_house_name") or "",
        "url": c.get("url") or "", "linkedin": c.get("url_linkedin") or "", "logo": c.get("url_favicon") or "",
        "licensed": bool(c.get("licensed_sponsor")), "policy": unmangle(c.get("policy")),
        "openToSponsorship": c.get("open_to_sponsorship"), "size": c.get("estimated_num_employees_label") or "",
        "jobs": c.get("active_jobs_count") or 0, "sponsoredEmployees": c.get("sponsored_employees_count") or 0,
        "cos2025": c.get("cos_used_count_2025"), "onRegisterSince": str(c.get("added_to_register") or "")[:10],
        "about": unmangle(c.get("description"))[:300], "favourite": bool(c.get("is_favourited")),
    }


def person(p, company_id=None, company_name=""):
    """An employee from a company's list (camelCase) or from the network (snake_case) -> one format."""
    co = p.get("company") or {}
    st = p.get("sponsorship_status") or {}
    return {
        "id": p["id"], "name": p.get("name") or p.get("full_name") or "", "title": p.get("jobTitle") or p.get("job_title") or "",
        "linkedin": p.get("linkedInUrl") or p.get("url_linkedin") or "", "avatar": p.get("avatarUrl") or p.get("avatar_url") or "",
        "companyId": co.get("id") or company_id, "company": co.get("trading_name") or company_name,
        "sponsorship": p.get("sponsorshipStatus") or st.get("display_name") or "",
        "experience": p.get("experience_tag") or "", "expertise": p.get("expertise_tag") or "",
        "contacted": bool(p.get("isContacted")),
    }


def collect():
    """Everything except jobs: stats, the sponsor directory and people. Returns (companies, people, stats, status)."""
    s = session()
    status, companies, people, stats = {}, [], {}, {}

    def step(name, fn):
        try:
            fn()
            status[name] = {"ok": True, "count": len(companies) if name == "Companies" else len(people) if name != "Stats" else len(stats)}
        except Exception as e:
            status[name] = {"ok": False, "count": 0, "error": str(e)[:160]}

    def get_stats():
        for k in ("sponsored-jobs", "visa-sponsors", "sponsored-employees", "employees"):
            stats[k] = call(s, "stats/" + k)

    def get_companies():
        companies.extend(company(c) for c in call(s, "companies", {}).get("companies") or [])

    def get_company_people():
        for c in companies:
            if not c["sponsoredEmployees"]:
                continue
            offset = 0
            while True:
                data = call(s, "company/employees", {"companyId": c["id"], "offset": offset})
                batch = data.get("employees") or []
                for p in batch:
                    people[p["id"]] = person(p, c["id"], c["name"])
                offset += len(batch)
                if not data.get("hasMore") or not batch:
                    break

    def get_network():
        for i in range(NETWORK_PAGES):
            data = call(s, "employees/network", {"initialFetch": i == 0})
            for p in data.get("employees") or []:
                people[p["id"]] = {**people.get(p["id"], {}), **{k: v for k, v in person(p).items() if v not in ("", None)}, "network": True}
            if not data.get("moreEmployeesExist"):
                break

    step("Stats", get_stats)
    step("Companies", get_companies)
    step("Sponsored employees", get_company_people)
    step("Network", get_network)
    return companies, list(people.values()), stats, status


def run(store, dry=False, force=False):
    """Refreshes companies and people, at most every 5 hours (so on each 6-hourly run). Returns a status line for the run report."""
    if not os.environ.get("POLI_EMAIL"):
        return {"ok": True, "count": 0, "error": "no Poli account (POLI_EMAIL / POLI_PASSWORD)"}
    now = int(time.time() * 1000)
    meta = (store.get_json(META_KEY) if store else None) or {}
    if not force and now - meta.get("at", 0) < 5 * 3600 * 1000:
        return {"ok": True, "count": meta.get("companies", 0), "error": "fresh, refreshed on the next run"}
    companies, people, stats, status = collect()
    for name, st in status.items():
        print(f"  Poli {name:20} {'ok ' if st['ok'] else 'ERR'} {st['count']:5}  {st.get('error', '')}")
    if dry or not store:
        for c in sorted(companies, key=lambda c: -c["jobs"])[:8]:
            print(f"  {c['name'][:30]:30} jobs {c['jobs']:4}  sponsored staff {c['sponsoredEmployees']:3}  CoS 2025 {c['cos2025']}")
        for p in people[:5]:
            print(f"  {p['name'][:25]:25} {p['title'][:35]:35} @ {p['company'][:20]}")
        return {"ok": all(s["ok"] for s in status.values()), "count": len(companies)}
    # Merged into Postgres, never replaced (pg.merge): the Pro account ends, and a free account sees less (fewer
    # people, hidden fields), so a record Poli no longer shows, and any field it now returns empty, keeps what was stored.
    import pg
    pg.poli_companies(companies, now)
    pg.poli_people(people, now)
    try:  # the jobs feed too, kept in its own table (the offer store ages offers out after 45 days)
        pg.poli_jobs(all_jobs(), now)
    except Exception as e:
        status["Jobs archive"] = {"ok": False, "count": 0, "error": str(e)[:160]}
    store.cmd("SET", META_KEY, json.dumps({"at": now, "companies": len(companies), "people": len(people),
                                           "stats": stats, "sources": status}))
    bad = [n for n, s in status.items() if not s["ok"]]
    return {"ok": not bad, "count": len(companies), **({"error": ", ".join(bad) + " failed"} if bad else {})}


def _flat(r):
    """One CSV row: scalars as they are, nested values as JSON."""
    return {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in r.items()}


def _write(out, name, rows):
    """rows -> out/raw/name.json (every field Poli returned) and out/name.csv (one row per record)."""
    import csv
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    with open(os.path.join(out, "raw", name + ".json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows):
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with open(os.path.join(out, name + ".csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(_flat(r) for r in rows)
    print(f"  {name}: {len(rows)}", flush=True)


def export(out, max_job_pages=2500):
    """The full Poli data as datasets, before the Pro account ends: the raw records of every endpoint the collector
    uses (not the trimmed copies kept in Redis), and the whole jobs feed instead of its first 30 pages.
    Jobs are written every 100 pages, so a run cut short still leaves what it read."""
    s = session()
    if not s:
        raise SystemExit("no Poli account (POLI_EMAIL / POLI_PASSWORD)")
    report = {"at": int(time.time() * 1000)}
    _write(out, "stats", {k: call(s, "stats/" + k) for k in ("sponsored-jobs", "visa-sponsors", "sponsored-employees", "employees")})
    companies = call(s, "companies", {}).get("companies") or []
    _write(out, "companies", companies)
    employees = []
    for c in companies:
        if not c.get("sponsored_employees_count"):
            continue
        offset = 0
        while True:
            data = call(s, "company/employees", {"companyId": c["id"], "offset": offset})
            batch = data.get("employees") or []
            employees += [{**p, "_companyId": c["id"], "_company": c.get("trading_name")} for p in batch]
            offset += len(batch)
            if not data.get("hasMore") or not batch:
                break
    _write(out, "company_employees", employees)
    network, i = {}, 0
    while i < 3000:  # 10 a page; Poli counts about 20,000 employees
        data = call(s, "employees/network", {"initialFetch": i == 0})
        for p in data.get("employees") or []:
            network[p["id"]] = p
        i += 1
        if not data.get("moreEmployeesExist"):
            break
    _write(out, "network", list(network.values()))
    jobs_raw, empty = {}, 0
    for i in range(max_job_pages):
        try:
            data = call(s, "jobs/", {"initialFetch": i == 0})
        except Exception as e:
            report["jobsError"] = f"page {i}: {e}"[:200]
            break
        new = [j for j in data.get("jobs") or [] if j.get("id") not in jobs_raw]
        jobs_raw.update((j["id"], j) for j in new)
        empty = 0 if new else empty + 1
        if (i + 1) % 100 == 0:
            _write(out, "jobs", list(jobs_raw.values()))
        if not data.get("moreJobsExist") or empty >= 5:
            break
    report["jobPages"] = i + 1
    _write(out, "jobs", list(jobs_raw.values()))
    report.update(companies=len(companies), companyEmployees=len(employees), network=len(network), jobs=len(jobs_raw))
    _write(out, "report", report)
    return report


def import_export(store, out):
    """Loads an export (out/raw/*.json) into Postgres: companies, people (sponsored employees and the whole network)
    and the jobs archive. Merged like a normal run: adds and updates, never deletes or blanks."""
    raw = lambda n: json.load(open(os.path.join(out, "raw", n + ".json"), encoding="utf-8"))
    now = int(time.time() * 1000)
    companies = [company(c) for c in raw("companies")]
    people = {p["id"]: person(p, p.get("_companyId"), p.get("_company") or "") for p in raw("company_employees")}
    for p in raw("network"):
        people[p["id"]] = {**people.get(p["id"], {}), **{k: v for k, v in person(p).items() if v not in ("", None)}, "network": True}
    jobs_ = [offer(j) for j in raw("jobs") if j.get("url")]
    import pg  # into Postgres: the 20,000 people are searched there, too many for one Redis read
    return {"companies": pg.poli_companies(companies, now), "people": pg.poli_people(list(people.values()), now),
            "jobs": pg.poli_jobs(jobs_, now)}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, os.path.dirname(__file__))
    from collect import load_env
    for a in sys.argv[1:]:
        if a.startswith("--env="):
            load_env(a.split("=", 1)[1])
        if a.startswith("--import="):
            from collect import Store
            print(import_export(Store(), a.split("=", 1)[1]))
            sys.exit(0)
        if a.startswith("--export="):
            print(export(a.split("=", 1)[1]))
            sys.exit(0)
    s = session()
    print("signed in" if s else "no account", call(s, "auth/status") if s else "")
    js = all_jobs()
    print(len(js), "jobs, e.g.", [(x["title"], x["org"]) for x in js[:3]])
    print(run(None, dry=True, force=True))
