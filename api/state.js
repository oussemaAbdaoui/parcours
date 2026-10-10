const { auth, upstash, redis } = require('./_lib');
const { db } = require('./_db');

// Your data: Neon Postgres, one row per item (see db/schema.sql). The newest edit of each item wins, so edits
// made on two devices to different items never overwrite each other.
// GET  -> {state, version}: the whole state, assembled from the rows.
// PUT  -> {changes: {items: [{c, id, data|null, ts}], settings: [{k, data, ts}]}}: only what changed on the device
//         (data null = deleted). Older clients that send {state} are still accepted.
// After each write the assembled state is mirrored to Redis (parcours:state), which the collectors read for
// the profile and searches. On first use the old Redis copy is imported into Neon.
const KEY = 'parcours:state';
const LISTS = ['apps', 'saved', 'journal', 'searches', 'feeds', 'queue', 'contacts'];
const NEWEST_FIRST = new Set(['saved', 'journal']); // the app adds these at the top, the others at the end
const SETTINGS = ['profile', 'status', 'notes', 'companyNotes', 'seen', 'seenAt', 'mailSeen', 'oppsHidden', 'oppsSeenAt', 'goal'];

async function load(pool) {
  const [items, settings] = await Promise.all([
    pool.query('select collection, id, data, created_at, updated_at from items where not deleted'),
    pool.query('select key, data, updated_at from settings'),
  ]);
  const state = { apps: [], saved: [], journal: [], searches: [], feeds: [], updatedAt: 0 };
  const rows = {};
  for (const r of items.rows) (rows[r.collection] = rows[r.collection] || []).push(r);
  for (const c of LISTS) {
    const list = (rows[c] || []).sort((a, b) => (NEWEST_FIRST.has(c) ? -1 : 1) * (Number(a.created_at) - Number(b.created_at)));
    state[c] = list.map((r) => r.data);
  }
  for (const r of settings.rows) state[r.key] = r.data;
  const all = [...items.rows, ...settings.rows].map((r) => Number(r.updated_at));
  state.updatedAt = all.length ? Math.max(...all) : 0;
  return state;
}

async function apply(pool, changes) {
  const client = await pool.connect();
  try {
    await client.query('begin');
    for (const it of changes.items || []) {
      if (!LISTS.includes(it.c) || !it.id || !Number.isFinite(it.ts)) continue;
      // Newest edit wins: an older edit arriving late (stale device) is ignored.
      await client.query(
        `insert into items (collection, id, data, created_at, updated_at, deleted) values ($1, $2, $3, $4, $4, $5)
         on conflict (collection, id) do update set data = excluded.data, updated_at = excluded.updated_at, deleted = excluded.deleted
         where items.updated_at < excluded.updated_at`,
        [it.c, String(it.id), JSON.stringify(it.data == null ? {} : it.data), it.ts, it.data == null]);
    }
    for (const s of changes.settings || []) {
      if (!SETTINGS.includes(s.k) || !Number.isFinite(s.ts)) continue;
      await client.query(
        `insert into settings (key, data, updated_at) values ($1, $2, $3)
         on conflict (key) do update set data = excluded.data, updated_at = excluded.updated_at where settings.updated_at < excluded.updated_at`,
        [s.k, JSON.stringify(s.data ?? null), s.ts]);
    }
    await client.query('commit');
  } catch (e) {
    await client.query('rollback');
    throw e;
  } finally {
    client.release();
  }
}

// A whole state (old Redis copy or an older client) as changes stamped with one time.
function asChanges(state, ts) {
  const items = [];
  // Millisecond offsets keep each list's order (created_at sorts the lists when they are assembled).
  for (const c of LISTS) {
    const list = state[c] || [];
    list.forEach((x, i) => { if (x && x.id) items.push({ c, id: x.id, data: x, ts: ts - (NEWEST_FIRST.has(c) ? i : list.length - 1 - i) }); });
  }
  const settings = SETTINGS.filter((k) => state[k] !== undefined).map((k) => ({ k, data: state[k], ts }));
  return { items, settings };
}

async function mirror(u, state) {
  if (u) await redis(u, ['SET', KEY, JSON.stringify(state)]);
}

/* Your documents (CV and recommendation letters as uploaded, PDF or text), kept apart from the state so the
   sync stays small: ?doc=<id> on this same function (the Hobby plan allows 12). The extracted text lives in the
   profile; the original file is what gets attached when you apply. Files up to 3 MB.
   GET ?doc=list -> [{id, name, type, size, updated}]; GET ?doc=<id> -> {id, name, type, data (base64)};
   PUT ?doc=<id> {name, type, data}; DELETE ?doc=<id>. */
const DOC_MAX = 3 * 1024 * 1024;
let docsReady = null;
function docsTable(pool) {
  docsReady = docsReady || pool.query(`create table if not exists docs (id text primary key, name text not null, type text not null,
    data text not null, size integer not null, updated_at bigint not null)`);
  return docsReady;
}
async function docs(req, res, pool) {
  const id = String(req.query.doc || '');
  if (!/^[\w-]{1,64}$/.test(id)) return res.status(400).json({ error: 'Invalid document id.' });
  await docsTable(pool);
  if (req.method === 'GET' && id === 'list') {
    const r = await pool.query('select id, name, type, size, updated_at from docs order by updated_at desc');
    return res.status(200).json({ docs: r.rows.map((d) => ({ id: d.id, name: d.name, type: d.type, size: d.size, updated: Number(d.updated_at) })) });
  }
  if (req.method === 'GET') {
    const r = await pool.query('select id, name, type, data from docs where id = $1', [id]);
    return r.rows[0] ? res.status(200).json(r.rows[0]) : res.status(404).json({ error: 'Document not found.' });
  }
  if (req.method === 'PUT') {
    const { name, type, data } = req.body || {};
    if (typeof name !== 'string' || typeof data !== 'string' || !/^(application\/pdf|text\/plain|text\/markdown)$/.test(type || '')) return res.status(400).json({ error: 'Send a PDF or text file.' });
    const size = Math.floor(data.length * 3 / 4);
    if (size > DOC_MAX) return res.status(413).json({ error: 'The file is over 3 MB.' });
    await pool.query(`insert into docs (id, name, type, data, size, updated_at) values ($1, $2, $3, $4, $5, $6)
      on conflict (id) do update set name = excluded.name, type = excluded.type, data = excluded.data, size = excluded.size, updated_at = excluded.updated_at`,
      [id, name.slice(0, 200), type, data, size, Date.now()]);
    return res.status(200).json({ ok: true, id, size });
  }
  if (req.method === 'DELETE') {
    await pool.query('delete from docs where id = $1', [id]);
    return res.status(200).json({ ok: true });
  }
  return res.status(405).json({ error: 'Method not allowed.' });
}

module.exports = async (req, res) => {
  if (!(await auth(req, res))) return;
  const pool = db(), u = upstash();
  if (!pool && !u) return res.status(501).json({ error: 'Sync is not configured.' });
  res.setHeader('Cache-Control', 'no-store');
  try {
    if (req.query && req.query.doc != null) {
      if (!pool) return res.status(501).json({ error: 'Documents need the Neon database (DATABASE_URL).' });
      return await docs(req, res, pool);
    }
    if (!pool) return legacy(req, res, u);
    if (req.method === 'GET') {
      let state = await load(pool);
      if (!state.updatedAt && u) { // first use: import the Redis copy
        const old = await redis(u, ['GET', KEY]);
        const prev = old && old.result ? JSON.parse(old.result) : null;
        if (prev) { await apply(pool, asChanges(prev, prev.updatedAt || Date.now())); state = await load(pool); }
      }
      return res.status(200).json({ state: state.updatedAt ? state : null, version: state.updatedAt, store: 'neon' });
    }
    if (req.method === 'PUT') {
      const body = req.body || {};
      const changes = body.changes || (body.state && Array.isArray(body.state.apps) ? asChanges(body.state, body.state.updatedAt || Date.now()) : null);
      if (!changes) return res.status(400).json({ error: 'Invalid data.' });
      if (JSON.stringify(changes).length > 2_000_000) return res.status(413).json({ error: 'Too many changes at once.' });
      // Never let one save wipe the data: a device with an empty or stale copy once deleted everything this way.
      // Refused: deleting 10+ items that are over 40% of what is stored, or blanking a profile that has content.
      const dels = (changes.items || []).filter((it) => it && it.data == null).length;
      if (dels >= 10) {
        const n = Number((await pool.query('select count(*) from items where not deleted')).rows[0].count);
        if (dels > 0.4 * n) return res.status(409).json({ error: `Refused: this save would delete ${dels} of your ${n} items at once.` });
      }
      const prof = (changes.settings || []).find((s) => s && s.k === 'profile');
      if (prof && (!prof.data || !Object.keys(prof.data).length)) {
        const cur = (await pool.query("select data from settings where key = 'profile'")).rows[0];
        if (cur && cur.data && Object.keys(cur.data).length) return res.status(409).json({ error: 'Refused: this save would erase your profile.' });
      }
      await apply(pool, changes);
      const state = await load(pool);
      await mirror(u, state).catch(() => {}); // the collectors' copy; never fail a save over it
      return res.status(200).json({ ok: true, version: state.updatedAt, store: 'neon' });
    }
    res.status(405).json({ error: 'Method not allowed.' });
  } catch (e) {
    res.status(502).json({ error: 'Sync storage is unavailable right now.' });
  }
};

// Without Neon: the previous single-document copy in Redis.
async function legacy(req, res, u) {
  if (req.method === 'GET') {
    const out = await redis(u, ['GET', KEY]);
    return res.status(200).json({ state: out && out.result ? JSON.parse(out.result) : null });
  }
  if (req.method === 'PUT') {
    const state = req.body && req.body.state;
    if (!state || !Array.isArray(state.apps)) return res.status(400).json({ error: 'Invalid data.' });
    const s = JSON.stringify(state);
    if (s.length > 900000) return res.status(413).json({ error: 'Data is too large to sync.' });
    await redis(u, ['SET', KEY, s]);
    return res.status(200).json({ ok: true });
  }
  res.status(405).json({ error: 'Method not allowed.' });
}
