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
            x["desc"] = _keep(_t(desc[0].get_all_text()))
        level = re.search(r"Seniority level\s+([A-Za-z -]+?)\s+Employment type", text)
        if level:
            x["type"] = (x.get("type") or "") + (" · " if x.get("type") else "") + level.group(1)
        time.sleep(1.5)
    return done, ""


ACADEMIC = {"Inria", "CNRS", "ABG", "jobs.ac.uk", "ELLIS", "Academic Positions", "ScholarshipDB", "jobRxiv", "Max Planck"}
STEALTH_SOURCES = {"ABG", "Academic Positions", "ScholarshipDB", "StepStone", "Tanitjobs"}
MAIN_SELECTORS = ['[itemprop="description"]', ".job-description", "#job-description", ".jobsearch-JobComponent-description",
                  ".description", "article", "main"]


def _html_text(h):
    h = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", str(h or ""), flags=re.I)
    h = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#39;", "'"), ("&quot;", '"'), ("&rsquo;", "'")):
        h = h.replace(a, b)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", h)).strip()


def _job_posting(page):
    """First schema.org JobPosting in the page's JSON-LD, if any."""
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                t = d.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    return d
                stack.extend(v for v in d.values() if isinstance(v, (list, dict)))
            elif isinstance(d, list):
                stack.extend(d)
    return None


def _salary(bs):
    if not isinstance(bs, dict):
        return ""
    v = bs.get("value") or {}
    lo, hi = (v.get("minValue"), v.get("maxValue")) if isinstance(v, dict) else (v, None)
    unit = v.get("unitText", "") if isinstance(v, dict) else ""
    if not lo and not hi:
        return ""
    return f"{lo or ''}{'-' + str(hi) if hi else ''} {bs.get('currency', '')} {unit.lower()}".strip()


DESC_MAX, OLD_DESC_MAX = 4000, 2500
REQ_HEAD = re.compile(r"(profil (?:du |de la )?candidat\w*|profil recherch\w*|votre profil|candidate profile|your profile|requirements|"
                      r"qualifications|what we.re looking for|who you are|you (?:have|bring)|ihr profil|anforderungen|was du mitbringst|"
                      r"comp[ée]tences (?:requises|attendues)|le candidat ou la candidate|the (?:ideal )?candidate|"
                      r"(?:we are|we.re) looking for|looking for a candidate|nous recherchons|requested profile|profile sought|"
                      r"skills and qualifications|eligibility|conditions d.admission|pr[ée]requis)", re.I)
HEAD_KEEP = DESC_MAX - 1800


def _keep(text):
    """The description to store: whole if short; else its start plus the candidate requirements, which long academic
    listings put after the topic (the degree asked for, the skills) and a plain cut would lose."""
    if len(text) <= DESC_MAX:
        return text
    m = REQ_HEAD.search(text, HEAD_KEEP)  # the requirements past the part a plain cut keeps anyway
    if not m:
        return text[:DESC_MAX]
    return text[:HEAD_KEEP].rstrip() + " … " + text[m.start():m.start() + 1750]


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
SKIP_EMAIL = re.compile(r"^(no-?reply|noreply|donotreply|privacy|dpo|gdpr|rgpd|webmaster|abuse|support|unsubscribe|newsletter)@|\.(png|jpg|gif|svg)$", re.I)
CONTACT_WORD = re.compile(r"(contact(?: person)?|supervisors?|encadrant(?:e|s)?|directeur|directrice|co-?directeur|responsable|ansprechpartner(?:in)?|betreuer(?:in)?|hiring manager|recruiter|recruteur|recruteuse|advisor|principal investigator|PI)\b", re.I)
NAME = re.compile(r"((?:Dr\.?|Prof\.?|Pr\.?|M\.|Mme|Mr\.?|Ms\.?)\s+)?([A-Z][a-zà-ÿ'-]+(?:[ -](?:[A-Z][a-zà-ÿ'-]+|[A-Z]{2,})){1,2})")


def extract_contacts(text):
    """Contacts published in an offer for applicants: emails, with the name and role written next to them."""
    out, seen = [], set()
    for m in EMAIL.finditer(text or ""):
        email = m.group(0).strip(".")
        if SKIP_EMAIL.search(email) or email.lower() in seen:
            continue
        seen.add(email.lower())
        before = text[max(0, m.start() - 140):m.start()]
        role_m = None
        for role_m in CONTACT_WORD.finditer(before):
            pass
        names = [n for n in NAME.finditer(before[role_m.end():] if role_m else before[-60:])]
        name = (names[-1].group(0).strip() if names else "")
        if name and (len(name) > 40 or re.search(r"\b(The|Le|La|Les|For|Pour|Please|Merci|Candidature|Application)\b", name)):
            name = ""
        out.append({"email": email, "name": name, "role": role_m.group(1).lower() if role_m else ""})
        if len(out) >= 3:
            break
    return out


def _apply_page(x, page):
    x["contactsChecked"] = True
    try:
        found = extract_contacts(_t(" ".join(page.css("body ::text").getall()))[:20000])
        if found:
            x["contacts"] = found
    except Exception:
        pass
    jp = _job_posting(page)
    if jp:
        text = _html_text(jp.get("description"))
        if len(text) > len(x.get("desc") or ""):
            x["desc"] = _keep(text)
        if jp.get("validThrough") and not x.get("deadline"):
            x["deadline"] = str(jp["validThrough"])[:10]
        if jp.get("datePosted") and not x.get("posted"):
            x["posted"] = str(jp["datePosted"])[:10]
        et = jp.get("employmentType")
        if et and not x.get("type"):
            x["type"] = ", ".join(et) if isinstance(et, list) else str(et)
        sal = _salary(jp.get("baseSalary"))
        if sal:
            x["salary"] = sal
        org = (jp.get("hiringOrganization") or {}).get("name") if isinstance(jp.get("hiringOrganization"), dict) else None
        if org and not x.get("org"):
            x["org"] = _t(org)
        return True
    for sel in MAIN_SELECTORS:
        el = page.css(sel)
        if el:
            text = _t(el[0].get_all_text())
            if len(text) > 400:
                if len(text) > len(x.get("desc") or ""):
                    x["desc"] = _keep(text)
                return True
    return False


def details(items, limit=60, stealth_limit=20, stealth=True, only_sources=None, budget=360):
    """Opens offer pages whose stored description is short and fills desc, deadline, salary, type.
    Stops when the time budget (seconds) runs out; the rest is picked up on later runs."""
    t0 = time.time()
    # Short descriptions, academic offers read once more for the contact they usually name at the bottom, and
    # descriptions cut at the old 2500-character limit (read again once, to get their candidate requirements).
    todo = [x for x in items if x.get("source") != "LinkedIn" and x.get("url", "").startswith("http")
            and (only_sources is None or x.get("source") in only_sources)
            and ((not x.get("detailed") and len(x.get("desc") or "") < 400) or (x.get("source") in ACADEMIC and not x.get("contactsChecked"))
                 or (len(x.get("desc") or "") == OLD_DESC_MAX and not x.get("recut")))]
    for x in todo:
        if len(x.get("desc") or "") == OLD_DESC_MAX:
            x["recut"] = True  # one more attempt only
    plain = [x for x in todo if x.get("source") not in STEALTH_SOURCES][:limit]
    hard = [x for x in todo if x.get("source") in STEALTH_SOURCES][:stealth_limit] if stealth else []
    done = failed = 0
    for x in plain:
        if time.time() - t0 > budget * 0.5:
            break
        try:
            page = Fetcher.get(x["url"], stealthy_headers=True, timeout=20, follow_redirects=True)
            if page.status == 429:
                break
            if page.status == 200 and _apply_page(x, page):
                done += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        x["detailed"] = True  # one attempt per offer
        time.sleep(1.2)
    if hard:
        from scrapling.fetchers import StealthySession
        try:
            with StealthySession(headless=True, solve_cloudflare=True, timeout=30000, disable_resources=True) as session:
                for x in hard:
                    if time.time() - t0 > budget:
                        break
                    try:
                        page = session.fetch(x["url"], network_idle=False, timeout=30000)
                        if page.status == 200 and _apply_page(x, page):
                            done += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
                    x["detailed"] = True
                    time.sleep(1.2)
        except Exception as e:
            return done, f"stealth browser: {str(e)[:80]}"
    return done, (f"{failed} pages without readable details" if failed and not done else "")


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
    if todo and limit:
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
