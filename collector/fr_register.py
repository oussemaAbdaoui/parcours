"""French company register (INSEE SIRENE, through the free state API recherche-entreprises.api.gouv.fr): for each
company with offers in France, its staff band, founding year, sector (NAF code), size category (PME, ETI, GE), head
office town, and whether it is still active. Stored in companies.register; the app shows it on offers and company
pages, and warns when the register says the company has closed.

Names are ambiguous ("Margo" returns 751 companies), so only an exact match counts: the registered name, the full
name or the acronym, once normalised like every company key (enrich._norm). Among several exact matches, the active
employer with the most staff wins. No exact match is remembered too ({"none": true}), so it is not asked again for
90 days. The API allows 7 requests a second; a run asks at most LIMIT companies.

Also marks the French Tech Next40 and French Tech 120 companies (data/french-tech-120.csv, 2025 list: the first 40
rows are the Next40) in companies.lists.

  python collector/fr_register.py [--env=path] [--dry-run]
"""
import csv
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from enrich import _norm  # noqa: E402

API = "https://recherche-entreprises.api.gouv.fr/search"
REFRESH_DAYS, LIMIT, PAUSE = 90, 400, 0.2
FRENCH_TECH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "french-tech-120.csv")
# INSEE staff bands (tranche_effectif_salarie): code -> (lowest headcount, label)
STAFF = {"00": (0, "no employees"), "01": (1, "1-2"), "02": (3, "3-5"), "03": (6, "6-9"), "11": (10, "10-19"), "12": (20, "20-49"),
         "21": (50, "50-99"), "22": (100, "100-199"), "31": (200, "200-249"), "32": (250, "250-499"), "41": (500, "500-999"),
         "42": (1000, "1,000-1,999"), "51": (2000, "2,000-4,999"), "52": (5000, "5,000-9,999"), "53": (10000, "10,000+")}
# NAF codes worth naming: what kind of employer this is for a tech job
NAF = {"62.01Z": "software development", "62.02A": "IT consulting (ESN)", "62.02B": "IT maintenance", "62.03Z": "IT operations",
       "62.09Z": "IT services", "58.29A": "software publishing", "58.29B": "software publishing", "58.29C": "software publishing",
       "63.11Z": "data processing and hosting", "63.12Z": "web portals", "72.19Z": "R&D", "72.11Z": "biotech R&D",
       "70.22Z": "business consulting", "71.12B": "engineering consultancy", "73.11Z": "advertising", "64.19Z": "banking",
       "65.12Z": "insurance", "78.10Z": "recruitment agency", "78.20Z": "temp staffing agency", "78.30Z": "staffing",
       "85.42Z": "higher education", "84.11Z": "public administration", "70.10Z": "head office"}
SECTION = {"A": "agriculture", "B": "mining", "C": "manufacturing", "D": "energy", "E": "water and waste", "F": "construction",
           "G": "trade", "H": "transport", "I": "hospitality", "J": "information and communication", "K": "finance and insurance",
           "L": "real estate", "M": "professional and scientific services", "N": "administrative services",
           "O": "public administration", "P": "education", "Q": "health", "R": "arts and leisure", "S": "other services"}
TECH_SECTIONS = {"J", "M", "K", "O", "P", "Q"}  # sectors where an unsized company hiring for tech is plausible


def record(x, now):
    """One register entry -> the compact record stored in companies.register."""
    staff = STAFF.get(x.get("tranche_effectif_salarie") or "")
    naf = x.get("activite_principale") or ""
    return {"country": "fr", "id": x.get("siren"), "name": x.get("nom_raison_sociale") or x.get("nom_complet") or "",
            "staff": staff[1] if staff else "", "staffMin": staff[0] if staff else None, "staffYear": x.get("annee_tranche_effectif_salarie"),
            "founded": (x.get("date_creation") or "")[:4], "naf": naf,
            "sector": NAF.get(naf) or SECTION.get(x.get("section_activite_principale") or "", ""),
            "category": x.get("categorie_entreprise") or "", "town": ((x.get("siege") or {}).get("libelle_commune") or "").title(),
            "active": x.get("etat_administratif") == "A", "at": now}


def lookup(key, name, now):
    """The register record for a company key, {"none": True} when no exact match, or None on a network error."""
    try:
        r = requests.get(API, params={"q": name, "per_page": 15}, timeout=20)
        if r.status_code == 429:
            time.sleep(2)
            r = requests.get(API, params={"q": name, "per_page": 15}, timeout=20)
        r.raise_for_status()
        results = r.json().get("results") or []
    except (requests.RequestException, ValueError):
        return None
    exact = [x for x in results if key in {_norm(x.get("nom_raison_sociale")), _norm(x.get("sigle")),
                                           _norm((x.get("nom_complet") or "").split("(")[0])} - {""}]
    if len(exact) == 1:
        x = exact[0]
        # The only company of that name, but with no staff count, is trusted only in a sector that hires for tech
        # jobs ("Free-Work", consulting, yes; "Haystack", arts and leisure, founded 2025, no).
        if STAFF.get(x.get("tranche_effectif_salarie") or "") or (x.get("section_activite_principale") or "") in TECH_SECTIONS \
                or (x.get("activite_principale") or "").startswith("78."):
            return record(x, now)
        return {"none": True, "at": now}
    # Several companies share the name (25 "Margo", a 1985 estate agent first): only active ones with a known staff
    # count compete, and the largest must have ten times the staff of the next ("Open", 2,000+, against a 20-person
    # wholesaler); a common name also needs 10 staff or more, so a one-person "Escape" restaurant is not the security startup.
    sized = sorted((x for x in exact if x.get("etat_administratif") == "A" and STAFF.get(x.get("tranche_effectif_salarie") or "")),
                   key=lambda x: -STAFF[x["tranche_effectif_salarie"]][0])
    if not sized:
        return {"none": True, "at": now}
    top = STAFF[sized[0]["tranche_effectif_salarie"]][0]
    second = STAFF[sized[1]["tranche_effectif_salarie"]][0] if len(sized) > 1 else 0
    if (second and top < 10 * max(second, 1)) or (len(exact) > 3 and top < 10):
        return {"none": True, "at": now}
    return record(sized[0], now)


def french_tech():
    """({company key: "Next40" | "French Tech 120"}, {company key: name}) from data/french-tech-120.csv."""
    if not os.path.exists(FRENCH_TECH):
        return {}, {}
    rows = list(csv.DictReader(open(FRENCH_TECH, encoding="utf-8", errors="replace")))
    return {_norm(r["Name"].split("(")[0]): ("Next40" if i < 40 else "French Tech 120") for i, r in enumerate(rows)}, \
        {_norm(r["Name"].split("(")[0]): r["Name"].split("(")[0].strip() for r in rows}


def refresh(dry=False, budget=240):
    """Marks the French Tech companies, then looks up companies with French offers whose register entry is missing or
    older than REFRESH_DAYS. Returns (companies looked up, error or "")."""
    import pg
    c = pg.required()
    now = int(time.time() * 1000)
    lists, names = french_tech()
    if lists and not dry:
        pg.company_ids(names, now)  # French Tech companies with no offer yet get a row too, so their offers link later
        with c.cursor() as cur:
            cur.execute("update companies set lists = array_remove(coalesce(lists, '{}'), 'Next40') where 'Next40' = any(lists)")
            cur.execute("update companies set lists = array_remove(coalesce(lists, '{}'), 'French Tech 120') where 'French Tech 120' = any(lists)")
            cur.execute("update companies c set lists = array_append(coalesce(c.lists, '{}'), t.l), updated_at = %s "
                        "from unnest(%s::text[], %s::text[]) as t(k, l) where c.norm = t.k", (now, list(lists), list(lists.values())))
    stale = now - REFRESH_DAYS * 86400 * 1000
    todo = c.execute("""select c.norm, c.name from companies c
        where (exists (select 1 from offers o where o.company_id = c.id and o.country = 'fr') or 'Next40' = any(c.lists)
               or 'French Tech 120' = any(c.lists))
          and (c.register is null or (c.register->>'at')::bigint < %s)
        order by c.register is not null, c.updated_at desc limit %s""", (stale, LIMIT)).fetchall()
    t0, done, failed = time.time(), 0, 0
    for key, name in todo:
        if time.time() - t0 > budget:
            break
        rec = lookup(key, name, now)
        time.sleep(PAUSE)
        if rec is None:
            failed += 1
            if failed >= 10 and not done:
                return 0, "the register API did not answer"
            continue
        done += 1
        if dry:
            print(f"  {name[:30]:30} {rec.get('staff', '') or ('no exact match' if rec.get('none') else ''):14} {rec.get('founded', '')} "
                  f"{rec.get('sector', '')[:28]:28} {'' if rec.get('none') or rec.get('active') else 'CLOSED'}")
            continue
        c.execute("update companies set register = %s, updated_at = %s where norm = %s", (json.dumps(rec, ensure_ascii=False), now, key))
    # A few failed lookups are normal (they are asked again next run); only a run where none worked is an error.
    if failed:
        print(f"  French company register: {failed} lookups failed, retried next run")
    return done, ("the register API did not answer" if failed and not done else "")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    from collect import load_env
    for a in sys.argv[1:]:
        if a.startswith("--env="):
            load_env(a.split("=", 1)[1])
    print(refresh(dry="--dry-run" in sys.argv))
