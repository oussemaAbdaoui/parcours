"""Neon Postgres for the collectors: collected data moves here from Redis one store at a time (Poli first).

DATABASE_URL (or DATABASE_URL_UNPOOLED) comes from the environment: a GitHub secret for the cloud runs,
~/parcours-collector/upstash.env on the PC. Without it every function is a no-op, so a run never fails for it.
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


def _clean(r):
    """Empty values dropped, so a merge never blanks a stored field."""
    return {k: v for k, v in r.items() if v not in ("", None, [], {})}


def merge(table, rows, columns, now, sticky=()):
    """Upserts rows into table: columns(r) gives the indexed columns, the record itself goes to data, merged with
    what is stored (old || new, empty fields dropped first) and stamped seen_at. sticky: boolean columns that stay
    true once set (a person seen in the network stays flagged when a company list later omits the flag). Never deletes."""
    c = conn()
    if not c or not rows:
        return 0
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
    c = conn()
    canon = {k: _norm(k) for k in names if k}
    canon = {k: v for k, v in canon.items() if len(v) >= 2}
    if not c or not canon:
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
    """Mirrors a run's save: each offer written whole (the run already merged richer stored copies), removed ones
    deleted. Returns the count written."""
    c = conn()
    if not c:
        return 0
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


def company_rating(norm, name, rec, now):
    """A company's review rating (or "not found"), as cached in Redis parcours:companies."""
    c = conn()
    if not c or not norm:
        return
    cid = company_ids({norm: name or norm}, now).get(norm)
    with c.cursor() as cur:
        cur.execute("update companies set rating = %s, rating_at = %s where id = %s",
                    (json.dumps(rec, ensure_ascii=False), int((rec.get("at") or now / 1000) * 1000), cid))


def company_seen(entries, now):
    """Hiring log rows: [(norm, name, offer_id, day, kind, src)]. Idempotent: an offer counts once."""
    c = conn()
    if not c or not entries:
        return 0
    ids = company_ids({e[0]: e[1] for e in entries}, now)
    rows = [(ids[e[0]], e[2], e[3], e[4] or "job", e[5] or "s") for e in entries if e[0] in ids]
    with c.cursor() as cur:
        for i in range(0, len(rows), 500):
            cur.executemany("insert into company_seen (company_id, offer_id, day, kind, src) values (%s, %s, %s, %s, %s) "
                            "on conflict do nothing", rows[i:i + 500])
    return len(rows)


def insight(key, company, role, rec, now):
    """Interview stories for one company and role, linked to the company."""
    c = conn()
    if not c:
        return
    from enrich import _norm as n
    cid = company_ids({n(company): company}, now).get(n(company))
    with c.cursor() as cur:
        cur.execute("insert into insights (key, company_id, role, data, updated_at) values (%s, %s, %s, %s, %s) on conflict (key) do update "
                    "set company_id = excluded.company_id, role = excluded.role, data = excluded.data, updated_at = excluded.updated_at",
                    (key, cid, role or "", json.dumps(rec, ensure_ascii=False), now))


def merge_renormalised(now):
    """Companies stored under a key the current normaliser would change ("lovable labs sweden ab") are folded into
    the right one ("lovable labs"): offers, hiring log and stories move over, a missing rating is carried, and the
    old row goes. Returns how many were folded."""
    c = conn()
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
