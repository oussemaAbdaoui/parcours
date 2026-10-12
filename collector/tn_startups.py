"""Tunisian tech startups: the official catalogue (APII / CIDT, September 2022, STARTUPSTECH.pdf), parsed into
data/tn-startups.json (117 startups: founding year, sector, website, founders, contact email, address, activity).
Stored in Postgres as the dataset tn-startups, which the app shows under Discover -> Startups (Tunisia) for direct
applications. Each website is checked once every 30 days (the catalogue is from 2022, some have closed), and the
matching companies get "Tunisian startup" in companies.lists.

Also the directory of partner companies (entreprisespartenaires.csv: 6,600 Tunisian companies with sector code, city,
address and phone), kept for the sectors that hire engineers like you (IT services, ICT services, engineering and
consulting, electrical and electronics industry: 1,466) in data/tn-companies.json, stored as the dataset tn-companies.
Companies already in your store get "Tunisian partner company" in companies.lists; no rows are made for the others.

  python collector/tn_startups.py [--env=path] [--force]
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

sys.path.insert(0, os.path.dirname(__file__))
from enrich import _norm  # noqa: E402

SET = "tn-startups"
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "tn-startups.json")
CHECK_DAYS, LIST = 30, "Tunisian startup"
DIRECTORY, DIRECTORY_SET, DIRECTORY_LIST = DATA.replace("tn-startups", "tn-companies"), "tn-companies", "Tunisian partner company"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"}


def alive(site):
    """True when the website answers (any status below 500 over https or http), False when it does not."""
    for scheme in ("https://", "http://"):
        try:
            r = requests.get(scheme + site, headers=UA, timeout=15, allow_redirects=True)
            if r.status_code < 500:
                return True
        except requests.RequestException:
            continue
    return False


def refresh(force=False):
    """Loads the catalogue into the dataset, re-checking websites older than CHECK_DAYS. Returns (count, error)."""
    import pg
    now = int(time.time() * 1000)
    stored = pg.dataset(SET)
    rows = json.load(open(DATA, encoding="utf-8"))
    out = []
    for r in rows:
        key = _norm(r["name"].split("(")[0]) or _norm(r["name"])
        old = stored.get(key) or {}
        out.append({**r, "id": key, "alive": old.get("alive"), "checkedAt": old.get("checkedAt", 0)})
    due = [x for x in out if x["site"] and (force or now - (x["checkedAt"] or 0) > CHECK_DAYS * 86400 * 1000)]
    with ThreadPoolExecutor(8) as ex:
        for x, ok in zip(due, ex.map(lambda x: alive(x["site"]), due)):
            x["alive"], x["checkedAt"] = ok, now
    n = pg.dataset_save(SET, out, [k for k in stored if k not in {x["id"] for x in out}], now)
    names = {x["id"]: x["name"].split("(")[0].strip().title() for x in out}
    pg.company_ids(names, now)
    with pg.required().cursor() as cur:
        cur.execute("update companies c set lists = array_append(coalesce(c.lists, '{}'), %s), updated_at = %s "
                    "where c.norm = any(%s) and not (%s = any(coalesce(c.lists, '{}')))", (LIST, now, list(names), LIST))
    # The partner companies directory: replaced as a whole, marks only companies already stored.
    directory = json.load(open(DIRECTORY, encoding="utf-8"))
    pg.dataset_save(DIRECTORY_SET, directory, [k for k in pg.dataset(DIRECTORY_SET) if k not in {x["id"] for x in directory}], now)
    with pg.required().cursor() as cur:
        cur.execute("update companies c set lists = array_append(coalesce(c.lists, '{}'), %s), updated_at = %s "
                    "where c.norm = any(%s) and not (%s = any(coalesce(c.lists, '{}')))",
                    (DIRECTORY_LIST, now, [x["id"] for x in directory], DIRECTORY_LIST))
    return n + len(directory), ""


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    from collect import load_env
    for a in sys.argv[1:]:
        if a.startswith("--env="):
            load_env(a.split("=", 1)[1])
    print(refresh(force="--force" in sys.argv))
