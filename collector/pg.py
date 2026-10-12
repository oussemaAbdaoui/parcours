"""Neon Postgres for the collectors: the store for everything collected (offers, companies, hiring log, interview
stories, Poli, master's, academia) and where they read your profile and searches. Redis keeps only run reports,
queues, sessions and counters.

DATABASE_URL_UNPOOLED (or DATABASE_URL) comes from the environment: a GitHub secret for the cloud runs,
~/parcours-collector/upstash.env on the PC.
"""
import json
import os

_conn = None


def conn():
    """One connection per run, autocommit. None when no database is configured."""
    global _conn
    url = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL")
    if not url:
        return None
    if _conn is None or _conn.closed:
        import psycopg
        _conn = psycopg.connect(url, autocommit=True, connect_timeout=20)
    return _conn


def required():
    """The connection, or an error when no database is configured: offers, master's and the rest live only here now."""
    c = conn()
    if not c:
        raise RuntimeError("DATABASE_URL_UNPOOLED is not set: the collected data is stored in Postgres")
    return c


def _rows(sql, args=()):
    with required().cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


# ---------- Your data (written by the app through api/state.js) ----------

LISTS = ("apps", "saved", "journal", "searches", "feeds", "queue", "contacts")
NEWEST_FIRST = {"saved", "journal"}


def state():
    """The app's state assembled like api/state.js load(): lists in the app's order, then the settings."""
    out = {"apps": [], "saved": [], "journal": [], "searches": [], "feeds": [], "updatedAt": 0}
    items = _rows("select collection, data, created_at, updated_at from items where not deleted")
    settings = _rows("select key, data, updated_at from settings")
    for c in LISTS:
        rows = sorted((r for r in items if r[0] == c), key=lambda r: r[2], reverse=c in NEWEST_FIRST)
        out[c] = [r[1] for r in rows]
    for k, data, _ in settings:
        out[k] = data
    out["updatedAt"] = max([r[3] for r in items] + [r[2] for r in settings] + [0])
    return out


def _clean(r):
    """Empty values dropped, so a merge never blanks a stored field."""
    return {k: v for k, v in r.items() if v not in ("", None, [], {})}


def merge(table, rows, columns, now, sticky=()):
    """Upserts rows into table: columns(r) gives the indexed columns, the record itself goes to data, merged with
    what is stored (old || new, empty fields dropped first) and stamped seen_at. sticky: boolean columns that stay
    true once set (a person seen in the network stays flagged when a company list later omits the flag). Never deletes."""
    if not rows:
        return 0
    c = required()
    cols = list(columns(rows[0]).keys())
    sample = columns(rows[0])

    def keep(k):  # an empty new value keeps the stored one, like the data merge
        if k in sticky:
            return f"{k} = {table}.{k} or excluded.{k}"
        if isinstance(sample[k], str):
            return f"{k} = coalesce(nullif(excluded.{k}, ''), {table}.{k})"
        return f"{k} = coalesce(excluded.{k}, {table}.{k})"
    sets = ", ".join(keep(k) for k in cols if k != "id")
    sql = (f"insert into {table} ({', '.join(cols)}, data, seen_at) values ({', '.join(['%s'] * (len(cols) + 2))}) "
           f"on conflict (id) do update set {sets + ', ' if sets else ''}data = {table}.data || excluded.data, seen_at = excluded.seen_at")
    with c.cursor() as cur:
        for i in range(0, len(rows), 500):
            cur.executemany(sql, [(*columns(r).values(), json.dumps(_clean(r), ensure_ascii=False), now) for r in rows[i:i + 500]])
    return len(rows)


# ---------- Poli ----------

def _norm(name):
    from enrich import _norm as n
    return n(name or "")


def poli_companies(rows, now):
    return merge("poli_companies", rows, lambda r: {"id": int(r["id"]), "name": r.get("name") or "", "norm": _norm(r.get("name")),
                                                    "legal_norm": _norm(r.get("legalName")), "licensed": bool(r.get("licensed"))}, now)


def poli_people(rows, now):
    def cols(r):
        search = " ".join(str(r.get(k) or "") for k in ("name", "title", "company", "expertise", "experience")).lower()
        return {"id": int(r["id"]), "company_id": int(r["companyId"]) if r.get("companyId") else None, "name": r.get("name") or "",
                "title": r.get("title") or "", "sponsorship": r.get("sponsorship") or "", "network": bool(r.get("network")), "search": search}
    return merge("poli_people", rows, cols, now, sticky=("network",))


def poli_jobs(rows, now):
    return merge("poli_jobs", rows, lambda r: {"id": str(r["id"]), "company_id": (r.get("poli") or {}).get("companyId")}, now)


# ---------- Offers and companies ----------

def company_ids(names, now):
    """{key: display name} -> {key: companies.id}, creating the missing companies. Keys are normalised again
    (keys stored by an older normaliser, "lovable labs sweden ab", land on "lovable labs"). New companies are linked
    to their Poli sponsor record by trading or registered name."""
    c = required()
    canon = {k: _norm(k) for k in names if k}
    canon = {k: v for k, v in canon.items() if len(v) >= 2}
    if not canon:
        return {}
    first = {}
    for k, v in canon.items():
        first.setdefault(v, names[k] or k)
    keys = list(first)
    with c.cursor() as cur:
        cur.execute("insert into companies (norm, name, updated_at) select k, n, %s from unnest(%s::text[], %s::text[]) as t(k, n) "
                    "on conflict (norm) do update set updated_at = excluded.updated_at returning norm, id",
                    (now, keys, [first[k] for k in keys]))
        ids = dict(cur.fetchall())
        link_sponsors(cur, keys)
    return {k: ids[v] for k, v in canon.items() if v in ids}


def link_sponsors(cur, keys=None):
    """companies.poli_id from the Poli directory: same trading name first, else same registered name."""
    only = "and c.norm = any(%s)" if keys is not None else ""
    for col in ("norm", "legal_norm"):
        cur.execute(f"update companies c set poli_id = p.id from poli_companies p where c.poli_id is null and p.{col} = c.norm and p.{col} <> '' {only}",
                    (keys,) if keys is not None else None)


def offers_save(items, removed, now):
    """A run's save: each offer written whole (the run already merged richer stored copies), removed ones
    deleted. Returns the count written."""
    c = required()
    from enrich import _norm as n
    ids = company_ids({n(x.get("org")): x.get("org") or "" for x in items if x.get("org")}, now)
    rows = [(x["id"], ids.get(n(x.get("org"))), x.get("origin") or "cloud", x.get("source") or "", x.get("c") or "",
             x.get("kind") or "job", x.get("title") or "", x.get("foundAt"), json.dumps(x, ensure_ascii=False), now) for x in items]
    with c.cursor() as cur:
        for i in range(0, len(rows), 300):
            cur.executemany("insert into offers (id, company_id, origin, source, country, kind, title, found_at, data, updated_at) "
                            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) on conflict (id) do update set company_id = excluded.company_id, "
                            "origin = excluded.origin, source = excluded.source, country = excluded.country, kind = excluded.kind, "
                            "title = excluded.title, found_at = excluded.found_at, data = excluded.data, updated_at = excluded.updated_at", rows[i:i + 300])
        if removed:
            cur.execute("delete from offers where id = any(%s)", (list(removed),))
    return len(rows)


def offers_all():
    return [r[0] for r in _rows("select data from offers")]


def offers_get(ids):
    """{id: offer} for the ids that are stored."""
    return dict(_rows("select id, data from offers where id = any(%s)", (list(ids),))) if ids else {}


def ratings_get(norms):
    """{norm: rating record} for the companies that have one (the 30-day review cache)."""
    want = {k: _norm(k) for k in norms}
    if not want:
        return {}
    got = dict(_rows("select norm, rating from companies where rating is not null and norm = any(%s)", (list(set(want.values())),)))
    return {k: got[n] for k, n in want.items() if n in got}


def company_rating(norm, name, rec, now):
    """A company's review rating (or "not found"), as cached in Redis parcours:companies."""
    if not norm:
        return
    c = required()
    cid = company_ids({norm: name or norm}, now).get(norm)
    with c.cursor() as cur:
        cur.execute("update companies set rating = %s, rating_at = %s where id = %s",
                    (json.dumps(rec, ensure_ascii=False), int((rec.get("at") or now / 1000) * 1000), cid))


def company_seen(entries, now):
    """Hiring log rows: [(norm, name, offer_id, day, kind, src)]. Idempotent: an offer counts once. Returns how many
    were new."""
    if not entries:
        return 0
    c = required()
    ids = company_ids({e[0]: e[1] for e in entries}, now)
    rows = [(ids[e[0]], e[2], e[3], e[4] or "job", e[5] or "s") for e in entries if e[0] in ids]
    added = 0
    with c.cursor() as cur:
        for i in range(0, len(rows), 500):
            cur.executemany("insert into company_seen (company_id, offer_id, day, kind, src) values (%s, %s, %s, %s, %s) "
                            "on conflict do nothing", rows[i:i + 500])
            added += max(cur.rowcount, 0)
    return added


def insight(key, company, role, rec, now):
    """Interview stories for one company and role, linked to the company."""
    c = required()
    from enrich import _norm as n
    cid = company_ids({n(company): company}, now).get(n(company))
    with c.cursor() as cur:
        cur.execute("insert into insights (key, company_id, role, data, updated_at) values (%s, %s, %s, %s, %s) on conflict (key) do update "
                    "set company_id = excluded.company_id, role = excluded.role, data = excluded.data, updated_at = excluded.updated_at",
                    (key, cid, role or "", json.dumps(rec, ensure_ascii=False), now))


def insights_get(keys=None):
    """{key: stories record}, all of them or just those keys."""
    if keys is None:
        return dict(_rows("select key, data from insights"))
    return dict(_rows("select key, data from insights where key = any(%s)", (list(keys),)))


# ---------- Master's and academia: keyed lists refreshed whole ----------

def dataset(name):
    """{id: record} of one set (masters, academia-schools, academia-people)."""
    return dict(_rows("select id, data from datasets where set = %s", (name,)))


def dataset_save(name, records, gone, now):
    """Upserts records (each with an id) and deletes the ids in gone. Returns the count written."""
    rows = [(name, str(r["id"]), json.dumps(r, ensure_ascii=False), now) for r in records]
    with required().cursor() as cur:
        for i in range(0, len(rows), 500):
            cur.executemany("insert into datasets (set, id, data, updated_at) values (%s, %s, %s, %s) on conflict (set, id) "
                            "do update set data = excluded.data, updated_at = excluded.updated_at", rows[i:i + 500])
        if gone:
            cur.execute("delete from datasets where set = %s and id = any(%s)", (name, [str(g) for g in gone]))
    return len(rows)


def merge_renormalised(now):
    """Companies stored under a key the current normaliser would change ("lovable labs sweden ab") are folded into
    the right one ("lovable labs"): offers, hiring log and stories move over, a missing rating is carried, and the
    old row goes. Returns how many were folded."""
    c = required()
    folded = 0
    with c.cursor() as cur:
        cur.execute("select id, norm, name, rating, rating_at from companies")
        for cid, norm, name, rating, rating_at in cur.fetchall():
            want = _norm(norm)
            if want == norm:
                continue
            if len(want) < 2:
                continue
            target = company_ids({want: name}, now)[want]
            cur.execute("update offers set company_id = %s where company_id = %s", (target, cid))
            cur.execute("update insights set company_id = %s where company_id = %s", (target, cid))
            cur.execute("insert into company_seen (company_id, offer_id, day, kind, src) select %s, offer_id, day, kind, src "
                        "from company_seen where company_id = %s on conflict do nothing", (target, cid))
            cur.execute("delete from company_seen where company_id = %s", (cid,))
            if rating is not None:
                cur.execute("update companies set rating = %s, rating_at = %s where id = %s and rating is null",
                            (json.dumps(rating, ensure_ascii=False), rating_at, target))
            cur.execute("delete from companies where id = %s", (cid,))
            folded += 1
        link_sponsors(cur)
    return folded
