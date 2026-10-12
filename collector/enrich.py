"""Adds what the match score needs and the listings do not carry:

- LinkedIn applicant count and full description, from LinkedIn's public job page (plain HTTP).
- Company rating and review count, from Indeed's company search (stealth browser). Cached in the
  Postgres (companies.rating) for 30 days, "not found" included, so each company is looked up rarely.

Both are capped per run and stop at the first sign of blocking; a failed enrichment never fails the run.
"""
import json
import re
import time
import unicodedata

from scrapling.fetchers import Fetcher

CACHE_DAYS = 30


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # Legal forms and country words are dropped (same list as coNorm in index.html).
    s = re.sub(r"\b(sas|sa|sarl|gmbh|ag|inc|ltd|llc|llp|plc|limited|bv|nv|ab|oy|srl|spa|group|groupe|france|deutschland|germany|"
               r"tunisie|tunisia|maroc|morocco|nederland|netherlands|belgium|belgique|uk|sweden|sverige|danmark|denmark|suisse|"
               r"switzerland|luxembourg|canada)\b", " ", s)
    # Exact match only: a looser rule (shorter name prefixes) was tested on the Poli directory and matched wrong
    # companies 6 times in 7 ("Board Intelligence" -> "Board", "Axon Networks" -> "AXON").
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _t(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def linkedin_details(items, limit=40, stealth=False, proxy=None, meter=None):
    """Fills applicants / applicantsCapped / desc for LinkedIn items without a full description. LinkedIn
    refuses most datacenter IPs (the cloud run), not a home connection; when it rate-limits even that, the rest
    goes through Scrapling's stealth browser (stealth=True). With a rotating residential proxy every request
    comes from another home IP, so the cloud run gets through too; meter = {"left": bytes} stops it once this
    month's proxy allowance is used up (meter["used"] gets the bytes spent). A new description drops
    requirements read from the title alone, so Claude reads them again from the full text."""
    done, session, ctx, refused = 0, None, None, 0
    if proxy:  # applicant re-counts first, with up to a third of this run's proxy share (they decide dealbreakers)
        sub = {"left": meter["left"] // 3} if meter else None
        recheck_applicants(items, proxy, sub)
        if meter and sub:
            meter["used"] = meter.get("used", 0) + sub.get("used", 0)
    try:
        for x in items:
            if done >= limit or (meter and meter.get("used", 0) >= meter["left"]):
                break
            m = re.search(r"li-(\d+)", x.get("id", ""))
            if x.get("source") != "LinkedIn" or not m or len(x.get("desc") or "") >= 400 or "applicants" in x:
                continue
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}"
            if session:
                page = session.fetch(url)
            else:
                page = Fetcher.get(url, stealthy_headers=True, timeout=30, **({"proxy": proxy} if proxy else {}))
                if meter is not None:
                    meter["used"] = meter.get("used", 0) + len(page.body or b"") + 2000  # plus headers
            done += 1
            if page.status == 429 and stealth and not session:
                from scrapling.fetchers import StealthySession
                ctx = StealthySession(headless=True, timeout=30000, disable_resources=True)
                session = ctx.__enter__()
                page = session.fetch(url)
            if page.status == 429:
                # Through a rotating proxy the next request leaves from another IP: skip this offer (tried next
                # run) and go on; stop only when refusals follow one another. A single IP stops at the first.
                refused += 1
                if not proxy or refused >= 5:
                    return done, f"rate-limited after {done - refused} pages"
                time.sleep(2)
                continue
            refused = 0
            if page.status != 200:
                x["applicants"] = None  # gone or refused: not tried again
                continue
            _linkedin_fill(x, page)
            time.sleep(0.3 if proxy else 1.5)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)
    return done, ""


RECHECK_MIN, RECHECK_DAYS, RECHECK_LIMIT = 50, 2, 60


def recheck_applicants(items, proxy, meter=None):
    """A count is read once, but applicants keep coming: an offer seen at 141 can pass the 150 dealbreaker unseen.
    Offers counted between 50 and 150 more than 2 days ago are counted again (counts only: the description and
    Claude's reading stay), most crowded first, up to 120 pages a run (about 5 MB of proxy data)."""
    old = int(time.time() * 1000) - RECHECK_DAYS * 86400000
    todo = sorted((x for x in items if x.get("source") == "LinkedIn" and isinstance(x.get("applicants"), int)
                   and RECHECK_MIN <= x["applicants"] <= 150 and not x.get("applicantsCapped") and x.get("applicantsAt", 0) < old
                   and re.search(r"li-(\d+)", x.get("id", ""))), key=lambda x: -x["applicants"])[:RECHECK_LIMIT]
    n, crossed = 0, 0
    for x in todo:
        if meter and meter.get("used", 0) >= meter["left"]:
            break
        jid = re.search(r"li-(\d+)", x["id"]).group(1)
        page = Fetcher.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}", stealthy_headers=True, timeout=30, proxy=proxy)
        if meter is not None:
            meter["used"] = meter.get("used", 0) + len(page.body or b"") + 2000
        if page.status != 200:
            continue
        before = x["applicants"]
        _linkedin_fill(x, page, counts_only=True)
        n += 1
        crossed += before <= 150 < (x.get("applicants") or 0)
        time.sleep(0.3)
    if todo:
        print(f"  applicants re-counted: {n}/{len(todo)}, {crossed} now over 150")


def _linkedin_fill(x, page, counts_only=False):
    """Applicants (and, unless counts_only, the description and seniority) from a LinkedIn job page."""
    text = _t(" ".join(page.css("::text").getall()))
    x["applicantsAt"] = int(time.time() * 1000)
    a = re.search(r"(Over\s+)?(\d[\d,.]*)\s+applicants", text, re.I)
    first = re.search(r"Be among the first (\d+) applicants", text, re.I)
    if a:
        x["applicants"] = int(re.sub(r"[,.]", "", a.group(2)))
        x["applicantsCapped"] = bool(a.group(1))
    elif first:
        x["applicants"] = max(1, int(first.group(1)) // 2)  # "among the first 25" = fewer than 25 so far
    elif not counts_only:
        x["applicants"] = None
    if counts_only:
        return
    desc = page.css(".show-more-less-html__markup")
    if desc:
        x["desc"] = _keep(_t(desc[0].get_all_text()))
        x.pop("req", None)  # read from the title alone: read again from the full text
    level = re.search(r"Seniority level\s+([A-Za-z -]+?)\s+Employment type", text)
    if level:
        x["type"] = (x.get("type") or "") + (" · " if x.get("type") else "") + level.group(1)


ACADEMIC = {"Inria", "CNRS", "ABG", "jobs.ac.uk", "ELLIS", "Academic Positions", "ScholarshipDB", "jobRxiv", "Max Planck"}
STEALTH_SOURCES = {"ABG", "Academic Positions", "ScholarshipDB", "StepStone", "Tanitjobs", "Duunitori", "Emploi.ma"}
MAIN_SELECTORS = ['[itemprop="description"]', ".ck-content", ".job-description", "#job-description", ".jobsearch-JobComponent-description",
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
READER_V = 2  # 2: page body read when the structured data holds only a summary (Academic Positions)
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
        if len(x.get("desc") or "") >= 400:
            return True
    # No structured data, or only a summary in it (Academic Positions puts 180 characters there): the page body.
    for sel in MAIN_SELECTORS:
        el = page.css(sel)
        if el:
            text = _t(el[0].get_all_text())
            if len(text) > 400:
                if len(text) > len(x.get("desc") or ""):
                    x["desc"] = _keep(text)
                return True
    return bool(jp)


PROMISING = re.compile(r"\b(ai|ia|ml|machine learning|deep learning|llm|genai|data|python|d[ée]velopp\w*|developer|software|logiciel|"
                       r"engineer|ing[ée]nieur\w*|backend|full.?stack|devops|cloud|nlp|vision|research|recherche|phd|doctora\w*|th[èe]se)\b", re.I)


def details(items, limit=60, stealth_limit=20, stealth=True, only_sources=None, budget=360, priority=None):
    """Opens offer pages whose stored description is short and fills desc, deadline, salary, type.
    Stops when the time budget (seconds) runs out; the rest is picked up on later runs."""
    t0 = time.time()
    # Short descriptions, academic offers read once more for the contact they usually name at the bottom, and
    # descriptions cut at the old 2500-character limit (read again once, to get their candidate requirements).
    # An offer still short after its attempt is tried once more when the page reader improves (READER_V).
    short = lambda x: len(x.get("desc") or "") < 400 and (not x.get("detailed") or x.get("readerV", 1) < READER_V)
    todo = [x for x in items if x.get("source") != "LinkedIn" and x.get("url", "").startswith("http")
            and (only_sources is None or x.get("source") in only_sources)
            and (short(x) or (x.get("source") in ACADEMIC and not x.get("contactsChecked"))
                 or (len(x.get("desc") or "") == OLD_DESC_MAX and not x.get("recut")))]
    for x in todo:
        if len(x.get("desc") or "") == OLD_DESC_MAX:
            x["recut"] = True  # one more attempt only
        x["readerV"] = READER_V
    # Most promising first: an offer stays capped until its text is read, so a "Junior AI Engineer" is opened
    # before a "Barman" that was listed earlier.
    # With priority ({id: score the listing suggests}), the highest first.
    todo.sort(key=lambda x: (not PROMISING.search(x.get("title") or ""), -(priority or {}).get(x["id"], 0)))
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
    import pg
    cached = pg.ratings_get(keys) if pg.conn() else {}
    now = time.time()
    info = {}
    todo = []
    for k in keys:
        rec = cached.get(k)
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
                        pg.company_rating(k, names[k], rec, int(now * 1000))
                    time.sleep(1.5)
        except Exception as e:  # blocked or broken: keep what we have
            err = str(e)[:120]
    for x in items:
        rec = info.get(_norm(x.get("org")))
        if rec and rec.get("rating") is not None:
            x["company"] = {k: rec[k] for k in ("rating", "count", "source", "url") if k in rec}
    return looked, err
