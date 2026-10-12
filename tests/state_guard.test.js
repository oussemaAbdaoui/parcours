// The sync server's wipe guards (api/state.js), run against an in-memory stand-in for Postgres: nothing real is
// touched. A device with an empty or stale copy once deleted everything; these saves must be refused.
// Run: node tests/state_guard.test.js (exit code 1 on any failure).
const Module = require('module');
const path = require('path');

// In-memory tables: items (collection, id) and settings (key), with the few queries state.js makes.
function fakePool(nItems, profile) {
  const items = new Map(), settings = new Map();
  for (let i = 0; i < nItems; i++) items.set(`apps|a${i}`, { collection: 'apps', id: `a${i}`, data: { id: `a${i}` }, created_at: i, updated_at: i, deleted: false });
  if (profile) settings.set('profile', { key: 'profile', data: profile, updated_at: 1 });
  const writes = [];
  const query = async (sql, args = []) => {
    if (/^select count\(\*\) from items where not deleted/.test(sql)) return { rows: [{ count: String([...items.values()].filter((r) => !r.deleted).length) }] };
    if (/select data from settings where key = 'profile'/.test(sql)) return { rows: settings.has('profile') ? [settings.get('profile')] : [] };
    if (/select collection, id, data, created_at, updated_at from items/.test(sql)) return { rows: [...items.values()].filter((r) => !r.deleted) };
    if (/select key, data, updated_at from settings/.test(sql)) return { rows: [...settings.values()] };
    if (/^(begin|commit|rollback)$/.test(sql)) return { rows: [] };
    if (/insert into items/.test(sql)) { writes.push(args); const [c, id, data, ts, del] = args; items.set(`${c}|${id}`, { collection: c, id, data: JSON.parse(data), created_at: ts, updated_at: ts, deleted: del }); return { rows: [] }; }
    if (/insert into settings/.test(sql)) { writes.push(args); settings.set(args[0], { key: args[0], data: JSON.parse(args[1]), updated_at: args[2] }); return { rows: [] }; }
    throw new Error('unexpected query: ' + sql.slice(0, 60));
  };
  return { query, connect: async () => ({ query, release() {} }), writes, items };
}

let pool;
const load = Module._load;
Module._load = function (req, parent, isMain) {
  if (parent && parent.filename && parent.filename.endsWith(path.join('api', 'state.js'))) {
    if (req === './_db') return { db: () => pool };
    if (req === './_lib') return { auth: async () => true };
  }
  return load.apply(this, arguments);
};
const handler = require('../api/state.js');

async function put(body) {
  let status = 200, out = null;
  const res = { setHeader() {}, status(s) { status = s; return this; }, json(j) { out = j; return this; }, end() { return this; } };
  await handler({ method: 'PUT', body, headers: {}, query: {} }, res);
  return { status, out };
}
const del = (n, from = 0) => Array.from({ length: n }, (_, i) => ({ c: 'apps', id: `a${from + i}`, data: null, ts: 1e13 }));

const cases = [
  ['deleting 12 of 20 items at once is refused', async () => { pool = fakePool(20); const r = await put({ changes: { items: del(12) } }); return r.status === 409 && !pool.writes.length; }],
  ['deleting 3 of 20 items goes through', async () => { pool = fakePool(20); const r = await put({ changes: { items: del(3) } }); return r.status === 200 && pool.writes.length === 3; }],
  ['deleting 10 of 100 items goes through (under 40%)', async () => { pool = fakePool(100); const r = await put({ changes: { items: del(10) } }); return r.status === 200; }],
  ['blanking a profile that has content is refused', async () => { pool = fakePool(5, { name: 'X', skills: ['python'] }); const r = await put({ changes: { settings: [{ k: 'profile', data: {}, ts: 1e13 }] } }); return r.status === 409 && !pool.writes.length; }],
  ['an older client sending an empty whole state deletes nothing', async () => {
    pool = fakePool(20); const r = await put({ state: { apps: [], updatedAt: 1e13 } });
    return r.status === 200 && [...pool.items.values()].every((x) => !x.deleted);
  }],
  ['an edit older than the stored one is ignored', async () => {
    pool = fakePool(1); pool.items.get('apps|a0').updated_at = 50;
    // The real query has "where items.updated_at < excluded.updated_at": check the SQL carries it.
    const src = require('fs').readFileSync(path.join(__dirname, '..', 'api', 'state.js'), 'utf8');
    return /where items\.updated_at < excluded\.updated_at/.test(src) && /where settings\.updated_at < excluded\.updated_at/.test(src);
  }],
];

(async () => {
  let failed = 0;
  for (const [name, fn] of cases) {
    let pass = false;
    try { pass = await fn(); } catch (e) { console.log('  error:', e.message); }
    if (!pass) failed++;
    console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}`);
  }
  console.log(`\n${cases.length - failed}/${cases.length} passed`);
  process.exit(failed ? 1 : 0);
})();
