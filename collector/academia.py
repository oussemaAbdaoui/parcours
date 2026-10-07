"""Schools and professors in your countries, for master's, PhD and scholarship applications. Three engines:

1. Schools: every university, school and research facility from ROR (the Research Organization Registry), ranked by
   recent computer-science output and by papers on your own topics (OpenAlex). The app joins them with the master's
   programmes and scholarships of masters.py by name.
2. Professors: researchers publishing on your profile's topics in each country (OpenAlex works of the last three
   years), scored on topic fit, how often they lead papers as last author (usually the supervisor), activity and
   impact, plus, in France, the PhD theses they directed (theses.fr).
3. Contacts: a public ORCID email or homepage, an email read from that homepage, or one printed on the first page of
   their own arXiv papers and matched to their name. When colleagues at the same school all use first.last@domain,
   a guessed address in that format, labelled as guessed. LinkedIn and Google Scholar are search links in the app:
   neither allows automated reading.

Stored in the hashes parcours:academia:schools and parcours:academia:people, with parcours:academia:meta; refreshed
weekly by .github/workflows/academia.yml (python collector/academia.py [--dry-run] [--only=fr,ca] [--out=preview.json]).
"""
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
from collections import defaultdict
from datetime import date

import requests

sys.path.insert(0, os.path.dirname(__file__))
from collect import STATE_KEY, Store, load_env  # noqa: E402
from masters import profile_fields  # noqa: E402

SCHOOLS_KEY, PEOPLE_KEY, META_KEY = "parcours:academia:schools", "parcours:academia:people", "parcours:academia:meta"
COUNTRIES = {"fr": "FR", "de": "DE", "ca": "CA", "ch": "CH", "tn": "TN"}
UA = {"User-Agent": "parcours-personal-app (academic search for one applicant)"}
PER_COUNTRY = 60  # professors kept per country
TOPICS = {  # profile families (masters.profile_fields) -> research topics searched in titles and abstracts
    "ai": ["machine learning", "deep learning", "natural language processing", "explainable artificial intelligence",
           "large language models", "computer vision"],
    "data": ["data mining", "statistical learning", "recommender systems"],
    "software": ["software engineering", "distributed systems"],
}
http = requests.Session()
http.headers.update(UA)


def get_json(url, params=None, pause=0.15, tries=3):
    for i in range(tries):
        r = http.get(url, params=params, timeout=45)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 + 3 * i)
            continue
        r.raise_for_status()
        time.sleep(pause)
        return r.json()
    r.raise_for_status()


def fold(s):
    return unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()


def short(oa_id):
    return str(oa_id or "").rsplit("/", 1)[-1]


# ---------- engine 1: schools ----------

def ror_schools(cc):
    """Every education and facility organisation ROR lists in a country."""
    out, page = [], 1
    while True:
        j = get_json("https://api.ror.org/v2/organizations", {"filter": f"country.country_code:{cc},types:education", "page": page}, pause=0.3)
        out += j.get("items") or []
        if page * 20 >= j.get("number_of_results", 0) or not j.get("items"):
            break
        page += 1
    for t in ("facility",):
        page = 1
        while True:
            j = get_json("https://api.ror.org/v2/organizations", {"filter": f"country.country_code:{cc},types:{t}", "page": page}, pause=0.3)
            out += j.get("items") or []
            if page * 20 >= j.get("number_of_results", 0) or not j.get("items") or page >= 15:
                break
            page += 1
    return out


def school_record(o, c):
    names = o.get("names") or []
    label = next((n["value"] for n in names if "ror_display" in (n.get("types") or [])), names[0]["value"] if names else "")
    loc = ((o.get("locations") or [{}])[0].get("geonames_details") or {})
    web = next((l["value"] for l in o.get("links") or [] if l.get("type") == "website"), "")
    return {
        "id": short(o["id"]), "ror": o["id"], "name": label, "c": c,
        "aliases": [n["value"] for n in names if n.get("value") != label][:6],
        "acronym": next((n["value"] for n in names if "acronym" in (n.get("types") or [])), ""),
        "types": o.get("types") or [], "city": loc.get("name", ""), "website": web,
        "parent": [short(r["id"]) for r in o.get("relationships") or [] if r.get("type") == "parent"][:3],
        "children": len([r for r in o.get("relationships") or [] if r.get("type") == "child"]),
        "established": o.get("established"), "cs": 0, "topic": 0, "oa": "",
    }


def research_activity(cc, topics, since):
    """Recent computer-science papers per institution, and papers on your topics: {OpenAlex id: count}, both."""
    base = f"institutions.country_code:{cc},from_publication_date:{since}"
    cs = get_json("https://api.openalex.org/works", {"filter": base + ",primary_topic.field.id:fields/17", "group_by": "authorships.institutions.lineage", "per-page": 200})
    tq = "|".join(f'"{t}"' if " " in t else t for t in topics)
    tp = get_json("https://api.openalex.org/works", {"filter": base + f",title_and_abstract.search:{tq}", "group_by": "authorships.institutions.lineage", "per-page": 200})
    return ({short(g["key"]): g["count"] for g in cs.get("group_by") or []}, {short(g["key"]): g["count"] for g in tp.get("group_by") or []})


def openalex_to_ror(ids):
    """OpenAlex institution ids -> ROR ids, 50 at a time."""
    out, ids = {}, list(ids)
    for i in range(0, len(ids), 50):
        j = get_json("https://api.openalex.org/institutions", {"filter": "openalex_id:" + "|".join(ids[i:i + 50]), "per-page": 50, "select": "id,ror"})
        for r in j.get("results") or []:
            if r.get("ror"):
                out[short(r["id"])] = short(r["ror"])
    return out


# ---------- engine 2: professors ----------

def topic_authors(cc, topics, since):
    """Authors in the country on each topic, from the 200 most relevant papers of the last three years."""
    people = {}
    for t in topics:
        j = get_json("https://api.openalex.org/works", {"filter": f"institutions.country_code:{cc},from_publication_date:{since},title_and_abstract.search:\"{t}\"",
                                                       "per-page": 200, "select": "id,title,publication_year,authorships,primary_location"})
        for w in j.get("results") or []:
            n = len(w.get("authorships") or [])
            for a in w.get("authorships") or []:
                inst = next((i for i in a.get("institutions") or [] if i.get("country_code") == cc), None)
                if not inst or not (a.get("author") or {}).get("id"):
                    continue
                aid = short(a["author"]["id"])
                p = people.setdefault(aid, {"id": aid, "name": a["author"].get("display_name", ""), "orcid": short(a["author"].get("orcid")),
                                            "inst": short(inst.get("id")), "instName": inst.get("display_name", ""), "ror": short(inst.get("ror")),
                                            "papers": 0, "last": 0, "topics": set(), "year": 0, "recent": []})
                p["papers"] += 1
                if a.get("author_position") == "last" and n > 1:
                    p["last"] += 1
                p["topics"].add(t)
                p["year"] = max(p["year"], w.get("publication_year") or 0)
                if len(p["recent"]) < 3:
                    p["recent"].append({"title": w.get("title") or "", "year": w.get("publication_year"), "id": short(w.get("id"))})
    return people


def author_details(ids):
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 50):
        j = get_json("https://api.openalex.org/authors", {"filter": "openalex_id:" + "|".join(ids[i:i + 50]), "per-page": 50,
                                                         "select": "id,display_name,orcid,summary_stats,works_count,cited_by_count,last_known_institutions,topics"})
        for a in j.get("results") or []:
            out[short(a["id"])] = a
    return out


def theses_directed(name):
    """PhD theses directed, from theses.fr (France only): the best match on the full name."""
    try:
        j = get_json("https://theses.fr/api/v1/personnes/recherche/", {"q": name, "debut": 0, "nombre": 5}, pause=0.3)
    except Exception:
        return None
    want = fold(name).split()
    for x in j.get("personnes") or []:
        got = fold(f"{x.get('prenom', '')} {x.get('nom', '')}").split()
        if want and got and want[-1] == got[-1] and want[0][:1] == got[0][:1]:
            return {"count": (x.get("roles") or {}).get("Directeur / Directrice") or 0, "id": x.get("id")}
    return None


def score(p, max_papers):
    fit = min(1.0, p["papers"] / max(3, max_papers)) * 0.6 + min(1.0, len(p["topics"]) / 3) * 0.4
    lead = min(1.0, (p["last"] + 2 * min(10, (p.get("theses") or {}).get("count", 0))) / 8)
    active = 1.0 if p["year"] >= date.today().year - 1 else 0.6 if p["year"] >= date.today().year - 2 else 0.3
    impact = min(1.0, (p.get("h") or 0) / 40)
    parts = {"fit": round(fit * 45), "supervision": round(lead * 25), "activity": round(active * 10), "impact": round(impact * 20)}
    return sum(parts.values()), parts


# ---------- engine 3: contacts ----------

EMAIL = re.compile(r"(\{[\w.,\s-]+\}|[\w.+-]+)\s*(?:@|\[at\]|\(at\)|\s+at\s+)\s*([\w-]+(?:\s*(?:\.|\[dot\]|\(dot\))\s*[\w-]+)+)", re.I)


def emails_in(text):
    out = []
    for local, dom in EMAIL.findall(text or ""):
        dom = re.sub(r"\s*(?:\[dot\]|\(dot\))\s*", ".", dom).replace(" ", "").lower().strip(".")
        if "." not in dom or re.search(r"\.(png|jpg|gif|svg|css|js)$", dom):
            continue
        locals_ = [l.strip() for l in local.strip("{}").split(",")] if local.startswith("{") else [local]
        out += [f"{l.lower()}@{dom}" for l in locals_ if l]
    return list(dict.fromkeys(out))


def matches_name(email, name):
    """Does the local part of the address belong to this person (first.last, flast, last, firstl...)?"""
    local = fold(email.split("@")[0])
    parts = [w for w in re.split(r"[^a-z]+", fold(name)) if len(w) > 1]
    if not parts:
        return False
    first, last = parts[0], parts[-1]
    return last in local and (first in local or local.startswith(first[0]) or local.endswith(first[0]) or local == last)


def from_orcid(orcid):
    if not orcid:
        return [], []
    try:
        r = http.get(f"https://pub.orcid.org/v3.0/{orcid}/person", headers={"Accept": "application/json"}, timeout=30)
        p = r.json() if r.ok else {}
    except Exception:
        return [], []
    time.sleep(0.2)
    emails = [e.get("email") for e in ((p.get("emails") or {}).get("email") or []) if e.get("email")]
    urls = [u["url"]["value"] for u in ((p.get("researcher-urls") or {}).get("researcher-url") or []) if (u.get("url") or {}).get("value")]
    return emails, urls


def from_page(url, name):
    try:
        r = http.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok or "html" not in r.headers.get("content-type", ""):
            return []
    except Exception:
        return []
    html = re.sub(r"<[^>]+>", " ", r.text.replace("&#64;", "@").replace("&#x40;", "@"))
    return [e for e in emails_in(html) if matches_name(e, name)]


def from_arxiv(author_id, name, limit=2):
    """Emails printed on the first page of the author's own arXiv papers, matched to their name."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return [], None
    j = get_json("https://api.openalex.org/works", {"filter": f"authorships.author.id:{author_id},locations.source.id:S4306400194",
                                                   "sort": "publication_date:desc", "per-page": 4, "select": "id,locations"})
    tried = 0
    for w in j.get("results") or []:
        pdf = next((l["pdf_url"] for l in w.get("locations") or [] if "arxiv.org" in (l.get("pdf_url") or "")), None)
        if not pdf or tried >= limit:
            continue
        tried += 1
        try:
            r = http.get(pdf, timeout=40)
            text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text() or ""
        except Exception:
            continue
        time.sleep(1)
        found = [e for e in emails_in(text) if matches_name(e, name)]
        if found:
            return found, pdf.replace("/pdf/", "/abs/")
    return [], None


def contacts(p):
    """Fills p["emails"] with {email, source, url} and p["homepage"]."""
    found = []
    o_emails, o_urls = from_orcid(p.get("orcid"))
    found += [{"email": e.lower(), "source": "ORCID (public)", "url": f"https://orcid.org/{p['orcid']}"} for e in o_emails]
    home = next((u for u in o_urls if not re.search(r"linkedin|twitter|x\.com|github|scholar\.google|researchgate|orcid", u, re.I)), "")
    p["homepage"] = home
    p["links"] = [u for u in o_urls if u != home][:4]
    if not found and home:
        found += [{"email": e, "source": "Homepage", "url": home} for e in from_page(home, p["name"])]
    if not found:
        es, src = from_arxiv(p["id"], p["name"])
        found += [{"email": e, "source": "Their arXiv paper", "url": src} for e in es]
    p["emails"] = list({e["email"]: e for e in found}.values())[:3]


def guess_emails(people):
    """first.last@domain for people without an address, when colleagues at the same school use exactly that format."""
    fmt = defaultdict(lambda: defaultdict(int))
    for p in people:
        for e in p.get("emails") or []:
            parts = [w for w in re.split(r"[^a-z]+", fold(p["name"])) if len(w) > 1]
            if len(parts) >= 2 and e["email"].split("@")[0] == f"{parts[0]}.{parts[-1]}":
                fmt[p.get("ror") or p.get("inst")][e["email"].split("@")[1]] += 1
    n = 0
    for p in people:
        if p.get("emails"):
            continue
        doms = fmt.get(p.get("ror") or p.get("inst")) or {}
        dom = max(doms, key=doms.get) if doms else None
        parts = [w for w in re.split(r"[^a-z]+", fold(p["name"])) if len(w) > 1]
        if dom and doms[dom] >= 2 and len(parts) >= 2:
            p["emails"] = [{"email": f"{parts[0]}.{parts[-1]}@{dom}", "source": f"Guessed: {doms[dom]} colleagues use first.last@{dom}", "url": "", "guess": True}]
            n += 1
    return n


# ---------- run ----------

def run_country(c, topics, since, log):
    cc = COUNTRIES[c]
    raw = ror_schools(cc)
    schools = {}
    for o in raw:
        s = school_record(o, c)
        schools[s["id"]] = s
    cs, tp = research_activity(cc, topics, since)
    ror_of = openalex_to_ror(set(cs) | set(tp))
    for oa, ror in ror_of.items():
        if ror in schools:
            schools[ror].update({"cs": cs.get(oa, 0), "topic": tp.get(oa, 0), "oa": oa})
    log(f"  {c}: {len(schools)} schools, {sum(1 for s in schools.values() if s['cs'])} with recent CS papers")

    people = topic_authors(cc, topics, since)
    ranked = sorted(people.values(), key=lambda p: (-(p["papers"] + 1.5 * p["last"]), -p["year"]))[:PER_COUNTRY * 2]
    det = author_details([p["id"] for p in ranked])
    keep = []
    for p in ranked:
        a = det.get(p["id"]) or {}
        st = a.get("summary_stats") or {}
        p.update({"h": st.get("h_index"), "works": a.get("works_count"), "cited": a.get("cited_by_count"),
                  "orcid": p["orcid"] or short(a.get("orcid")), "fields": [t.get("display_name") for t in (a.get("topics") or [])[:4]]})
        lk = next((i for i in a.get("last_known_institutions") or [] if i.get("country_code") == cc), None)
        if lk:  # where they are now, not where an old paper says
            p.update({"inst": short(lk.get("id")), "instName": lk.get("display_name", ""), "ror": short(lk.get("ror"))})
        elif a.get("last_known_institutions"):
            continue  # moved abroad
        keep.append(p)
    if c == "fr":
        for p in keep[:PER_COUNTRY]:
            p["theses"] = theses_directed(p["name"])
    max_papers = max([p["papers"] for p in keep] or [1])
    for p in keep:
        p["score"], p["parts"] = score(p, max_papers)
    keep = sorted(keep, key=lambda p: -p["score"])[:PER_COUNTRY]
    for i, p in enumerate(keep):
        contacts(p)
        if i % 10 == 9:
            log(f"    {c}: contacts for {i + 1}/{len(keep)}")
    for p in keep:
        p["topics"] = sorted(p["topics"])
        p["c"] = c
        if p.get("ror") in schools:
            schools[p["ror"]]["people"] = schools[p["ror"]].get("people", 0) + 1
    log(f"  {c}: {len(keep)} professors, {sum(1 for p in keep if p.get('emails'))} with an email")
    return list(schools.values()), keep


def topics_for(state):
    fams = profile_fields((state or {}).get("profile"))
    return list(dict.fromkeys(t for f in fams for t in TOPICS.get(f, [])))[:6]


def save_hash(store, key, records, idf="id"):
    old = set(store.cmd("HKEYS", key) or [])
    batch = []
    for r in records:
        batch += [r[idf], json.dumps(r, ensure_ascii=False)]
        if len(batch) >= 300:
            store.cmd("HSET", key, *batch)
            batch = []
    if batch:
        store.cmd("HSET", key, *batch)
    gone = list(old - {r[idf] for r in records})
    for i in range(0, len(gone), 200):
        store.cmd("HDEL", key, *gone[i:i + 200])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dry = "--dry-run" in sys.argv
    env = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--env=")), "")
    only = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--only=")), list(COUNTRIES))
    if env:
        load_env(env)
    store = None if dry and not os.environ.get("UPSTASH_REDIS_REST_URL") else Store()
    state = (store.get_json(STATE_KEY) if store else None) or {}
    topics = topics_for(state)
    since = date(date.today().year - 3, 1, 1).isoformat()
    print(f"topics: {topics}, since {since}, countries: {only}")
    schools, people, status = [], [], {}
    for c in only:
        try:
            s, p = run_country(c, topics, since, print)
            schools += s
            people += p
            status[c] = {"ok": True, "schools": len(s), "people": len(p), "emails": sum(1 for x in p if x.get("emails"))}
        except Exception as e:
            status[c] = {"ok": False, "error": str(e)[:200]}
            print(f"  {c}: ERROR {e}")
    guessed = guess_emails(people)
    print(f"{len(schools)} schools, {len(people)} professors, {sum(1 for p in people if p.get('emails'))} with an email ({guessed} guessed)")
    out = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--out=")), "")
    if out:  # local preview: what the app's /api/opps?set=academia would return
        with open(out, "w", encoding="utf8") as f:
            json.dump({"at": int(time.time() * 1000), "topics": topics, "since": since, "countries": status, "schools": schools, "people": people}, f, ensure_ascii=False)
    if dry or not store:
        for p in sorted(people, key=lambda p: -p["score"])[:12]:
            print(f"  [{p['c']}] {p['score']:3} {p['name'][:28]:28} {p['instName'][:34]:34} h{p.get('h')} th{(p.get('theses') or {}).get('count', '-')} {[e['email'] for e in p.get('emails') or []]}")
        return
    ok = [c for c, s in status.items() if s["ok"]]
    # Countries that failed keep what was stored for them last time.
    if ok:
        keep_s = [json.loads(v) for v in (store.cmd("HVALS", SCHOOLS_KEY) or []) if json.loads(v).get("c") not in ok]
        keep_p = [json.loads(v) for v in (store.cmd("HVALS", PEOPLE_KEY) or []) if json.loads(v).get("c") not in ok]
        save_hash(store, SCHOOLS_KEY, keep_s + schools)
        save_hash(store, PEOPLE_KEY, keep_p + people)
    store.cmd("SET", META_KEY, json.dumps({"at": int(time.time() * 1000), "topics": topics, "since": since, "countries": status}))
    print("saved")


if __name__ == "__main__":
    main()
