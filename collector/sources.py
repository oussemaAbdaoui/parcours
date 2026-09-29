"""Scrapers for PhD, master's and job platforms, built on Scrapling (BSD-3, github.com/D4Vinci/Scrapling).

Only plain HTTP fetching of public listing pages that the site's robots.txt allows. No stealth browser,
no CAPTCHA or Cloudflare bypass: sites that block automated access (Academic Positions, ABG, FindAPhD,
Tanitjobs) or disallow it in robots.txt (Euraxess) are covered through their email alerts and the Gmail scan.

Every scraper returns a list of dicts: id, title, org, location, c, kind, source, url, posted, deadline, desc.
"""
import re
import time
from datetime import date, datetime

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
            where = next((s for s in spans if s and not re.search(r"\d{4}|/", s) and len(s) < 30), "")
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


SCRAPERS = {"jobs.ac.uk": jobs_ac_uk, "Inria": inria, "ELLIS": ellis, "Keejob": keejob}
# Browser-based (StealthyFetcher). Only run where a browser is installed (STEALTH=1 in the workflow).
STEALTH_SCRAPERS = {"ABG": abg}
