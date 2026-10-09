"""Master's programmes and scholarships in Germany, France and Italy (plus EU-wide Erasmus Mundus), matched to the profile.

All sources are official and public, read over plain HTTP:
- DAAD International Programmes (Germany): JSON search the DAAD site itself uses.
- DAAD scholarship database (Germany): the data file behind the DAAD search page, filtered to graduates from your
  country, for study, in your subject groups.
- Mon Master open data (France): the ministry's dataset of national master's, with applicants, seats and offers.
- CampusBourses (France): Campus France's scholarship directory API, master's level, open to your nationality.
- Universitaly (Italy): the ministry portal's course search, second-cycle (Magistrale) degrees.
- Erasmus Mundus catalogue (EU): joint master's run across several countries, most with full scholarships.

Stored apart from job offers (programmes stay open for months and need no job dealbreakers) in the hash
parcours:masters:items, refreshed at most once a day.
"""
import json
import re
import time
import urllib.parse
from html import unescape

import requests

ITEMS_KEY, META_KEY = "parcours:masters:items", "parcours:masters:meta"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36",
      "Accept-Language": "en,fr;q=0.8"}
TUNISIA = {"daad": 189, "campusfrance": "60"}

# Profile skill families -> what to look for in programme names, in English, French and Italian.
FIELDS = {
    "ai": (["artificial intelligence", "machine learning", "data science", "computer science", "informatics", "robotics"],
           ["intelligence artificielle", "informatique", "science des données", "apprentissage", "mathématiques appliquées"],
           ["artificial intelligence", "computer science", "data science", "intelligenza artificiale", "informatica"]),
    "data": (["data science", "data engineering", "statistics", "business analytics"],
             ["science des données", "statistique", "big data"],
             ["data science", "statistica", "data analytics"]),
    "software": (["computer science", "software engineering", "informatics", "computer engineering"],
                 ["informatique", "génie logiciel"],
                 ["computer science", "ingegneria informatica", "informatica"]),
}
DEFAULT_FAMILIES = ["ai", "software"]
NOISE = re.compile(r"\b(art|arts|music|nursing|law|theology|dentistry|veterinary)\b", re.I)


def _get(url, **kw):
    r = requests.get(url, headers=dict(UA, **kw.pop("headers", {})), timeout=kw.pop("timeout", 45), **kw)
    r.raise_for_status()
    return r


def _clean(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def profile_fields(profile):
    """Which subject families to search, from the profile's skills, roles and degree field."""
    p = profile or {}
    text = " ".join([*(p.get("skills") or []), *(p.get("roles") or []), p.get("field") or "", p.get("cv") or ""][:400]).lower()
    fams = []
    if re.search(r"machine learning|deep learning|\bllm|\bai\b|artificial intelligence|nlp|computer vision|explainab", text):
        fams.append("ai")
    if re.search(r"data science|data engineer|statistic|analytics|sql|spark", text):
        fams.append("data")
    if re.search(r"software|backend|frontend|java|python|web|devops", text):
        fams.append("software")
    return fams or DEFAULT_FAMILIES


def terms_for(fams, lang):
    i = {"en": 0, "fr": 1, "it": 2}[lang]
    return list(dict.fromkeys(t for f in fams for t in FIELDS[f][i]))


def languages(profile):
    langs = {"en"}
    for l in (profile or {}).get("languages") or []:
        code = (l.get("code") if isinstance(l, dict) else str(l))[:2].lower()
        langs.add(code)
    return langs


def _matches(text, terms):
    low = f" {text.lower()} "
    return [t for t in terms if t in low]


# ---------- Germany ----------

def daad_programmes(fams, langs):
    out, seen = [], set()
    lang_ids = ["2"] + (["1"] if "de" in langs else [])  # 2 = English, 1 = German
    for q in terms_for(fams, "en")[:5]:
        params = [("degree[]", "2"), ("q", q), ("limit", "60"), ("offset", "0"), ("display", "list")] + [("lang[]", l) for l in lang_ids]
        data = _get("https://www2.daad.de/deutschland/studienangebote/international-programmes/api/solr/en/search.json", params=params).json()
        for c in data.get("courses", []):
            if c["id"] in seen or NOISE.search(c.get("courseName", "")):
                continue
            seen.add(c["id"])
            name = c.get("courseName", "")
            hit = _matches(f"{name} {c.get('subject') or ''}", terms_for(fams, "en"))
            if not hit:
                continue
            out.append({
                "id": f"daadp:{c['id']}", "type": "program", "country": "de", "source": "DAAD",
                "title": name, "org": c.get("academy", ""), "city": c.get("city", ""),
                "lang": ", ".join(c.get("languages") or []), "tuition": c.get("tuitionFees") or c.get("costString") or "",
                "duration": c.get("programmeDuration") or "", "start": c.get("beginning") or "",
                "deadlineText": _clean(c.get("applicationDeadline")), "deadline": _deadline_from_text(c.get("applicationDeadline")),
                "url": "https://www2.daad.de" + (c.get("link") or ""), "terms": hit,
                "desc": "; ".join(c.get("supportInternationalStudents") or [])[:400],
            })
    return out


def _taffy(name):
    t = _get("https://www2.daad.de/bundles/daadstipendiendatenbanklsh/data/a/js/" + name, timeout=90).text
    return json.loads(t[t.index("TAFFY(") + 6: t.rindex(")")])


def daad_scholarships(fams, origin=TUNISIA["daad"]):
    groups = {"C", "F"} | ({"B"} if "data" in fams else set())  # C maths/natural sciences, F engineering, B economics
    out = []
    for s in _taffy("scholarships.js"):
        if origin not in (s.get("origin") or []) or 3 not in (s.get("status") or []):  # 3 = graduates (master's level)
            continue
        if 1 not in (s.get("intentions") or [1]) or not set(s.get("subjectGrps") or []) & groups:  # 1 = study
            continue
        prog = s.get("sapProgid")
        out.append({
            "id": f"daads:{prog}", "type": "scholarship", "country": "de", "source": "DAAD scholarships",
            "title": s.get("nameEn") or s.get("nameDe", ""), "org": "DAAD" if s.get("isDaad") else (s.get("nameEn", "").split(":")[0]),
            "city": "", "lang": "", "url": "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/"
            f"?status=3&origin={origin}&subjectGrps=&daad=&q=&page=1&detail={prog}",
            "desc": _clean((s.get("introduction") or {}).get("en") if isinstance(s.get("introduction"), dict) else s.get("introduction"))[:600], "deadline": "", "deadlineText": "",
            "eligible": "Graduates from Tunisia", "terms": [],
        })
    return out


# ---------- France ----------

def mon_master(fams):
    base = "https://data.enseignementsup-recherche.gouv.fr/api/explore/v2.1/catalog/datasets/fr-esr-mon_master/records"
    out, seen = [], set()
    terms = terms_for(fams, "fr")
    for t in terms[:5]:
        where = f'search(mention, "{t}") or search(parcours, "{t}")'
        data = _get(base, params={"where": where, "limit": 100, "order_by": "n_can_pp desc"}).json()
        for r in data.get("results", []):
            key = r.get("ifc") or f"{r.get('inmp')}:{r.get('eta_uai')}"
            if key in seen:
                continue
            seen.add(key)
            title = (r.get("parcours") or r.get("mention") or "").strip()
            mention = (r.get("mention") or "").title()
            hit = _matches(f"{title} {mention}", terms)
            if not hit:
                continue
            applicants = (r.get("n_can_pp") or 0) + (r.get("n_can_pc") or 0)
            offers, seats = r.get("n_prop_total"), r.get("col")
            city = re.sub(r"\s*\(\d+\)$", "", (r.get("lieux") or "").split("|")[0].split(" - ")[-1]).title()
            q = urllib.parse.quote(f'master "{title}" {r.get("eta_nom", "")}')
            out.append({
                "id": f"mm:{key}", "type": "program", "country": "fr", "source": "Mon Master",
                "title": f"{mention}: {title}" if mention and mention.lower() not in title.lower() else title,
                "org": r.get("eta_nom", ""), "city": city, "lang": "French",
                "tuition": "National fees (higher for non-EU unless exempted)",
                "url": f"https://www.google.com/search?q={q}", "terms": hit,
                "competition": {"applicants": applicants, "seats": seats, "offers": offers,
                                "rate": round(100 * offers / applicants) if applicants and offers else None,
                                "session": r.get("session")},
                "alternance": r.get("alternance") == "1",
                "desc": "Figures from the last Mon Master session. Applicants from outside the EU usually apply through "
                        "Études en France (Campus France) instead of Mon Master.",
                "deadline": "", "deadlineText": "",
            })
    return out


def campus_bourses(country=TUNISIA["campusfrance"]):
    data = _get("https://bourses-api.campusfrance.org/sgetgrants/en", headers={"Referer": "https://campusbourses.campusfrance.org/"}).json()
    out = []
    for p in data.get("programs", []):
        levels = (p.get("levelListId") or "").split(",")
        countries = [c for c in (p.get("countryListId") or "").split(",") if c]
        if "2" not in levels or (countries and country not in countries):  # 2 = master's; no list = every nationality
            continue
        out.append({
            "id": f"cb:{p['bourseId']}", "type": "scholarship", "country": "fr", "source": "Campus France",
            "title": p.get("title", ""), "org": "", "city": "", "lang": "",
            "url": f"https://campusbourses.campusfrance.org/#/program/{p['bourseId']}",
            "desc": _clean(p.get("synthese"))[:600], "deadline": (p.get("endAt") or "")[:10], "deadlineText": "",
            "eligible": "Open to Tunisians" if countries else "Open to all nationalities", "terms": [],
        })
    return out


# ---------- Italy ----------

def universitaly(fams, langs):
    out, seen = [], set()
    for q in terms_for(fams, "it")[:5]:
        data = _get("https://universitaly-backend.cineca.it/api/offerta-formativa/cerca-corsi",
                    params={"searchText": q, "tipoClasse": 0, "order": "RND"},
                    headers={"Origin": "https://www.universitaly.it", "Referer": "https://www.universitaly.it/", "Accept": "application/json"}).json()
        uni = data.get("universita") or {}
        for c in uni.get("corsi") or []:
            if c["id"] in seen or (c.get("tipoLaurea") or {}).get("descrizione") not in ("Magistrale", "Magistrale a ciclo unico"):
                continue
            lang = (c.get("lingua") or "").upper()
            if lang != "EN" and not (lang == "IT" and "it" in langs):
                continue
            seen.add(c["id"])
            name = c.get("nomeCorsoEn") or c.get("nomeCorso") or ""
            hit = _matches(f"{name} {c.get('nomeCorso') or ''}", terms_for(fams, "it"))
            if not hit:
                continue
            org = re.sub(r"\s+", " ", (c.get("nomeStruttura") or "").replace("�", "à"))
            out.append({
                "id": f"uit:{c['id']}", "type": "program", "country": "it", "source": "Universitaly",
                "title": name, "org": org, "city": (c.get("sede") or {}).get("comuneDescrizione") or "",
                "lang": {"EN": "English", "IT": "Italian"}.get(lang, lang), "duration": f"{c.get('durataAnni')} years" if c.get("durataAnni") else "",
                "url": c.get("url") or "https://www.universitaly.it/", "terms": hit,
                "desc": f"Class {((c.get('classe') or {}).get('codice') or '').strip()}. Italian regional DSU scholarships "
                        "(fee waiver, grant, housing) are open to international students; apply to the region's DSU office.",
                "deadline": "", "deadlineText": "",
            })
    return out


# Italy has no national scholarship database: these are the official recurring schemes open to international
# master's students (URLs checked). Calls open once a year; the dates are on each site.
ITALY_SCHEMES = [
    ("Italian Government (MAECI) scholarships for international students", "Ministry of Foreign Affairs", "Italy",
     "https://studyinitaly.esteri.it/", "Scholarships for foreign students enrolling in Italian master's programmes. The call is published once a year on Study in Italy."),
    ("ER.GO regional scholarship (Emilia-Romagna: Bologna, Modena, Parma, Ferrara)", "ER.GO", "Bologna",
     "https://www.er-go.it/", "Means-tested DSU grant with fee waiver and housing priority for students at universities in Emilia-Romagna, international students included."),
    ("EDISU regional scholarship (Piedmont: Turin, Politecnico di Torino)", "EDISU Piemonte", "Turin",
     "https://www.edisu.piemonte.it/", "Means-tested DSU grant, canteen and housing for students in Piedmont, international students included."),
    ("DiSCo regional scholarship (Lazio: Rome universities)", "DiSCo Lazio", "Rome",
     "https://laziodisco.it/", "Means-tested DSU grant and housing for students at universities in Lazio, international students included."),
    ("DSU Toscana regional scholarship (Florence, Pisa, Siena)", "DSU Toscana", "Florence",
     "https://www.dsu.toscana.it/", "Means-tested DSU grant and housing for students in Tuscany, international students included."),
    ("ESU Padova regional scholarship (Veneto: University of Padua)", "ESU Padova", "Padua",
     "https://www.esu.pd.it/", "Means-tested DSU grant and housing for students in Padua, international students included."),
]


def italy_schemes():
    return [{"id": "itsch:" + re.sub(r"\W+", "-", org.lower()), "type": "scholarship", "country": "it", "source": "Italy (official)",
             "title": title, "org": org, "city": city, "lang": "", "url": url, "desc": desc, "deadline": "",
             "deadlineText": "Yearly call, see the site", "eligible": "Open to international students", "terms": []}
            for title, org, city, url, desc in ITALY_SCHEMES]


# ---------- EU ----------

def erasmus_mundus(fams):
    terms = terms_for(fams, "en") + ["data", "computing", "intelligent", "digital", "cyber", "robot", "software", "information"]
    cards, seen = [], set()
    for page in range(0, 15):  # the catalogue shows 20 programmes per page
        s = _get("https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en" + (f"?page={page}" if page else "")).text
        found = re.findall(r'<a\s+href="([^"]+)"[^>]*?data-ecl-title-link\s*>\s*<span\s+class="ecl-link__label">(.*?)</span>'
                           r'.*?ecl-content-block__description">\s*<p>(.*?)<br', s, re.S)
        found = [f for f in found if f[0] not in seen]
        if not found:
            break
        seen.update(f[0] for f in found)
        cards += found
        time.sleep(0.5)
    out = []
    for url, title, acr in cards:
        title, acr = _clean(title), _clean(acr)
        hit = _matches(title, terms)
        if not hit:
            continue
        out.append({
            "id": "em:" + re.sub(r"\W+", "-", title.lower())[:60], "type": "program", "country": "eu", "source": "Erasmus Mundus",
            "title": title, "org": acr.replace(" - Project overview", ""), "city": "Several countries", "lang": "English",
            "url": url, "terms": hit, "scholarship": True,
            "desc": "Joint master's taught in several European countries. Erasmus Mundus scholarships cover tuition, travel and a monthly "
                    "allowance for the best applicants. Applications usually run from October to January.",
            "deadline": "", "deadlineText": "Usually October to January",
        })
    return out


MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                      "october", "november", "december"], 1)}


def _deadline_from_text(s):
    """'Register by 15 January 2027 + 1 more' -> '2027-01-15' (first date only)."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s or "")
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return ""


SOURCES = [
    ("DAAD programmes", lambda f, l: daad_programmes(f, l)),
    ("DAAD scholarships", lambda f, l: daad_scholarships(f)),
    ("Mon Master", lambda f, l: mon_master(f)),
    ("Campus France", lambda f, l: campus_bourses()),
    ("Universitaly", lambda f, l: universitaly(f, l)),
    ("Italy schemes", lambda f, l: italy_schemes()),
    ("Erasmus Mundus", lambda f, l: erasmus_mundus(f)),
]


# DAAD answers 403 to GitHub's servers: the PC refreshes these two (masters.py --home), the cloud the rest.
HOME_SOURCES = {"DAAD programmes", "DAAD scholarships"}


def collect(profile, only=None):
    fams, langs = profile_fields(profile), languages(profile)
    items, status = [], {}
    for name, fn in SOURCES:
        if only and name not in only:
            continue
        try:
            found = fn(fams, langs)
            status[name] = {"ok": True, "count": len(found)}
            items += found
        except Exception as e:  # one source failing should not stop the rest
            status[name] = {"ok": False, "count": 0, "error": str(e)[:160]}
        time.sleep(1)
    return items, status, fams


def run(store, state, dry=False, force=False, only=None):
    """Refreshes the master's store at most once a day (only: just those sources, whenever asked, leaving the daily
    refresh to the cloud). Returns a status line for the run report."""
    now = int(time.time() * 1000)
    meta = (store.get_json(META_KEY) if store else None) or {}
    if not force and not only and now - meta.get("at", 0) < 20 * 3600 * 1000:
        return {"ok": True, "count": meta.get("count", 0), "error": "fresh, next refresh within a day"}
    items, status, fams = collect(state.get("profile"), only or {n for n, _ in SOURCES} - HOME_SOURCES)
    for name, st in status.items():
        print(f"  {name:18} {'ok ' if st['ok'] else 'ERR'} {st['count']:4}  {st.get('error', '')}")
    if dry or not store:
        for x in items[:12]:
            print(f"  [{x['type'][:4]}] {x['country']} {x['source']:16} {x['title'][:60]:60} | {x.get('org', '')[:30]}")
        return {"ok": True, "count": len(items)}
    flat = store.cmd("HGETALL", ITEMS_KEY) or []
    old = {flat[i]: json.loads(flat[i + 1]) for i in range(0, len(flat), 2)}
    fresh = {x["id"] for x in items}
    batch = []
    for x in items:
        x["foundAt"] = old.get(x["id"], {}).get("foundAt", now)
        x["seenAt"] = now
        batch += [x["id"], json.dumps(x, ensure_ascii=False)]
        if len(batch) >= 80:
            store.cmd("HSET", ITEMS_KEY, *batch)
            batch = []
    if batch:
        store.cmd("HSET", ITEMS_KEY, *batch)
    ok_sources = {x["source"] for x in items}
    # Drop entries a source no longer lists, but only for sources that answered this time.
    gone = [i for i, x in old.items() if i not in fresh and x.get("source") in ok_sources]
    for i in range(0, len(gone), 100):
        store.cmd("HDEL", ITEMS_KEY, *gone[i:i + 100])
    meta["sources"] = {**meta.get("sources", {}), **status}
    if not only:
        meta.update({"at": now, "count": len(items), "fields": fams})
    store.cmd("SET", META_KEY, json.dumps(meta))
    return {"ok": all(s["ok"] for s in status.values()), "count": len(items),
            **({"error": ", ".join(n for n, s in status.items() if not s["ok"]) + " failed"} if not all(s["ok"] for s in status.values()) else {})}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if "--home" in sys.argv:  # PC task "Parcours masters": the sources that block the cloud, into the shared store
        from collect import STATE_KEY, Store, load_env
        env = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--env=")), "")
        if env:
            load_env(env)
        st = Store()
        print(time.strftime("%Y-%m-%d %H:%M"), run(st, st.get_json(STATE_KEY) or {}, only=HOME_SOURCES))
        sys.exit(0)
    prof = {"skills": ["machine learning", "python", "deep learning", "llm"], "languages": ["en", "fr"]}
    its, st, f = collect(prof)
    print("fields:", f)
    for n, s in st.items():
        print(f"{n:18} {'ok ' if s['ok'] else 'ERR'} {s['count']:4} {s.get('error', '')}")
    for src in {x["source"] for x in its}:
        for x in [i for i in its if i["source"] == src][:3]:
            print(f"  [{x['type'][:4]}] {x['country']} {src:16} {x['title'][:70]:70} | {x.get('org', '')[:28]} | {x.get('deadline') or x.get('deadlineText', '')}")
