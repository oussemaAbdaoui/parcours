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
                                                    "licensed": bool(r.get("licensed"))}, now)


def poli_people(rows, now):
    def cols(r):
        search = " ".join(str(r.get(k) or "") for k in ("name", "title", "company", "expertise", "experience")).lower()
        return {"id": int(r["id"]), "company_id": int(r["companyId"]) if r.get("companyId") else None, "name": r.get("name") or "",
                "title": r.get("title") or "", "sponsorship": r.get("sponsorship") or "", "network": bool(r.get("network")), "search": search}
    return merge("poli_people", rows, cols, now, sticky=("network",))


def poli_jobs(rows, now):
    return merge("poli_jobs", rows, lambda r: {"id": str(r["id"]), "company_id": (r.get("poli") or {}).get("companyId")}, now)
