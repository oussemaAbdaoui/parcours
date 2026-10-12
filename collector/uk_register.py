"""UK register of licensed sponsors (gov.uk, published every working day): a UK job needs an employer licensed for
the Skilled Worker visa. Poli lists about 2,500 sponsors; the register has about 120,000.

Refreshed weekly into the Postgres table uk_sponsors, then every company is marked companies.uk_sponsor (true when
its name is on the register). Names match when equal once normalised (enrich._norm), equal without spaces
("ElevenLabs" / "Eleven Labs Ltd"), or equal once some generic endings are dropped from the registered name ("Wayve
Technologies Ltd" -> "wayve", "PA Consulting Services" -> "pa consulting"). Trading names count ("Roofoods Ltd t/a Deliveroo"). A looser prefix rule was
measured and rejected: "Meta" matched "Meta Data Systems", "Prima" fourteen companies.

  python collector/uk_register.py [--env=path] [--force]
"""
import csv
import io
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
REFRESH_DAYS = 7
GENERIC = {"limited", "ltd", "plc", "llp", "lp", "inc", "incorporated", "corporation", "corp", "co", "company", "group", "holdings",
           "holding", "technologies", "technology", "tech", "operations", "services", "service", "solutions", "consulting",
           "consultancy", "consultants", "associates", "international", "europe", "european", "emea", "global", "worldwide",
           "uk", "gb", "england", "london", "bank", "national", "association", "partners", "ventures", "enterprises", "systems",
           "software", "digital", "management", "trading", "the", "and"}


def base(norm):
    """The registered name without generic trailing words ("wayve technologies" -> "wayve"); never empty."""
    words = norm.split()
    while len(words) > 1 and words[-1] in GENERIC:
        words.pop()
    return " ".join(words)


def variants(norm):
    """The name and each shorter form while generic trailing words are dropped: "pa consulting services" gives
    "pa consulting services", "pa consulting" and "pa"."""
    words, out = norm.split(), [norm]
    while len(words) > 1 and words[-1] in GENERIC:
        words.pop()
        out.append(" ".join(words))
    return out


def download():
    """[(organisation name, town)] on the Skilled Worker route, from the newest register CSV."""
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    page = requests.get(PAGE, timeout=30, headers=ua)
    page.raise_for_status()
    link = re.search(r"https://assets\.publishing\.service\.gov\.uk/[^\"]+\.csv", page.text)
    if not link:
        raise RuntimeError("register CSV link not found on gov.uk")
    r = requests.get(link.group(0), timeout=120, headers=ua)
    r.raise_for_status()
    rows = csv.DictReader(io.StringIO(r.content.decode("utf-8-sig", "replace")))
    return [((x.get("Organisation Name") or "").strip(), (x.get("Town/City") or "").strip()) for x in rows
            if (x.get("Route") or "").strip() == "Skilled Worker"]


def names(org):
    """The registered name and any trading names ("A Ltd t/a B", "A trading as B")."""
    parts = re.split(r"\s+(?:t/a|T/A|T/a|trading as|Trading As|TRADING AS)\s+", org)
    return [p.strip(" ,") for p in parts if p.strip(" ,")]


def refresh(force=False):
    """Downloads the register when older than a week and re-marks companies. Returns (sponsor names, error)."""
    import pg
    from enrich import _norm
    now = int(time.time() * 1000)
    last = pg._rows("select coalesce(max(updated_at), 0) from uk_sponsors")[0][0]
    if not force and now - last < REFRESH_DAYS * 86400 * 1000:
        n = pg._rows("select count(*) from uk_sponsors")[0][0]
        with pg.required().cursor() as cur:
            link_uk(cur)
        return n, ""
    rows = {}
    for org, town in download():
        for name in names(org):
            n = _norm(name)
            if len(n) >= 2:
                rows.setdefault(n, (n, base(n), org, town, now))
    if len(rows) < 50000:  # a broken download must not empty the table
        raise RuntimeError(f"register looks incomplete ({len(rows)} names)")
    with pg.required().cursor() as cur:
        vals = list(rows.values())
        for i in range(0, len(vals), 5000):
            cur.executemany("insert into uk_sponsors (norm, base, name, town, updated_at) values (%s, %s, %s, %s, %s) on conflict (norm) "
                            "do update set base = excluded.base, name = excluded.name, town = excluded.town, updated_at = excluded.updated_at",
                            vals[i:i + 5000])
        cur.execute("delete from uk_sponsors where updated_at < %s", (now,))  # licences revoked since the last download
        link_uk(cur)
    return len(rows), ""


def link_uk(cur, keys=None):
    """companies.uk_sponsor for every company (or just keys): on the register by name, no-space name, or base name."""
    cur.execute("select norm from uk_sponsors")
    known = set()
    for (norm,) in cur.fetchall():
        for v in variants(norm):
            known.update((v, v.replace(" ", "")))
    if not known:
        return
    # A company Poli lists as a sponsor counts too (Poli reads the same register under trading names: Meta, WTW).
    if keys is None:
        cur.execute("select id, norm, poli_id from companies")
    else:
        cur.execute("select id, norm, poli_id from companies where norm = any(%s)", (list(keys),))
    rows = [(n in known or n.replace(" ", "") in known or p is not None, i) for i, n, p in cur.fetchall()]
    cur.executemany("update companies set uk_sponsor = %s where id = %s and uk_sponsor is distinct from %s", [(v, i, v) for v, i in rows])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    from collect import load_env
    env = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--env=")), "")
    if env:
        load_env(env)
    print(refresh(force="--force" in sys.argv))
