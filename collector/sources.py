"""Scrapers for PhD, master's and job platforms, built on Scrapling (BSD-3, github.com/D4Vinci/Scrapling).

SCRAPERS use Scrapling's plain HTTP fetcher (or a site's public API/RSS) on pages the site's robots.txt allows.
STEALTH_SCRAPERS use StealthyFetcher, a real browser that passes Cloudflare challenges (ABG). Sites that block
GitHub's IP addresses outright (FindAPhD, Tanitjobs, MastersPortal, ZipRecruiter...) cannot be reached from there,
and Euraxess disallows its search in robots.txt; their email alerts reach the app through the Gmail scan.

Every scraper returns a list of dicts: id, title, org, location, c, kind, source, url, posted, deadline, desc.
"""
import json
import re
import time
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
            kind = "phd" if "phd" in low or "doctoral" in low else "job"
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


def max_planck(keywords):
    """Max Planck Society job board (Germany): PhD, postdoc and research positions across institutes."""
    out = []
    page = _get("https://www.mpg.de/stellenboerse")
    for li in page.css("li.teaser"):
        a = li.css("h3 a")
        href = a[0].attrib.get("href", "") if a else ""
        if "/job-" not in href:
            continue
        box = li.css(".text-box")
        texts = [_t(x) for x in (box[0].css("div::text").getall() if box else []) if _t(x)]
        inst = texts[-1] if texts else ""
        title = _t(a[0].get_all_text())
        out.append({
            "id": "mpg:" + href.split("job-")[-1], "title": title, "org": inst.split(",")[0],
            "location": inst.split(",")[-1].strip() if "," in inst else "", "c": "de",
            "kind": "phd" if re.search(r"phd|doktorand|doctoral", title.lower()) else "job", "source": "Max Planck",
            "url": page.urljoin(href), "posted": _long_date(li.css(".date::text").get()), "deadline": "", "desc": "",
        })
    return out


def jobrxiv(keywords):
    """jobRxiv: academic jobs board (PhD, postdoc, faculty), worldwide."""
    out = []
    for kw in keywords[:3]:
        page = _get("https://jobrxiv.org/?s=" + kw.replace(" ", "+"))
        for art in page.css("article.job_listing"):
            a = art.css("section.post-content > a")
            if not a:
                continue
            cls = art.attrib.get("class", "")
            region = re.search(r"job_listing_region-([\w-]+)", cls)
            out.append({
                "id": "jobrxiv:" + (art.attrib.get("id", "") or a[0].attrib.get("href", "")), "title": _t(a[0].get_all_text()),
                "org": _t(art.css(".author-link::text").get()),
                "location": region.group(1).replace("-", " ").title() if region else "", "c": "gl",
                "kind": "phd" if "job_listing_category-phd" in cls else "job", "source": "jobRxiv",
                "url": a[0].attrib.get("href", ""), "posted": "", "deadline": "",
                "desc": _t(art.css("section.post-content > p::text").get())[:600],
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


def himalayas(keywords):
    """Himalayas remote jobs (public API, newest first)."""
    out = []
    for j in _json("https://himalayas.app/jobs/api?limit=100").get("jobs", []):
        pub = j.get("pubDate")
        out.append({
            "id": "himalayas:" + str(j.get("guid") or j.get("applicationLink")), "title": _t(j.get("title")),
            "org": _t(j.get("companyName")), "location": ", ".join(j.get("locationRestrictions") or []) or "Remote",
            "c": "gl", "kind": "job", "source": "Himalayas", "url": j.get("applicationLink") or j.get("guid") or "",
            "posted": datetime.fromtimestamp(pub, timezone.utc).date().isoformat() if isinstance(pub, (int, float)) else str(pub or "")[:10],
            "deadline": "", "type": _t(j.get("employmentType")), "desc": _t(j.get("excerpt"))[:600],
        })
    return out


def jobicy(keywords):
    """Jobicy remote jobs (public API; credited as the source, links go to the original offer)."""
    return [{
        "id": "jobicy:" + str(j.get("id")), "title": _strip_html(j.get("jobTitle")), "org": _t(j.get("companyName")),
        "location": _t(j.get("jobGeo")) or "Remote", "c": "gl", "kind": "job", "source": "Jobicy", "url": j.get("url", ""),
        "posted": str(j.get("pubDate", ""))[:10], "deadline": "", "type": _t(" ".join(j.get("jobType") or [])),
        "desc": _strip_html(j.get("jobExcerpt"))[:600],
    } for j in _json("https://jobicy.com/api/v2/remote-jobs?count=50").get("jobs", [])]


def working_nomads(keywords):
    """Working Nomads remote jobs (public API)."""
    return [{
        "id": "wn:" + j.get("url", ""), "title": _t(j.get("title")), "org": _t(j.get("company_name")),
        "location": _t(j.get("location")) or "Remote", "c": "gl", "kind": "job", "source": "Working Nomads",
        "url": j.get("url", ""), "posted": str(j.get("pub_date", ""))[:10], "deadline": "", "type": _t(j.get("category_name")),
        "desc": _strip_html(j.get("description"))[:600],
    } for j in _json("https://www.workingnomads.com/api/exposed_jobs/")]


def _rss_field(item, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S)
    return _t(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))) if m else ""


def we_work_remotely(keywords):
    """We Work Remotely, official RSS feed for programming jobs."""
    page = _get("https://weworkremotely.com/categories/remote-programming-jobs.rss")
    xml = page.body.decode("utf8", "replace") if isinstance(page.body, bytes) else str(page.body)
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        full, link = _rss_field(item, "title"), _rss_field(item, "link")
        org, _, title = full.partition(": ")
        try:
            posted = datetime.strptime(_rss_field(item, "pubDate")[:25].strip(), "%a, %d %b %Y %H:%M:%S").date().isoformat()
        except ValueError:
            posted = ""
        out.append({
            "id": "wwr:" + link, "title": title or full, "org": org if title else "",
            "location": _rss_field(item, "region") or "Remote", "c": "gl", "kind": "job", "source": "We Work Remotely",
            "url": link, "posted": posted, "deadline": "", "desc": _strip_html(_rss_field(item, "description"))[:600],
        })
    return out


SCRAPERS = {"jobs.ac.uk": jobs_ac_uk, "Inria": inria, "ELLIS": ellis, "Keejob": keejob, "HelloWork": hellowork,
            "jobs.ch": jobs_ch, "Job Bank": jobbank, "CNRS": cnrs, "Max Planck": max_planck, "jobRxiv": jobrxiv,
            "Farojob": farojob, "Himalayas": himalayas, "Jobicy": jobicy, "Working Nomads": working_nomads,
            "We Work Remotely": we_work_remotely}
COUNTRY_WORDS = (("france", "fr"), ("germany", "de"), ("deutschland", "de"), ("switzerland", "ch"), ("schweiz", "ch"),
                 ("suisse", "ch"), ("canada", "ca"), ("tunisia", "tn"), ("tunisie", "tn"))


def _country(text):
    low = (text or "").lower()
    return next((c for w, c in COUNTRY_WORDS if w in low), "gl")


def _stealth_pages(urls):
    """Loads pages in one stealth browser session (passes Cloudflare challenges)."""
    from scrapling.fetchers import StealthySession  # needs `scrapling install` (browser) on the runner
    pages = []
    with StealthySession(headless=True, solve_cloudflare=True, timeout=90000) as session:
        for url in urls:
            page = session.fetch(url, network_idle=True)
            if page.status != 200:
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
                "kind": "phd" if re.search(r"\bph\.?d\b|doctoral", title.lower()) else "job", "source": "Academic Positions",
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
                "kind": "phd" if re.search(r"\bph\.?d\b|doctoral|doctorate", low) else "job", "source": "ScholarshipDB",
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


# Browser-based (StealthyFetcher). Only run where a browser is installed (STEALTH=1 in the workflow).
STEALTH_SCRAPERS = {"ABG": abg, "Academic Positions": academic_positions, "ScholarshipDB": scholarshipdb, "StepStone": stepstone}
