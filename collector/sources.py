"""Scrapers for PhD, master's and job platforms, built on Scrapling (BSD-3, github.com/D4Vinci/Scrapling).

SCRAPERS use Scrapling's plain HTTP fetcher (or a site's public API/RSS) on pages the site's robots.txt allows.
STEALTH_SCRAPERS use StealthyFetcher, a real browser that passes Cloudflare challenges (ABG). Sites that block
GitHub's IP addresses outright (FindAPhD, Tanitjobs, MastersPortal, ZipRecruiter...) cannot be reached from there,
and Euraxess disallows its search in robots.txt; their email alerts reach the app through the Gmail scan.

Every scraper returns a list of dicts: id, title, org, location, c, kind, source, url, posted, deadline, desc.
"""
import json
import os
import re
import time

import requests
from datetime import date, datetime, timezone

from scrapling.fetchers import Fetcher

UA_PAUSE = 1.5  # seconds between requests to the same site


def _get(url):
    page = Fetcher.get(url, stealthy_headers=True, timeout=30)
    if page.status != 200:
        raise RuntimeError(f"HTTP {page.status} from {url.split('/')[2]}")
    time.sleep(UA_PAUSE)
    return page


def _t(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


PHD = re.compile(r"\bph\.?d\b|\bdoctoral|\bdoctorate|\bdoctorant|\bdoktorand|\bth[eè]se\b", re.I)


def is_phd(title):
    """PhD offer? Word boundaries keep "postdoctoral" out."""
    return bool(PHD.search(title or ""))


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
FR_MONTHS = {m: i for i, m in enumerate(["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre", "decembre"], 1)}


def _day_month(s, future=False):
    """'04 Aug' -> ISO date in the right year (past for posting dates, upcoming for deadlines)."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})", s or "")
    if not m or m.group(2).lower() not in MONTHS:
        return ""
    today = date.today()
    d = date(today.year, MONTHS[m.group(2).lower()], int(m.group(1)))
    if future and d < today:
        d = d.replace(year=today.year + 1)
    if not future and d > today:
        d = d.replace(year=today.year - 1)
    return d.isoformat()


def _fr_date(s):
    s = s.lower().replace("é", "e").replace("û", "u")
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", s)
    if not m or m.group(2) not in FR_MONTHS:
        return ""
    return date(int(m.group(3)), FR_MONTHS[m.group(2)], int(m.group(1))).isoformat()


def jobs_ac_uk(keywords):
    """jobs.ac.uk search, PhD studentships. UK and some EU universities."""
    out = []
    for kw in keywords:
        page = _get("https://www.jobs.ac.uk/search/?keywords=" + kw.replace(" ", "+") + "&jobTypeFacet%5B0%5D=phds&sortOrder=1")
        for r in page.css("div.j-search-result__result"):
            a = r.css(".j-search-result__text > a")
            if not a:
                continue
            text = _t(r.get_all_text())
            loc = re.search(r"Location:\s*(.+?)(?:\s+Salary:|\s+Date Placed:|$)", text)
            fund = re.search(r"Salary:\s*(.+?)(?:\s+Date Placed:|$)", text)
            placed = re.search(r"Date Placed:\s*(\d{1,2}\s+\w{3})", text)
            closes = _t(r.css(".j-search-result__date--blue::text").get())
            out.append({
                "id": "jac:" + (r.attrib.get("data-advert-id") or a[0].attrib.get("href", "")),
                "title": _t(a[0].get_all_text()), "org": _t(r.css(".j-search-result__employer b::text").get()),
                "location": _t(loc.group(1)) if loc else "", "c": "gl", "kind": "phd", "source": "jobs.ac.uk",
                "url": page.urljoin(a[0].attrib.get("href", "")), "posted": _day_month(placed.group(1)) if placed else "",
                "deadline": _day_month(closes, future=True), "desc": ("Funding: " + _t(fund.group(1))) if fund else "",
            })
    return out


def inria(keywords):
    """Inria job board: PhD offers and research engineer offers (France)."""
    out = []
    for filtre, kind in (("doctorants", "phd"), ("ingenieurs", "job")):
        page = _get(f"https://jobs.inria.fr/public/classic/fr/offres?filtre={filtre}")
        for li in page.css("li.resultats"):
            a = li.css("a.list-offres-link")
            if not a:
                continue
            ul = li.css("ul.infos-liste-offre-inria")
            info = _t(ul[0].get_all_text()) if ul else ""
            city = re.search(r"Ville\s*:\s*(.+?)(?:\s+[ÉE]quipe|\s+Date|$)", info)
            team = re.search(r"[ÉE]quipe Inria\s*:\s*(\S+)", info)
            deadline = li.css("time::attr(datetime)").get() or ""
            out.append({
                "id": "inria:" + (li.attrib.get("id", "") or a[0].attrib.get("href", "")),
                "title": _t(a[0].get_all_text()), "org": "Inria" + (f" ({team.group(1)})" if team else ""),
                "location": _t(city.group(1)).title() if city else "", "c": "fr", "kind": kind, "source": "Inria",
                "url": page.urljoin(a[0].attrib.get("href", "")), "posted": "", "deadline": deadline[:10], "desc": "",
            })
    return out


def ellis(keywords):
    """ELLIS (European Lab for Learning & Intelligent Systems) job board: PhD, postdoc and faculty positions."""
    out = []
    for n in (1, 2):
        page = _get(f"https://ellis.eu/research/jobs?page={n}")
        for a in page.css('a[href*="/research/jobs/20"]'):
            href = a.attrib.get("href", "")
            meta = a.parent.css("span.italic::text").get() if a.parent else ""
            m = re.search(r"Apply by (\d{2})/(\d{2})/(\d{2})\s*•?\s*(.*)", _t(meta))
            title = _t(a.get_all_text())
            low = title.lower()
            kind = "phd" if is_phd(title) else "job"
            out.append({
                "id": "ellis:" + href.rstrip("/").split("/")[-1], "title": title, "org": "", "location": _t(m.group(4)) if m else "",
                "c": "gl", "kind": kind, "source": "ELLIS", "url": page.urljoin(href), "posted": "",
                "deadline": f"20{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else "", "desc": "",
            })
    return out


def keejob(keywords):
    """Keejob, Tunisian job board."""
    out = []
    for kw in keywords:
        page = _get("https://www.keejob.com/offres-emploi/?keywords=" + kw.replace(" ", "+"))
        for art in page.css("article"):
            a = art.css("h2 a")
            if not a:
                continue
            href = a[0].attrib.get("href", "")
            jid = re.search(r"/offres-emploi/(\d+)/", href)
            spans = [_t(s) for s in art.css("span::text").getall() if _t(s)]
            posted = next((_fr_date(s) for s in spans if re.search(r"\d{4}", s)), "")
            where = next((s for s in spans if s and not re.search(r"\d{4}|/", s) and len(s) < 30 and not re.fullmatch(r"(?i)cdi|cdd|stage|sivp|freelance|int[eé]rim|temps (plein|partiel)|karama|alternance", s)), "")
            desc = _t(art.css("p.text-sm::text").get())
            out.append({
                "id": "keejob:" + (jid.group(1) if jid else href), "title": _t(a[0].get_all_text()),
                "org": _t(art.css("h2 + p a::text").get()), "location": where, "c": "tn", "kind": "job", "source": "Keejob",
                "url": page.urljoin(href), "posted": posted, "deadline": "", "desc": desc[:600],
            })
    return out


def abg(keywords, pages=8):
    """ABG (Association Bernard Gregory): thesis offers, research jobs and M2 internships, mostly France.
    Behind Cloudflare, so this uses Scrapling's StealthyFetcher (a real browser); robots.txt disallows nothing.
    The listing pages through JavaScript, so the browser clicks "next" and keeps each page's HTML."""
    from scrapling.fetchers import StealthyFetcher  # needs `scrapling install` (browser) on the runner
    from scrapling.parser import Selector

    base = "https://www.abg.asso.fr"
    html_pages = []

    def walk(page):
        for _ in range(pages):
            html_pages.append(page.content())
            nxt = page.locator("td.pager_suiv a").first
            if not nxt.count():
                break
            first = page.locator("div.it_offre h2 a").first.get_attribute("href")
            nxt.click()
            try:  # wait for the listing to change
                page.wait_for_function(
                    "f => { const a = document.querySelector('div.it_offre h2 a'); return a && a.getAttribute('href') !== f; }",
                    arg=first, timeout=15000)
            except Exception:
                break
            page.wait_for_timeout(int(UA_PAUSE * 1000))

    resp = StealthyFetcher.fetch(base + "/fr/candidatOffres", headless=True, solve_cloudflare=True, network_idle=True,
                                 timeout=120000, page_action=walk)
    if resp.status != 200 or not html_pages:
        raise RuntimeError(f"HTTP {resp.status} from ABG")

    out, seen = [], set()
    for html in html_pages:
        doc = Selector(html)
        for it in doc.css("div.it_offre"):
            a = it.css("h2 a")
            if not a:
                continue
            href = a[0].attrib.get("href", "")
            ref = re.search(r"id_offre/(\d+)", href)
            oid = "abg:" + (ref.group(1) if ref else href)
            if oid in seen:
                continue
            seen.add(oid)
            kind_text = _t(it.css(".ligne_infos .type::text").get()).lower()
            kind = "phd" if "thèse" in kind_text or "these" in kind_text else "job"
            posted = re.search(r"(\d{2})/(\d{2})/(\d{4})", _t(it.css(".l_date::text").get()))
            org_el = it.css(".societe")
            org = re.sub(r"\s*(Emploi|Stage|Thèse|These)$", "", _t(org_el[0].get_all_text()) if org_el else "")
            loc = _t(it.css(".adresse::text").get()).strip(", ")
            low = loc.lower()
            c = next((v for k, v in (("allemagne", "de"), ("suisse", "ch"), ("canada", "ca"), ("tunisie", "tn")) if k in low),
                     "fr" if not loc or "france" in low or "," not in loc else "gl")
            extra = [_t(x) for x in (it.css(".contrat::text").get(), it.css(".salaire::text").get()) if _t(x)]
            mots = it.css(".mots::text").getall()
            mots = _t(mots[-1]) if mots else ""
            desc = _t(it.css(".text::text").get())
            out.append({
                "id": oid, "title": _t(a[0].get_all_text()), "org": org, "location": loc, "c": c, "kind": kind,
                "source": "ABG", "url": href if href.startswith("http") else base + href,
                "posted": f"{posted.group(3)}-{posted.group(2)}-{posted.group(1)}" if posted else "", "deadline": "",
                "type": kind_text, "desc": (desc + (f" Keywords: {mots}." if mots else "") + (" " + " · ".join(extra) if extra else ""))[:600],
            })
    print(f"  ABG: {len(html_pages)} pages read, {len(out)} offers before topic filter")
    return out


EN_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"], 1)}
DE_MONTHS = {m: i for i, m in enumerate(["januar", "februar", "marz", "april", "mai", "juni", "juli", "august",
                                         "september", "oktober", "november", "dezember"], 1)}


def _long_date(s):
    """'September 25, 2026' or '25. September 2026' -> ISO date."""
    s = (s or "").lower().replace("ä", "a")
    m = re.search(r"([a-z]+)\s+(\d{1,2}),\s*(\d{4})", s)
    if m and m.group(1) in EN_MONTHS:
        return date(int(m.group(3)), EN_MONTHS[m.group(1)], int(m.group(2))).isoformat()
    m = re.search(r"(\d{1,2})\.?\s+([a-z]+)\s+(\d{4})", s)
    if m and m.group(2) in DE_MONTHS:
        return date(int(m.group(3)), DE_MONTHS[m.group(2)], int(m.group(1))).isoformat()
    return ""


def _json(url):
    page = Fetcher.get(url, stealthy_headers=True, timeout=30)
    if page.status != 200:
        raise RuntimeError(f"HTTP {page.status} from {url.split('/')[2]}")
    time.sleep(UA_PAUSE)
    return page.json()


def _strip_html(s):
    return _t(re.sub(r"<[^>]+>", " ", s or "")).replace("&amp;", "&").replace("&#39;", "'")


def hellowork(keywords):
    """HelloWork, large French job board."""
    out = []
    for kw in keywords[:3]:
        page = _get("https://www.hellowork.com/fr-fr/emploi/recherche.html?k=" + kw.replace(" ", "+"))
        for li in page.css('li[data-id-storage-target="item"]'):
            oid = li.attrib.get("data-id-storage-item-id", "")
            title = li.css('input[name="title"]::attr(value)').get() or ""
            org = li.css('input[name="company"]::attr(value)').get() or ""
            href = li.css('a[href*="/fr-fr/emplois/"]::attr(href)').get() or ""
            if not oid or not title or not href:
                continue
            bits = [b for b in (_t(x) for x in li.css("*::text").getall()) if b and len(b) < 60]
            after = bits[bits.index(org) + 1:] if org in bits else []
            out.append({
                "id": "hellowork:" + oid, "title": _t(title), "org": _t(org), "location": after[0] if after else "",
                "c": "fr", "kind": "job", "source": "HelloWork", "url": page.urljoin(href), "posted": "", "deadline": "",
                "type": after[1] if len(after) > 1 else "", "desc": " · ".join(after[1:4]),
            })
    return out


def jobs_ch(keywords):
    """jobs.ch, main Swiss job board (reads the page's JobPosting structured data)."""
    out = []
    for kw in keywords[:3]:
        page = _get("https://www.jobs.ch/en/vacancies/?term=" + kw.replace(" ", "%20"))
        for raw in page.css('script[type="application/ld+json"]::text').getall():
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            for block in data if isinstance(data, list) else [data]:
                if block.get("@type") != "ItemList":
                    continue
                for el in block.get("itemListElement", []):
                    j = el.get("item", {})
                    if not j.get("url"):
                        continue
                    addr = (j.get("jobLocation") or {}).get("address") or {}
                    out.append({
                        "id": "jobsch:" + str((j.get("identifier") or {}).get("value") or j["url"]), "title": _t(j.get("title")),
                        "org": _t((j.get("hiringOrganization") or {}).get("name")),
                        "location": _t(addr.get("addressLocality") or "Switzerland"), "c": "ch", "kind": "job",
                        "source": "jobs.ch", "url": j["url"], "posted": str(j.get("datePosted", ""))[:10], "deadline": "",
                        "type": _t(j.get("employmentType")), "desc": _strip_html(j.get("description"))[:600],
                    })
    return out


def jobbank(keywords):
    """Job Bank, the Government of Canada job board (robots.txt asks for 5 s between requests)."""
    out = []
    for kw in keywords[:2]:
        page = _get("https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring=" + kw.replace(" ", "+"))
        time.sleep(5)
        for a in page.css("a.resultJobItem"):
            jid = re.search(r"jobposting/(\d+)", a.attrib.get("href", ""))
            if not jid:
                continue
            out.append({
                "id": "jobbank:" + jid.group(1), "title": _t(a.css(".noctitle::text").get()),
                "org": _t(a.css("li.business::text").get()), "location": _t(" ".join(a.css("li.location::text").getall())),
                "c": "ca", "kind": "job", "source": "Job Bank",
                "url": "https://www.jobbank.gc.ca/jobsearch/jobposting/" + jid.group(1),
                "posted": _long_date(a.css("li.date::text").get()), "deadline": "", "type": "",
                "desc": _t(" ".join(a.css("li.salary::text").getall())),
            })
    return out


def cnrs(keywords):
    """CNRS job portal: research engineer, fixed-term and PhD offers (France)."""
    out = []
    page = _get("https://emploi.cnrs.fr/Offres/Recherche.aspx")
    for card in page.css("div.card"):
        a = card.css("h3 a")
        if not a:
            continue
        href = a[0].attrib.get("href", "")
        ref = re.search(r"/Offres/\w+/([^/]+)/", href)
        metas = [_t(p.get_all_text()) for p in card.css(".meta p")]
        labels = [_t(x) for x in card.css("li.label span::text").getall()]
        out.append({
            "id": "cnrs:" + (ref.group(1) if ref else href), "title": _t(a[0].get_all_text()),
            "org": "CNRS" + (f" ({metas[0]})" if metas else ""), "location": metas[1].title() if len(metas) > 1 else "",
            "c": "fr", "kind": "phd" if "/Doctorant/" in href else "job", "source": "CNRS", "url": page.urljoin(href),
            "posted": "", "deadline": "", "type": " · ".join(labels), "desc": " · ".join(labels),
        })
    return out


def farojob(keywords):
    """Farojob, Tunisian job board (job offers only, not CVs)."""
    out = []
    for kw in keywords[:3]:
        page = _get("https://www.farojob.net/?s=" + kw.replace(" ", "+") + "&post_type=job_listing")
        for art in page.css("article.result"):
            a = art.css("h2 a")
            href = a[0].attrib.get("href", "") if a else ""
            if "/jobs/" not in href:
                continue
            title = _t(a[0].get_all_text())
            m = re.match(r"(.+?)\s+recrute\s+(.+)", title, re.I)
            out.append({
                "id": "farojob:" + href.rstrip("/").split("/")[-1], "title": re.sub(r"^(un|une|des)\s+", "", _t(m.group(2)), flags=re.I) if m else title,
                "org": _t(m.group(1)) if m else "", "location": "Tunisie", "c": "tn", "kind": "job", "source": "Farojob",
                "url": href, "posted": "", "deadline": "", "desc": _t(art.css("p::text").get())[:600],
            })
    return out


def _rss_field(item, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S)
    return _t(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))) if m else ""


def _rss_items(url):
    page = _get(url)
    xml = page.body.decode("utf8", "replace") if isinstance(page.body, bytes) else str(page.body)
    return re.findall(r"<item>(.*?)</item>", xml, re.S)


def _rss_date(item):
    try:
        return datetime.strptime(_rss_field(item, "pubDate")[:25].strip(), "%a, %d %b %Y %H:%M:%S").date().isoformat()
    except ValueError:
        return ""


# LinkedIn posts: people announcing they hire ("we're hiring", "je recrute"...), found through Google results bought
# from Serper (serper.dev; SERPER_API_KEY). LinkedIn's own post search needs a logged-in account, which its terms
# forbid automating. Once a day (the run after midnight UTC): two searches x your countries, one credit each.
POST_PLACES = {"fr": ("fr", "(France OR Paris OR Lyon OR Toulouse)"), "de": ("de", "(Germany OR Deutschland OR Berlin OR München)"),
               "ca": ("ca", "(Canada OR Montréal OR Montreal OR Toronto)"), "ch": ("ch", "(Switzerland OR Suisse OR Schweiz OR Zürich OR Genève)"),
               "tn": ("tn", "(Tunisie OR Tunisia OR Tunis OR Sfax)"), "be": ("be", "(Belgium OR Belgique OR Brussels OR Bruxelles OR Antwerp)"),
               "nl": ("nl", "(Netherlands OR Amsterdam OR Rotterdam OR Eindhoven OR Utrecht)"), "lu": ("lu", "(Luxembourg)"),
               "se": ("se", "(Sweden OR Stockholm OR Gothenburg)"), "dk": ("dk", "(Denmark OR Copenhagen)"),
               "fi": ("fi", "(Finland OR Helsinki)"), "no": ("no", "(Norway OR Oslo)"), "ma": ("ma", "(Maroc OR Morocco OR Casablanca OR Rabat)"), "ie": ("ie", "(Ireland OR Dublin OR Cork)"), "uk": ("uk", "(\"United Kingdom\" OR London OR UK)")}
POST_COUNTRIES, POST_QUERIES = list(POST_PLACES), ["machine learning engineer", "AI engineer"]
HIRING = '("hiring" OR "we\'re hiring" OR "je recrute" OR "nous recrutons" OR "on recrute" OR "wir suchen" OR "join our team")'


def _ago(s):
    """'3 days ago' / '5 hours ago' / 'Oct 2, 2026' -> ISO date, or ''."""
    m = re.match(r"(\d+)\s+(minute|hour|day|week)s?\s+ago", s or "")
    if m:
        days = {"minute": 0, "hour": 0, "day": 1, "week": 7}[m.group(2)] * int(m.group(1))
        return date.fromordinal(date.today().toordinal() - days).isoformat()
    try:
        return datetime.strptime((s or "").strip(), "%b %d, %Y").date().isoformat()
    except ValueError:
        return _long_date(s or "")


def linkedin_posts(keywords):
    """LinkedIn posts from the past week announcing a hire, for your top searches in each of your countries."""
    import os
    key = os.environ.get("SERPER_API_KEY")
    if not key:
        raise RuntimeError("add a SERPER_API_KEY secret (free at serper.dev) to search LinkedIn posts")
    if time.gmtime().tm_hour >= 6 and os.environ.get("POSTS_ANY_HOUR") != "1":
        return []  # once a day is enough, and keeps the free credits for months
    out, seen = [], set()
    for c in POST_COUNTRIES:
        gl, place = POST_PLACES[c]
        for kw in POST_QUERIES:
            r = requests.post("https://google.serper.dev/search", timeout=30, headers={"X-API-KEY": key, "Content-Type": "application/json"},
                              json={"q": f'site:linkedin.com/posts {HIRING} "{kw}" {place}', "gl": gl, "num": 10, "tbs": "qdr:w"})
            if r.status_code != 200:
                raise RuntimeError(f"Serper HTTP {r.status_code}: {r.text[:120]}")
            for o in r.json().get("organic") or []:
                link = (o.get("link") or "").split("?")[0]
                if "linkedin.com/posts/" not in link or link in seen:
                    continue
                seen.add(link)
                head = _t(o.get("title"))
                m = re.match(r"(.+?) (?:on|sur|auf) LinkedIn\s*:\s*(.+)", head)
                who, text = (m.group(1), m.group(2)) if m else ("", head)
                text = re.sub(r"\s*[|·-]\s*\d+\s+comments?.*$", "", text)
                out.append({
                    "id": "lipost:" + link, "title": text[:140] or "Hiring post", "org": who, "location": c.upper(), "c": c,
                    "kind": "job", "source": "LinkedIn posts", "url": link, "posted": _ago(o.get("date")), "deadline": "", "type": "post",
                    "desc": _t(o.get("snippet"))[:600], "poster": who,
                })
            time.sleep(0.5)
    return out


def poli(keywords):
    """Poli (withpoli.com), UK jobs at licensed visa sponsors: the signed-in feed when there is a Poli account
    (POLI_EMAIL / POLI_PASSWORD), and the signed-out visitor feed asked for in narrow slices (poli.all_jobs)."""
    import poli as poli_api
    return poli_api.all_jobs()


# Places in your countries, for sources that list jobs worldwide (company boards, Hacker News): an offer is kept
# only if it is in one of them, or remote without being tied to another country.
PLACES = {
    "fr": ("france", "paris", "lyon", "toulouse", "nantes", "bordeaux", "lille", "marseille", "montpellier", "grenoble",
           "rennes", "sophia antipolis", "nice", "strasbourg"),
    "de": ("germany", "deutschland", "berlin", "munich", "münchen", "hamburg", "frankfurt", "cologne", "köln", "stuttgart",
           "heidelberg", "freiburg", "leonberg", "karlsruhe", "dresden", "leipzig", "düsseldorf", "tübingen", "darmstadt"),
    "ch": ("switzerland", "schweiz", "suisse", "zurich", "zürich", "geneva", "genève", "lausanne", "basel", "bern"),
    "ca": ("canada", "toronto", "montreal", "montréal", "vancouver", "ottawa", "québec", "quebec", "calgary", "waterloo", "ontario"),
    "tn": ("tunisia", "tunisie", "tunis", "sfax", "sousse"),
    "be": ("belgium", "belgique", "brussels", "bruxelles", "antwerp", "ghent", "leuven", "liège", "liege"),
    "nl": ("netherlands", "nederland", "amsterdam", "rotterdam", "the hague", "utrecht", "eindhoven", "delft"),
    "lu": ("luxembourg",),
    "se": ("sweden", "stockholm", "gothenburg", "göteborg", "malmö", "malmo", "lund"),
    "dk": ("denmark", "copenhagen", "københavn", "aarhus"),
    "fi": ("finland", "helsinki", "espoo", "tampere"),
    "no": ("norway", "oslo", "bergen", "trondheim"),
    "ma": ("morocco", "maroc", "casablanca", "rabat", "marrakech"),
    "ie": ("ireland", "dublin", "cork", "galway", "limerick"),
    "uk": ("united kingdom", "london", "manchester", "cambridge", "oxford", "edinburgh", "bristol", "england", "scotland"),
}
_REMOTE = re.compile(r"\b(remote|anywhere|worldwide|global|télétravail)\b", re.I)
_ELSEWHERE = re.compile(r"\b(us|usa|u\.s\.|united states|india|brazil|latam|apac|asia|australia|"
                        r"singapore|japan|new york|san francisco|americas?|seattle|austin|boston|chicago|spain|"
                        r"barcelona|madrid|italy|portugal|lisbon|poland|warsaw|"
                        r"austria|vienna|bulgaria|israel|mexico|argentina|colombia|china|korea|dubai|uae|"
                        r"nyc|bay area|sf)\b", re.I)
# Roles worth showing from sources that list every job a company has (sales, legal, HR... are left out).
TECH_TITLE = re.compile(r"engineer|developer|scientist|research|machine learning|\bml\b|\bai\b|\bia\b|\bllm|data|software|"
                        r"devops|\bsre\b|architect|ingénieur|développeur|entwickler|informatik|ph\.?d|doctor|intern|stagiaire|"
                        r"werkstudent|backend|frontend|full.?stack|platform|infrastructure|security|mlops|nlp|vision", re.I)


def _where(text):
    """'Paris, France' -> 'fr'; 'Remote (EMEA)' -> 'gl'; 'New York' or 'US - Remote' -> None (not one of your places)."""
    low = (text or "").lower()
    for c, words in PLACES.items():
        if any(re.search(r"(?<![a-zà-ÿ])" + re.escape(w) + r"(?![a-zà-ÿ])", low) for w in words):
            return c
    return "gl" if _REMOTE.search(low) and not _ELSEWHERE.search(low) else None


# Company career boards on Greenhouse, Lever, Ashby, Workable and SmartRecruiters: their public job-board APIs, made for career sites
# to embed. AI and tech employers hiring in France, Germany, Switzerland, Canada or remotely; add a board by its
# name in the board URL (boards.greenhouse.io/<name>, jobs.lever.co/<name>, jobs.ashbyhq.com/<name>).
COMPANY_BOARDS = {
    "greenhouse": ["anthropic", "helsing", "dataiku", "doctolib", "datadog", "mirakl", "celonis", "algolia", "getyourguide",
                   "n26", "sumup", "parloa", "proton", "dialpad",
                   "dnascript", "shifttechnology", "flowdesk", "platformsh"],
    "lever": ["contentsquare", "blablacar", "qonto", "pigment", "swile", "sonarsource", "waabi",
              "malt", "verkor", "vestiairecollective", "younited", "360learning", "agicap", "brevo", "ekimetrics", "gojob",
              "playplay", "equativ"],
    "ashby": ["cohere", "deepl", "alephalpha", "photoroom", "alan", "owkin", "backmarket", "poolside", "n8n", "wealthsimple",
              "openai", "dust", "nabla", "ledger", "sorare", "langdock", "black-forest-labs", "elevenlabs", "synthesia",
              "wayve", "hopper",
              "mistral.ai", "pennylane", "voodoo", "seyna", "lifen", "ankorstore"],
    "workable": ["huggingface"],
    "smartrecruiters": ["ecovadis", "iad", "lecollectionist", "worldia"],
}
# French Tech Next40 / 120 boards (data/french-tech-120.csv), found from their careers pages and checked by company
# name on 12 Oct 2026; same-named boards of other companies (Comet, Swan, Sweep in the US) were left out.
# Lever and Ashby return no company name: the board name is shown unless named here.
BOARD_NAMES = {"mistral.ai": "Mistral AI", "openai": "OpenAI", "n8n": "n8n", "deepl": "DeepL", "vestiairecollective": "Vestiaire Collective", "360learning": "360Learning",
               "playplay": "PlayPlay", "backmarket": "Back Market", "blablacar": "BlaBlaCar", "elevenlabs": "ElevenLabs",
               "alephalpha": "Aleph Alpha", "photoroom": "Photoroom", "contentsquare": "Contentsquare", "sonarsource": "SonarSource"}


def _board(ats, name):
    """One company's open jobs as (title, org, location text, url, posted, desc)."""
    if ats == "greenhouse":
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{name}/jobs", timeout=30).json()
        return [(j["title"], j.get("company_name") or name, (j.get("location") or {}).get("name", ""), j["absolute_url"],
                 (j.get("first_published") or j.get("updated_at") or "")[:10], "") for j in r.get("jobs", [])]
    if ats == "lever":
        r = requests.get(f"https://api.lever.co/v0/postings/{name}?mode=json", timeout=30).json()
        return [(j["text"], BOARD_NAMES.get(name) or name.title(), " / ".join((j.get("categories") or {}).get("allLocations") or [(j.get("categories") or {}).get("location", "")])
                 + (" remote" if j.get("workplaceType") == "remote" else ""), j["hostedUrl"],
                 datetime.fromtimestamp(j["createdAt"] / 1000, timezone.utc).date().isoformat() if j.get("createdAt") else "",
                 j.get("descriptionPlain") or "") for j in r if isinstance(j, dict)]
    if ats == "ashby":
        r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{name}", timeout=30).json()
        return [(j["title"], BOARD_NAMES.get(name) or name.replace("-", " ").title(),
                 " / ".join([j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []])
                 + (" remote" if j.get("isRemote") and not j.get("secondaryLocations") else ""),
                 j["jobUrl"], (j.get("publishedAt") or "")[:10], j.get("descriptionPlain") or "")
                for j in r.get("jobs", []) if j.get("isListed", True)]
    if ats == "smartrecruiters":
        r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{name}/postings?limit=100", timeout=30).json()
        return [(j["name"], (j.get("company") or {}).get("name") or name, ((j.get("location") or {}).get("fullLocation") or "")
                 + (" remote" if (j.get("location") or {}).get("remote") else ""), f"https://jobs.smartrecruiters.com/{name}/{j['id']}",
                 (j.get("releasedDate") or "")[:10], "") for j in r.get("content", [])]
    r = requests.get(f"https://apply.workable.com/api/v1/widget/accounts/{name}", timeout=30).json()
    return [(j["title"], r.get("name") or name, f'{j.get("city", "")} {j.get("country", "")}' + (" remote" if j.get("telecommuting") else ""),
             j.get("url") or j.get("application_url", ""), j.get("published_on", ""), "") for j in r.get("jobs", [])]


def company_boards(keywords):
    """Open jobs at the companies in COMPANY_BOARDS, kept when they are in your countries or remote."""
    from concurrent.futures import ThreadPoolExecutor
    tasks = [(ats, name) for ats, names in COMPANY_BOARDS.items() for name in names]

    def one(t):
        try:
            return t, _board(*t), None
        except Exception as e:
            return t, [], e
    out, failed = [], []
    with ThreadPoolExecutor(8) as pool:
        for (ats, name), jobs, err in pool.map(one, tasks):
            if err:
                failed.append(name)
            for title, org, loc, url, posted, desc in jobs:
                c = _where(loc)
                if c and url and TECH_TITLE.search(title):
                    out.append({"id": f"{ats}:{name}:{url.rstrip('/').split('/')[-1]}", "title": _t(title), "org": org,
                                "location": _t(loc.replace(" remote", " (remote)")) or "Remote", "c": c,
                                "kind": "phd" if is_phd(title) else "job", "source": "Company boards", "url": url,
                                "posted": posted, "deadline": "", "desc": _t(desc)[:600]})
    if failed and len(failed) == len(tasks):
        raise RuntimeError("no company board answered")
    return out


def hn_hiring(keywords):
    """Hacker News "Ask HN: Who is hiring?", the monthly thread (through the official Algolia HN API): each top-level
    comment is one company, "Company | Role | Place | ...". Kept when the place is one of yours or remote."""
    from html import unescape
    hits = requests.get("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=6", timeout=30).json()["hits"]
    story = next((h for h in hits if "who is hiring" in h["title"].lower()), None)
    if not story:
        return []
    thread = requests.get(f"https://hn.algolia.com/api/v1/items/{story['objectID']}", timeout=60).json()
    out = []
    for c in thread.get("children") or []:
        text = unescape(c.get("text") or "")
        head = _strip_html(text.split("<p>")[0])
        parts = [p.strip() for p in re.split(r"\s+[|•–-]\s+", head) if p.strip()]
        where = _where(head)
        if len(parts) < 2 or not where:
            continue
        role = next((p for p in parts[1:] if re.search(r"engineer|developer|scientist|research|ml|ai\b|data|software|founding", p, re.I)), parts[1])
        out.append({
            "id": f"hn:{c['id']}", "title": role[:140], "org": parts[0][:80], "location": next((p for p in parts if _where(p)), where.upper()),
            "c": where, "kind": "job", "source": "HN Who is hiring", "url": f"https://news.ycombinator.com/item?id={c['id']}",
            "posted": (c.get("created_at") or "")[:10], "deadline": "", "desc": _strip_html(text)[:600],
        })
    return out


FREEWORK_COUNTRIES = {"FR": "fr", "DE": "de", "CH": "ch", "CA": "ca", "TN": "tn", "BE": "be", "LU": "lu", "NL": "nl", "MA": "ma"}


def free_work(keywords):
    """Free-Work, French IT job board (permanent jobs and freelance missions), through the JSON API its site uses."""
    out, seen = [], set()
    for kw in keywords[:3]:
        resp = requests.get("https://www.free-work.com/api/job_postings?itemsPerPage=40&searchKeywords=" + requests.utils.quote(kw),
                            headers={"Accept": "application/ld+json"}, timeout=30)
        resp.raise_for_status()
        time.sleep(UA_PAUSE)
        for m in resp.json().get("hydra:member", []):
            loc = m.get("location") or {}
            c = FREEWORK_COUNTRIES.get(loc.get("countryCode") or "") or ("gl" if m.get("remoteMode") == "full" else None)
            if not c or m["id"] in seen:
                continue
            seen.add(m["id"])
            contracts = {"permanent": "CDI", "fixed-term": "CDD", "contractor": "Freelance", "internship": "Stage",
                         "apprenticeship": "Alternance"}
            out.append({
                "id": f"freework:{m['id']}", "title": _t(m.get("title")), "org": (m.get("company") or {}).get("name", ""),
                "location": loc.get("label") or "France", "c": c, "kind": "job", "source": "Free-Work",
                "url": f"https://www.free-work.com/fr/tech-it/job-mission/{(m.get('job') or {}).get('slug', 'job')}/{m['slug']}",
                "posted": (m.get("publishedAt") or "")[:10], "deadline": "",
                "type": " · ".join(contracts.get(x, x) for x in m.get("contracts") or []), "desc": _strip_html(m.get("description"))[:600],
            })
    return out


def berlin_startup_jobs(keywords):
    """Berlin Startup Jobs, engineering jobs at Berlin startups (official RSS feed). Titles read "Role // Company"."""
    from html import unescape
    out = []
    for item in _rss_items("https://berlinstartupjobs.com/engineering/feed/"):
        full, link = unescape(_rss_field(item, "title")), _rss_field(item, "link")
        title, _, org = full.rpartition(" // ")
        out.append({
            "id": "bsj:" + link.rstrip("/").split("/")[-1], "title": _t(title or full), "org": _t(org) if title else "",
            "location": "Berlin", "c": "de", "kind": "job", "source": "Berlin Startup Jobs", "url": link,
            "posted": _rss_date(item), "deadline": "", "desc": _strip_html(unescape(_rss_field(item, "description")))[:600],
        })
    return out


def eth_zurich(keywords):
    """ETH Zurich job board: PhD, postdoc, research and engineering positions."""
    page = _get("https://jobs.ethz.ch/?lang=en")
    out = []
    for li in page.css("li.job-ad__item__wrapper"):
        a = li.css("a.job-ad__item__link")
        if not a:
            continue
        href = a[0].attrib.get("href", "")
        title = _t(li.css(".job-ad__item__title::text").get())
        meta = _t(li.css(".job-ad__item__company::text").get())
        posted, _, dept = meta.partition("|")
        d = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", posted.strip())
        out.append({
            "id": "eth:" + href.rstrip("/").split("/")[-1], "title": title, "org": "ETH Zurich" + (" · " + _t(dept) if dept.strip() else ""),
            "location": "Zürich", "c": "ch", "kind": "phd" if is_phd(title) else "job", "source": "ETH Zurich",
            "url": page.urljoin(href), "posted": f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else "", "deadline": "",
            "type": _t(li.css(".job-ad__item__details::text").get()), "desc": "",
        })
    return out


def academics_de(keywords):
    """academics.de, German academic and research job board (professorships, PhD, postdoc, research staff)."""
    out, seen = [], set()
    for kw in keywords[:3]:
        page = _get("https://www.academics.de/jobs?q=" + kw.replace(" ", "+"))
        for a in page.css('a[id^="job-"]'):
            href = a.attrib.get("href", "")
            jid = re.search(r"-(\d+)$", href)
            if not jid or jid.group(1) in seen:
                continue
            seen.add(jid.group(1))
            title = _t(a.attrib.get("title") or a.css("h2::text").get())
            logo = a.css("img")
            org = re.sub(r"\s*-\s*Logo$", "", logo[0].attrib.get("alt", "")) if logo else ""
            out.append({
                "id": "academics:" + jid.group(1), "title": title, "org": org, "location": "Germany", "c": "de",
                "kind": "phd" if is_phd(title) else "job", "source": "academics.de", "url": page.urljoin(href),
                "posted": "", "deadline": "", "desc": _t(" ".join(a.css("p::text").getall()))[:600],
            })
    return out


def _english(keywords, n=3):
    """Search words for boards in countries where tech offers are mostly in English (Nordics, EU research)."""
    plain = [k for k in keywords if k.isascii()]
    return list(dict.fromkeys(plain[:n] + ["machine learning", "data scientist"]))[:n + 1]


def platsbanken(keywords):
    """Platsbanken, the Swedish Public Employment Service board, through its open JobSearch API (no key):
    full descriptions included."""
    out = []
    for kw in _english(keywords):
        r = requests.get("https://jobsearch.api.jobtechdev.se/search", params={"q": kw, "limit": 50},
                         headers={"accept": "application/json"}, timeout=30)
        r.raise_for_status()
        for h in r.json().get("hits") or []:
            addr = h.get("workplace_address") or {}
            out.append({
                "id": "platsbanken:" + str(h.get("id")), "title": _t(h.get("headline")), "org": _t((h.get("employer") or {}).get("name")),
                "location": _t(addr.get("municipality") or addr.get("region") or "Sverige"), "c": "se", "kind": "job",
                "source": "Platsbanken", "url": h.get("webpage_url") or f"https://arbetsformedlingen.se/platsbanken/annonser/{h.get('id')}",
                "posted": (h.get("publication_date") or "")[:10], "deadline": (h.get("application_deadline") or "")[:10],
                "type": _t((h.get("employment_type") or {}).get("label")), "desc": _t((h.get("description") or {}).get("text"))[:4000],
            })
        time.sleep(UA_PAUSE)
    return out


def _find_results(o):
    """The list of job records (dicts with 'tid' and 'headline') wherever Jobindex nests it."""
    if isinstance(o, list) and o and isinstance(o[0], dict) and "tid" in o[0] and "headline" in o[0]:
        return o
    for v in (o.values() if isinstance(o, dict) else o if isinstance(o, list) else []):
        found = _find_results(v)
        if found:
            return found
    return []


def _dmy(s):
    """'8 Nov 2026' or '10 October 2026' -> ISO date."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", s or "")
    return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat() if m and m.group(2).lower() in MONTHS else ""


def jobindex(keywords):
    """Jobindex, the main Danish job board: the results page embeds its data (var Stash = {...}). Its search
    matches any word ("LLM engineer" returns every engineer), so it gets precise phrases instead of the keywords."""
    out = []
    for kw in ['"machine learning"', '"artificial intelligence"', '"data scientist"', '"python developer"']:
        page = _get("https://www.jobindex.dk/jobsoegning?q=" + requests.utils.quote(kw))
        h = str(page.html_content)
        i = h.find("var Stash")
        if i < 0:
            continue
        stash, _ = json.JSONDecoder().raw_decode(h[h.find("{", i):])
        for j in _find_results(stash):
            if not j.get("tid"):
                continue
            out.append({
                "id": "jobindex:" + j["tid"], "title": _t(j.get("headline")), "org": _t(j.get("companytext")),
                "location": _t(j.get("area") or "Danmark"), "c": "dk", "kind": "phd" if is_phd(j.get("headline")) else "job", "source": "Jobindex",
                "url": j.get("share_url") or j.get("url"), "posted": j.get("firstdate") or "", "deadline": j.get("lastdate") or "",
                "type": "", "desc": _t(re.sub(r"<[^>]+>", " ", j.get("html") or ""))[:4000],
            })
    return out


def euraxess(keywords, limit=20):
    """EURAXESS, the European Commission's research jobs portal: first-stage researcher (R1) posts, which are
    PhD positions and research jobs open without a doctorate. Each one's page is read for the full text."""
    cards = {}
    # Facet filters in the URL: the keywords, and first-stage researcher (R1 = job_research_profile 447).
    pages = [_get("https://euraxess.ec.europa.eu/jobs/search?" + requests.utils.quote(f"f[0]=keywords:{kw}&f[1]=job_research_profile:447", safe="=&")
                  + (f"&page={n}" if n else "")) for kw in _english(keywords, 2) for n in range(2)]
    for page in pages:
        for a in page.css("a"):
            href = a.attrib.get("href", "")
            if not re.match(r"^/jobs/\d+$", href) or href in cards:
                continue
            card = a
            for _ in range(6):
                card = card.parent
                if card is None or len(card.get_all_text()) > 250:
                    break
            if card is not None:
                cards[href] = (_t(a.get_all_text()), _t(card.get_all_text()))  # the link text is the offer's title
    out = []
    for href, (title, text) in cards.items():
        if "(R1)" not in text or len(out) >= limit:
            continue
        place = re.search(r"Work Locations:.*?Number of offers: \d+,\s*([^,]+),\s*([^,]+)", text)
        country = next((c for w, c in COUNTRY_WORDS if place and w in place.group(1).lower()), "xx")
        deadline = re.search(r"Application Deadline:\s*(\d{1,2} \w+ \d{4})", text)
        posted = re.search(r"Posted on:\s*(\d{1,2} \w+ \d{4})", text)
        try:
            detail = _get("https://euraxess.ec.europa.eu" + href)
        except RuntimeError:
            continue
        body = _t((detail.css("main") or [detail])[0].get_all_text())
        out.append({
            "id": "euraxess:" + href.rsplit("/", 1)[1], "title": title, "org": _t(text.split(" Posted on:")[0])[:80],
            # Other countries go under gl with the country named: score.js then ranks them as abroad (PhDs stay, lower).
            "location": _t(f"{place.group(2)}, {place.group(1)}" if place else ""), "c": country if country != "xx" else "gl",
            "kind": "phd" if is_phd(title) else "job",  # the title: a postdoc's text also says "PhD"
            "source": "EURAXESS", "url": "https://euraxess.ec.europa.eu" + href, "posted": _dmy(posted.group(1)) if posted else "",
            "deadline": _dmy(deadline.group(1)) if deadline else "", "type": "First-stage researcher (R1)", "desc": body[:4000],
        })
    return out


SCRAPERS = {"jobs.ac.uk": jobs_ac_uk, "Inria": inria, "ELLIS": ellis, "Keejob": keejob, "HelloWork": hellowork,
            "jobs.ch": jobs_ch, "Job Bank": jobbank, "CNRS": cnrs,
            "Farojob": farojob, "Poli": poli, "LinkedIn posts": linkedin_posts,
            "Company boards": company_boards, "HN Who is hiring": hn_hiring, "Free-Work": free_work,
            "Berlin Startup Jobs": berlin_startup_jobs, "ETH Zurich": eth_zurich,
            "academics.de": academics_de, "Platsbanken": platsbanken, "Jobindex": jobindex, "EURAXESS": euraxess}
COUNTRY_WORDS = (("france", "fr"), ("germany", "de"), ("deutschland", "de"), ("switzerland", "ch"), ("schweiz", "ch"),
                 ("suisse", "ch"), ("canada", "ca"), ("tunisia", "tn"), ("tunisie", "tn"), ("belgium", "be"), ("belgique", "be"),
                 ("netherlands", "nl"), ("luxembourg", "lu"), ("sweden", "se"), ("denmark", "dk"), ("finland", "fi"),
                 ("norway", "no"), ("morocco", "ma"), ("maroc", "ma"), ("ireland", "ie"),
                 ("united kingdom", "uk"), ("england", "uk"), ("scotland", "uk"))


def _country(text):
    low = (text or "").lower()
    return next((c for w, c in COUNTRY_WORDS if w in low), "gl")


def _stealth_pages(urls, strict=True):
    """Loads pages in one stealth browser session (passes Cloudflare challenges). strict=False skips a page that
    fails instead of losing the whole run."""
    from scrapling.fetchers import StealthySession  # needs `scrapling install` (browser) on the runner
    pages = []
    with StealthySession(headless=True, solve_cloudflare=True, timeout=90000) as session:
        for url in urls:
            page = session.fetch(url, network_idle=True)
            if page.status != 200:
                if not strict and pages:
                    continue
                raise RuntimeError(f"HTTP {page.status} from {url.split('/')[2]}")
            pages.append(page)
            time.sleep(UA_PAUSE)
    return pages


def academic_positions(keywords):
    """Academic Positions: PhD, postdoc and faculty jobs in Europe (behind Cloudflare)."""
    out = []
    for page in _stealth_pages(["https://academicpositions.com/find-jobs?search=" + kw.replace(" ", "%20") for kw in keywords[:3]]):
        for a in page.css('a[href*="academicpositions.com/ad/"]'):
            if not a.css("h4"):
                continue
            card = a.parent
            for _ in range(4):  # climb to the card that also holds employer and location
                if card is None or card.css("a.job-link"):
                    break
                card = card.parent
            text = _t(card.get_all_text()) if card is not None else ""
            closing = re.search(r"Closing on:\s*(\d{4}-\d{2}-\d{2})", text)
            loc = ", ".join(_t(x).strip(", ") for x in card.css(".job-locations a::text").getall()) if card is not None else ""
            title = _t(a.css("h4::text").get())
            href = a.attrib.get("href", "")
            out.append({
                "id": "ap:" + href.rstrip("/").split("/")[-1], "title": title,
                "org": _t(card.css("a.job-link::text").get()) if card is not None else "", "location": loc, "c": _country(loc),
                "kind": "phd" if is_phd(title) else "job", "source": "Academic Positions",
                "url": href, "posted": "", "deadline": closing.group(1) if closing else "",
                "desc": _t(a.css("p::text").get())[:600],
            })
    return out


def scholarshipdb(keywords):
    """ScholarshipDB: PhD, postdoc and scholarship offers worldwide (behind Cloudflare)."""
    out = []
    for page in _stealth_pages(["https://scholarshipdb.net/scholarships?q=" + kw.replace(" ", "+") for kw in keywords[:3]]):
        for li in page.css("ul.list-unstyled > li"):
            a = li.css("h4 a")
            if not a:
                continue
            href = a[0].attrib.get("href", "")
            title = _t(a[0].get_all_text())
            city = _t(li.css("span.text-success::text").get())
            country = _t(li.css("a.text-success::text").get())
            orgs = [_t(x) for x in li.css("div > a:not(.text-success)::text").getall() if _t(x)]
            p = li.css("p")
            low = title.lower()
            out.append({
                "id": "sdb:" + href.rstrip("/").split("=")[-1], "title": title, "org": orgs[0] if orgs else "",
                "location": ", ".join(x for x in (city, country) if x), "c": _country(country),
                "kind": "phd" if is_phd(title) else "job", "source": "ScholarshipDB",
                "url": page.urljoin(href), "posted": "", "deadline": "", "desc": _t(p[0].get_all_text())[:600] if p else "",
            })
    return out


def stepstone(keywords):
    """StepStone, main German job board (behind bot protection)."""
    out = []
    urls = ["https://www.stepstone.de/jobs/" + re.sub(r"\s+", "-", kw.strip().lower()) for kw in keywords[:3]]
    for page in _stealth_pages(urls):
        for art in page.css('[data-at="job-item"]'):
            a = art.css('a[data-at="job-item-title"]')
            if not a:
                continue
            href = a[0].attrib.get("href", "")
            jid = re.search(r"--(\d+)-inline", href)
            out.append({
                "id": "stepstone:" + (jid.group(1) if jid else href), "title": _t(a[0].get_all_text()),
                "org": _t(art.css('[data-at="job-item-company-name"]')[0].get_all_text()) if art.css('[data-at="job-item-company-name"]') else "",
                "location": _t(art.css('[data-at="job-item-location"]')[0].get_all_text()) if art.css('[data-at="job-item-location"]') else "",
                "c": "de", "kind": "job", "source": "StepStone", "url": page.urljoin(href), "posted": "", "deadline": "",
                "desc": _t(art.css('[data-at="job-item-middle"]')[0].get_all_text())[:600] if art.css('[data-at="job-item-middle"]') else "",
            })
    return out


def tanitjobs(keywords, pages=2):
    """Tanitjobs, main Tunisian job board. Cloudflare blocks datacenter IPs, so this only works from a home
    connection: it runs in the PC collector (collect.py --home), not on GitHub. Reads the first pages of each
    keyword (20 offers a page), not just the first, so the stored count keeps up with what ages out."""
    out = []
    urls = ["https://www.tanitjobs.com/jobs/?keywords=" + kw.replace(" ", "+") + (f"&page={n}" if n > 1 else "")
            for kw in keywords[:8] for n in range(1, pages + 1)]
    for page in _stealth_pages(urls, strict=False):
        for card in page.css("div.sj-job-card"):
            a = card.css(".sj-card-title a")
            if not a:
                continue
            href = a[0].attrib.get("href", "")
            jid = re.search(r"/job/(\d+)/", href)
            date_txt = re.search(r"(\d{2})/(\d{2})/(\d{4})", " ".join(card.css(".sj-card-date ::text").getall()))
            tags = [_t(x) for x in card.css(".sj-card-tag::text").getall() if _t(x)]
            out.append({
                "id": "tanitjobs:" + (jid.group(1) if jid else href), "title": _t(a[0].get_all_text()),
                "org": _t(card.css(".sj-card-company a::text").get()), "location": _t(card.css(".sj-loc::text").get()),
                "c": "tn", "kind": "job", "source": "Tanitjobs", "url": href,
                "posted": f"{date_txt.group(3)}-{date_txt.group(2)}-{date_txt.group(1)}" if date_txt else "", "deadline": "",
                "type": " · ".join(tags[1:]), "desc": _t(card.css(".sj-card-desc::text").get())[:600],
            })
    return out


def tunisietravail(keywords, pages=8):
    """TunisieTravail, Tunisian job announcements ("X recrute Y"). Mostly non-IT, so it reads the newest pages
    and lets the relevance and field filters keep the IT and engineering ones. Run from the PC collector."""
    out, seen = [], set()
    for n in range(1, pages + 1):
        page = _get("https://www.tunisietravail.net/" + (f"page/{n}/" if n > 1 else ""))
        for art in page.css("article"):
            a = art.css("a.h1titleall")
            if not a:
                continue
            href, title = a[0].attrib.get("href", ""), _t(a[0].attrib.get("title") or a[0].get_all_text())
            if not href or href in seen:
                continue
            seen.add(href)
            org, _, role = title.partition(" recrute ")
            role = re.sub(r"^(des|un|une|le|la|les)\s+", "", role).strip() or title
            pid = re.search(r"-(\d+)/?$", href)
            out.append({
                "id": "tunisietravail:" + (pid.group(1) if pid else href), "title": role[:1].upper() + role[1:], "org": org.strip() if role != title else "",
                "location": "Tunisie" if not re.search(r"\b(france|canada|allemagne|qatar|arabie|emirats|dubai|europe)\b", title, re.I) else title.split("–")[-1].strip(),
                "c": "tn", "kind": "job", "source": "TunisieTravail", "url": href,
                "posted": "", "deadline": "", "type": "", "desc": _t(" ".join(art.css(".PostContent ::text, p::text").getall()))[:600],
            })
        time.sleep(1)
    return out


def emploitunisie(keywords, pages=5):
    """EmploiTunisie, Tunisian job board (behind Cloudflare: PC collector only). Its search is a posted form, so this
    reads the newest pages (25 offers each) and lets the relevance and field filters keep the IT ones."""
    out, seen = [], set()
    urls = ["https://www.emploitunisie.com/recherche-jobs-tunisie" + (f"?page={n}" if n else "") for n in range(pages)]
    for page in _stealth_pages(urls, strict=False):
        for card in page.css("div.card-job"):
            a = card.css("h3 a")
            href = a[0].attrib.get("href", "") if a else ""
            jid = re.search(r"-(\d+)$", href)
            if not jid or jid.group(1) in seen:
                continue
            seen.add(jid.group(1))
            facts = [_t(x.get_all_text()) for x in card.css("ul li")]
            region = next((f.split(":", 1)[1].strip() for f in facts if f.lower().startswith("région")), "")
            out.append({
                "id": "emploitunisie:" + jid.group(1), "title": _t(a[0].attrib.get("title") or a[0].get_all_text()),
                "org": _t(card.css(".card-job-company::text").get()), "location": region or "Tunisie", "c": "tn",
                "kind": "job", "source": "EmploiTunisie", "url": page.urljoin(href), "posted": "", "deadline": "",
                "type": " · ".join(f.split(":", 1)[1].strip() for f in facts if ":" in f and f.lower().startswith(("type", "contrat"))),
                "desc": _t(card.css(".card-job-description p::text").get())[:600],
            })
    return out


def bayt_tunisia(keywords):
    """Bayt, Middle East and North Africa job board, Tunisia listings (behind Cloudflare: PC collector only)."""
    out, seen = [], set()
    slugs = list(dict.fromkeys(re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-") for kw in keywords[:6]))
    for page in _stealth_pages([f"https://www.bayt.com/en/tunisia/jobs/{s}-jobs/" for s in slugs if s], strict=False):
        for li in page.css("li[data-js-job]"):
            a = li.css("h2 a")
            jid = li.attrib.get("data-job-id", "")
            if not a or not jid or jid in seen:
                continue
            seen.add(jid)
            out.append({
                "id": "bayt:" + jid, "title": _t(a[0].attrib.get("title") or a[0].get_all_text()),
                "org": _t(li.css(".job-company-location-wrapper a::text").get()), "location": "Tunisie", "c": "tn",
                "kind": "job", "source": "Bayt", "url": page.urljoin(a[0].attrib.get("href", "")), "posted": "", "deadline": "",
                "desc": _t(" ".join(li.css(".jb-descr::text").getall()))[:600],
            })
    return out


def duunitori(keywords):
    """Duunitori, the main Finnish job board (behind a bot check: stealth browser, home connection). Most offers
    are in Finnish; score.js recognises those as asking for Finnish."""
    out, year = [], date.today().year
    for page in _stealth_pages(["https://duunitori.fi/tyopaikat?haku=" + kw.replace(" ", "+") for kw in _english(keywords, 2)], strict=False):
        for box in page.css(".job-box"):
            a = box.css("a.job-box__hover")
            if not a or not a[0].attrib.get("data-id"):
                continue
            a = a[0]
            posted = re.search(r"(\d{1,2})\.(\d{1,2})\.", " ".join(box.css(".job-box__job-posted ::text").getall()))
            iso = ""
            if posted:
                d = date(year, int(posted.group(2)), int(posted.group(1)))
                iso = (d if d <= date.today() else date(year - 1, d.month, d.day)).isoformat()  # "6.10." has no year
            out.append({
                "id": "duunitori:" + a.attrib["data-id"], "title": _t(box.css(".job-box__title ::text").get() or a.get_all_text()),
                "org": _t(a.attrib.get("data-company")), "location": _t(" ".join(box.css(".job-box__job-location ::text").getall())).strip(" –"),
                "c": "fi", "kind": "phd" if is_phd(a.get_all_text()) else "job", "source": "Duunitori",
                "url": page.urljoin(a.attrib.get("href", "")), "posted": iso, "deadline": "", "type": "", "desc": "",
            })
    return out


def emploi_ma(keywords):
    """Emploi.ma, a main Moroccan job board (Cloudflare challenge: stealth browser, home connection)."""
    out = []
    words = list(dict.fromkeys(["python", "data", "intelligence artificielle"] + [k for k in keywords if "ia" in k.lower().split()][:1]))
    for page in _stealth_pages(["https://www.emploi.ma/recherche-jobs-maroc/" + requests.utils.quote(w) for w in words], strict=False):
        for card in page.css("div.card-job-detail"):
            a = [x for x in card.css("a") if "/offre-emploi-maroc/" in x.attrib.get("href", "") and _t(x.get_all_text())]
            if not a:
                continue
            href = a[0].attrib["href"]
            jid = re.search(r"-(\d+)$", href.rstrip("/"))
            title = _t(a[0].get_all_text())
            text = _t(card.get_all_text())
            city = re.search(r"\b(Casablanca|Rabat|Marrakech|Tanger|F[eè]s|Agadir|Mekn[eè]s|Oujda|K[ée]nitra|T[ée]touan|Sal[ée]|Mohammedia|El Jadida|Benguerir)\b", text, re.I)
            # The company is the first short text after the title in the card.
            org = next((s for s in (_t(x) for x in card.css("::text").getall()) if s and s != title and len(s) < 60), "")
            out.append({
                "id": "emploima:" + (jid.group(1) if jid else href), "title": title, "org": org,
                "location": city.group(1) if city else "Maroc", "c": "ma", "kind": "phd" if is_phd(title) else "job", "source": "Emploi.ma",
                "url": page.urljoin(href), "posted": "", "deadline": "", "type": "", "desc": text[len(title):][:1500].strip(),
            })
    return out


WTTJ_SLUG = re.compile(r"machine-learning|data-scien|data-engineer|data-analy|(^|[-_])(ia|ai|ml)([-_]|$)|llm|genai|gen-ai|python|"
                       r"deep-learning|nlp|computer-vision|mlops|intelligence-artificielle|vision-par-ordinateur")
WTTJ_JUNIOR = re.compile(r"junior|graduate|debutant|jeune-diplome|entry|(^|[-_])vie([-_]|$)")
WTTJ_STUDENT = re.compile(r"stage|stagiaire|intern|alternan|apprenti")  # need student status: read last
WTTJ_COUNTRIES = {"FR": "fr", "BE": "be", "NL": "nl", "LU": "lu", "DE": "de", "CH": "ch", "CA": "ca", "SE": "se", "DK": "dk",
                  "NO": "no", "FI": "fi", "MA": "ma", "IE": "ie", "TN": "tn"}
WTTJ_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
WTTJ_SEEN = os.path.join(os.path.expanduser("~"), "parcours-collector", "wttj-seen.json")


def welcome_to_the_jungle(keywords, limit=50):
    """Welcome to the Jungle (startups and tech, mostly France). Its search needs an account, but its sitemaps list
    every public offer (about 90k) with the title and city in the link. Offers whose link reads like AI / data /
    Python are opened in a stealth browser (a bot check clears after a few seconds) for their JobPosting data;
    junior and graduate ones first, internships and work-study last (they need student status). Links already
    opened are remembered in WTTJ_SEEN on this PC, so each run reads `limit` new ones. Home connection only."""
    import gzip
    import html
    links = []
    for i in range(10):
        r = requests.get(f"https://www.welcometothejungle.com/sitemaps/job-listings.{i}.xml.gz", headers=WTTJ_UA, timeout=60)
        if r.status_code != 200:
            break
        body = r.content.decode(errors="ignore") if r.content[:2] == b"<?" else gzip.decompress(r.content).decode()
        links += re.findall(r"<loc>([^<]+/jobs/[^<]+)</loc>", body)
    # Matched on the link's own words (broad search keywords like "développeur" would take in every developer job).
    wanted = [u for u in links if WTTJ_SLUG.search(u.split("/jobs/")[1])]
    try:
        seen = json.load(open(WTTJ_SEEN))
    except (OSError, ValueError):
        seen = {}
    rank = lambda u: 0 if WTTJ_JUNIOR.search(u) else 2 if WTTJ_STUDENT.search(u) else 1
    todo = sorted((u for u in wanted if u not in seen), key=rank)[:limit]
    out = []
    if todo:
        from scrapling.fetchers import StealthySession
        with StealthySession(headless=True, timeout=60000) as session:
            for u in todo:
                try:
                    page = session.fetch(u, network_idle=True, wait=8000)
                except Exception:
                    continue  # tried again next run
                job = None
                for raw in page.css('script[type="application/ld+json"]::text').getall():
                    try:
                        d = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(d, dict) and d.get("@type") == "JobPosting":
                        job = d
                if page.status == 200 and not job:
                    continue  # bot check not cleared: tried again next run
                seen[u] = int(time.time())
                if not job:
                    continue
                places = job.get("jobLocation") or []
                places = places if isinstance(places, list) else [places]
                addr = [(p.get("address") or {}) for p in places if isinstance(p, dict)]
                c = next((WTTJ_COUNTRIES[a.get("addressCountry")] for a in addr if a.get("addressCountry") in WTTJ_COUNTRIES), None)
                valid = (job.get("validThrough") or "")[:10]
                if not c or (valid and valid < date.today().isoformat()):
                    continue
                desc = html.unescape(re.sub(r"<[^>]+>", " ", job.get("description") or ""))
                out.append({
                    "id": "wttj:" + u.split("/companies/")[1], "title": _t(job.get("title")),
                    "org": _t((job.get("hiringOrganization") or {}).get("name")),
                    "location": ", ".join(dict.fromkeys(_t(a.get("addressLocality")) for a in addr if a.get("addressLocality"))),
                    "c": c, "kind": "job", "source": "Welcome to the Jungle", "url": u,
                    "posted": (job.get("datePosted") or "")[:10], "deadline": valid,
                    "type": _t(job.get("employmentType") if isinstance(job.get("employmentType"), str) else " · ".join(job.get("employmentType") or [])),
                    "desc": _t(desc)[:4000],
                })
    os.makedirs(os.path.dirname(WTTJ_SEEN), exist_ok=True)
    json.dump({u: t for u, t in seen.items() if t > time.time() - 120 * 86400}, open(WTTJ_SEEN, "w"))
    return out


# Browser-based (StealthyFetcher). Only run where a browser is installed (STEALTH=1 in the workflow).
STEALTH_SCRAPERS = {"ABG": abg, "Academic Positions": academic_positions, "ScholarshipDB": scholarshipdb, "StepStone": stepstone}
# Need a home IP (blocked from datacenters). Run by the PC collector: collect.py --home.
HOME_SCRAPERS = {"Tanitjobs": tanitjobs, "TunisieTravail": tunisietravail, "EmploiTunisie": emploitunisie, "Bayt": bayt_tunisia,
                 "Welcome to the Jungle": welcome_to_the_jungle, "Duunitori": duunitori, "Emploi.ma": emploi_ma}
