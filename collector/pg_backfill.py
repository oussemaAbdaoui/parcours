"""One-off copy of the Redis stores into the Postgres tables of db/schema.sql (phase 2: offers and companies).
Idempotent: run it again any time, it upserts. Usage: python collector/pg_backfill.py --env=~/parcours-collector/upstash.env
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding="utf-8")
from collect import ITEMS_KEY, Store, load_env  # noqa: E402

for a in sys.argv[1:]:
    if a.startswith("--env="):
        load_env(os.path.expanduser(a.split("=", 1)[1]))
import pg  # noqa: E402
from enrich import COMPANIES_KEY, _norm  # noqa: E402
from history import HISTORY_KEY  # noqa: E402

st, now = Store(), int(time.time() * 1000)


def hash_items(key):
    flat = st.cmd("HGETALL", key) or []
    return [(flat[i], json.loads(flat[i + 1])) for i in range(0, len(flat), 2)]


history = hash_items(HISTORY_KEY)
rows = []
for k, rec in history:
    for oid, v in (rec.get("seen") or {}).items():
        day, kind, src = (v.split("|") + ["", "", ""])[:3]
        rows.append((k, rec.get("name") or k, oid, day, kind, src))
print("hiring log rows:", pg.company_seen(rows, now), "from", len(history), "companies")

names = {k: rec.get("name") or k for k, rec in history}
ratings = hash_items(COMPANIES_KEY)
for k, rec in ratings:
    pg.company_rating(k, names.get(k, k), rec, now)
print("ratings:", len(ratings))

offers = [rec for _, rec in hash_items(ITEMS_KEY)]
print("offers:", pg.offers_save(offers, [], now))

stories = hash_items("parcours:insights")
for k, rec in stories:
    pg.insight(k, rec.get("company") or k.split("|")[0], rec.get("role") or "", rec, now)
print("stories:", len(stories))

with pg.conn().cursor() as cur:
    cur.execute("""select (select count(*) from companies), (select count(*) from companies where rating is not null),
                          (select count(*) from companies where poli_id is not null), (select count(*) from offers),
                          (select count(*) from offers where company_id is null), (select count(*) from company_seen),
                          (select count(*) from insights where company_id is not null),
                          pg_size_pretty(pg_database_size(current_database()))""")
    print("companies %s (rated %s, UK sponsors %s) | offers %s (no company %s) | hiring log %s | stories linked %s | db %s" % cur.fetchone())
