"""Poli (withpoli.com): UK jobs at licensed visa sponsors, the sponsor directory, and employees likely sponsored there.

Signs in with a Poli account (POLI_EMAIL / POLI_PASSWORD; Pro unlocks the full feed) and reads the JSON API the
Poli web app itself uses:
- Jobs: the personalised "For you" feed, which follows the preferences saved in the Poli account. Returned as offers
  by sources.poli, so they go through the usual dealbreaker and scoring pipeline. Without an account, sources.poli
  reads the signed-out visitor feed instead (10 offers per category and level).
- Companies: the whole sponsor directory (licence, size, Certificates of Sponsorship used, open jobs), in the hash
  parcours:poli:companies.
- People: employees likely sponsored by their employer, from each company that lists some and from the account's
  personalised network, in the hash parcours:poli:people. Useful for referrals and advice.
Companies and people are refreshed on every collector run (every 6 hours); parcours:poli:meta holds the run report and Poli's totals.
"""
import json
import os
import time

import requests

BASE = "https://app.withpoli.com/api/"
COMPANIES_KEY, PEOPLE_KEY, META_KEY = "parcours:poli:companies", "parcours:poli:people", "parcours:poli:meta"
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
    r = s.post(BASE + path, json=body, timeout=30) if body is not None else s.get(BASE + path, timeout=30)
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
    """The signed-in "For you" feed. The server keeps the paging position for the session."""
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


def _replace_hash(store, key, records):
    """Writes every record, then drops the ones Poli no longer lists."""
    flat = store.cmd("HKEYS", key) or []
    fresh = {str(r["id"]) for r in records}
    batch = []
    for r in records:
        batch += [str(r["id"]), json.dumps(r, ensure_ascii=False)]
        if len(batch) >= 400:
            store.cmd("HSET", key, *batch)
            batch = []
    if batch:
        store.cmd("HSET", key, *batch)
    gone = [k for k in flat if k not in fresh]
    for i in range(0, len(gone), 200):
        store.cmd("HDEL", key, *gone[i:i + 200])


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
    # A failed step keeps what was stored before rather than wiping it.
    if status["Companies"]["ok"]:
        _replace_hash(store, COMPANIES_KEY, companies)
    if status["Sponsored employees"]["ok"] and status["Network"]["ok"]:
        _replace_hash(store, PEOPLE_KEY, people)
    store.cmd("SET", META_KEY, json.dumps({"at": now, "companies": len(companies), "people": len(people),
                                           "stats": stats, "sources": status}))
    bad = [n for n, s in status.items() if not s["ok"]]
    return {"ok": not bad, "count": len(companies), **({"error": ", ".join(bad) + " failed"} if bad else {})}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, os.path.dirname(__file__))
    from collect import load_env
    for a in sys.argv[1:]:
        if a.startswith("--env="):
            load_env(a.split("=", 1)[1])
    s = session()
    print("signed in" if s else "no account", call(s, "auth/status") if s else "")
    js = jobs(s, pages=3) if s else []
    print(len(js), "jobs, e.g.", [(x["title"], x["org"]) for x in js[:3]])
    print(run(None, dry=True, force=True))
