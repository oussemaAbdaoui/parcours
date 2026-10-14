// Public accounts (api/_users.js), sandboxed: a real Postgres in memory (PGlite) with the user tables from
// db/schema.sql, and the real handler. Nothing reaches Neon or Redis. Run: node tests/users.test.js
const fs = require('fs');
const path = require('path');
const { PGlite } = require('@electric-sql/pglite');
delete process.env.UPSTASH_REDIS_REST_URL; delete process.env.KV_REST_API_URL;   // no rate-limit store in the sandbox
const { handle, MAX_ITEMS } = require('../api/_users');

const schema = fs.readFileSync(path.join(__dirname, '..', 'db', 'schema.sql'), 'utf8');
const userTables = schema.slice(schema.indexOf('-- ---------- Public users'));

// pg.Pool shape over PGlite: query() and connect() -> client with query/release.
function poolOf(pg) {
  const query = (text, params) => pg.query(text, params);
  return { query, connect: async () => ({ query, release() {} }) };
}

let passed = 0, failed = 0;
function check(name, cond, detail) {
  if (cond) { passed++; console.log('PASS ' + name); } else { failed++; console.log('FAIL ' + name + (detail ? ' -> ' + JSON.stringify(detail) : '')); }
}

// A browser: keeps the cookie between calls, like the real one (Path=/api, HttpOnly).
function browser(pool) {
  let cookie = '';
  return async function call(method, a, body, { header = true, now } = {}) {
    const req = { method, query: { a }, body: body || {}, headers: Object.assign({ 'x-forwarded-for': '10.0.0.1' }, header ? { 'x-parcours': '1' } : {}, cookie ? { cookie } : {}) };
    const out = { status: 0, json: null, headers: {} };
    const res = {
      setHeader(k, v) { out.headers[k.toLowerCase()] = v; },
      status(s) { out.status = s; return this; },
      json(j) { out.json = j; return this; },
    };
    await handle(pool, req, res, now || Date.now());
    const set = out.headers['set-cookie'];
    if (set) { const m = set.match(/^psid=([^;]*)/); cookie = m && m[1] ? 'psid=' + m[1] : ''; }
    out.setCookie = set;
    return out;
  };
}

(async () => {
  const pg = new PGlite();
  await pg.exec(userTables);
  const pool = poolOf(pg);
  const amel = browser(pool), sami = browser(pool), stranger = browser(pool);

  // Sign-up
  let r = await amel('POST', 'signup', { email: '  Amel@Example.TN ', password: 'long-enough-1', name: 'Amel' });
  check('sign-up creates the account and signs in', r.status === 201 && r.json.user.email === 'amel@example.tn' && r.json.user.plan === 'free', r);
  check('session cookie is HttpOnly, Secure, SameSite=Lax, path /api', /HttpOnly/.test(r.setCookie) && /Secure/.test(r.setCookie) && /SameSite=Lax/.test(r.setCookie) && /Path=\/api/.test(r.setCookie), r.setCookie);
  const stored = (await pg.query('select pass from users')).rows[0].pass;
  check('password stored hashed, never in clear', stored.startsWith('scrypt$') && !stored.includes('long-enough-1'));
  const tok = (await pg.query('select token from sessions')).rows[0].token;
  check('session stored as a hash, not the cookie value', /^[0-9a-f]{64}$/.test(tok) && !r.setCookie.includes(tok));
  r = await sami('POST', 'signup', { email: 'amel@example.tn', password: 'another-pass' });
  check('same email twice is refused', r.status === 409, r);
  r = await sami('POST', 'signup', { email: 'not-an-email', password: 'long-enough-1' });
  check('invalid email refused', r.status === 400);
  r = await sami('POST', 'signup', { email: 'sami@example.tn', password: 'short' });
  check('short password refused', r.status === 400);
  r = await stranger('POST', 'signup', { email: 'x@example.tn', password: 'long-enough-1' }, { header: false });
  check('write without the x-parcours header refused (other sites)', r.status === 403);

  // Who am I
  r = await amel('GET', 'me');
  check('me returns the signed-in user', r.status === 200 && r.json.user.email === 'amel@example.tn', r);
  r = await stranger('GET', 'me');
  check('me without a session is 401', r.status === 401);
  r = await stranger('GET', 'state');
  check('state without a session is 401', r.status === 401);

  // Data: each user sees only their own
  const t = Date.now();
  r = await amel('PUT', 'state', { changes: { items: [{ c: 'apps', id: 'a1', data: { id: 'a1', role: 'ML engineer', org: 'InstaDeep' }, ts: t }],
    settings: [{ k: 'profile', data: { name: 'Amel', skills: ['python'] }, ts: t }, { k: 'path', data: 'work', ts: t }, { k: 'notAllowed', data: 1, ts: t }] } });
  check('save own data', r.status === 200, r);
  await sami('POST', 'signup', { email: 'sami@example.tn', password: 'long-enough-2' });
  await sami('PUT', 'state', { changes: { items: [{ c: 'apps', id: 'a1', data: { id: 'a1', role: 'PhD', org: 'Inria' }, ts: t }] } });
  r = await amel('GET', 'state');
  check('user sees own tracker only', r.json.state.apps.length === 1 && r.json.state.apps[0].org === 'InstaDeep', r.json);
  check('user sees own profile and path', r.json.state.profile.name === 'Amel' && r.json.state.path === 'work');
  check('unknown settings are not stored', !('notAllowed' in r.json.state));
  r = await sami('GET', 'state');
  check('other user sees theirs, same item id kept apart', r.json.state.apps.length === 1 && r.json.state.apps[0].org === 'Inria' && !r.json.state.profile, r.json);
  await amel('PUT', 'state', { changes: { items: [{ c: 'apps', id: 'a1', data: { id: 'a1', role: 'stale' }, ts: t - 1000 }] } });
  r = await amel('GET', 'state');
  check('older edit does not overwrite a newer one', r.json.state.apps[0].role === 'ML engineer');
  await amel('PUT', 'state', { changes: { items: [{ c: 'apps', id: 'a1', data: null, ts: t + 1000 }] } });
  r = await amel('GET', 'state');
  check('deletion removes the item', r.json.state.apps.length === 0);
  r = await amel('PUT', 'state', { changes: { items: Array.from({ length: MAX_ITEMS + 1 }, (_, i) => ({ c: 'saved', id: 's' + i, data: { id: 's' + i }, ts: t })) } });
  check('item limit per account enforced', r.status === 409 || r.status === 413, r.status);
  check('admin tables untouched by design (no items/settings table needed)', !(await pg.query("select 1 from information_schema.tables where table_name in ('items','settings')")).rows.length);

  // Sign-in and sign-out
  r = await stranger('POST', 'login', { email: 'amel@example.tn', password: 'wrong-password' });
  check('wrong password refused', r.status === 401 && r.json.error === 'Wrong email or password.');
  r = await stranger('POST', 'login', { email: 'nobody@example.tn', password: 'whatever-123' });
  check('unknown email gives the same answer', r.status === 401 && r.json.error === 'Wrong email or password.');
  r = await stranger('POST', 'login', { email: 'AMEL@example.tn', password: 'long-enough-1' });
  check('sign in (email case ignored)', r.status === 200 && r.json.user.email === 'amel@example.tn', r);
  r = await stranger('GET', 'state');
  check('second device sees the same data', r.status === 200 && r.json.state.profile.name === 'Amel');
  r = await stranger('POST', 'logout');
  check('sign out clears the cookie', r.status === 200 && /Max-Age=0/.test(r.setCookie));
  r = await stranger('GET', 'me');
  check('after sign-out: not signed in', r.status === 401);
  r = await amel('GET', 'me');
  check('other device stays signed in', r.status === 200);

  // Session expiry and renewal
  const day = 86400000;
  r = await amel('GET', 'me', null, { now: Date.now() + 20 * day });
  check('session used after 20 days is renewed', r.status === 200 && /Max-Age=2592000/.test(r.setCookie || ''), r.setCookie);
  r = await amel('GET', 'me', null, { now: Date.now() + 80 * day });
  check('session unused for 30+ days expires', r.status === 401);

  // Account deletion
  await amel('POST', 'login', { email: 'amel@example.tn', password: 'long-enough-1' });
  r = await amel('POST', 'delete', { password: 'wrong' });
  check('delete needs the password', r.status === 401);
  r = await amel('POST', 'delete', { password: 'long-enough-1' });
  const left = (await pg.query("select (select count(*) from users where email = 'amel@example.tn') u, (select count(*) from user_settings us join users x on x.id = us.user_id where x.email = 'amel@example.tn') s")).rows[0];
  check('delete removes the account and its data', r.status === 200 && Number(left.u) === 0 && Number(left.s) === 0, left);
  const orphans = (await pg.query('select count(*) n from user_items where user_id not in (select id from users)')).rows[0].n;
  check('no data left behind', Number(orphans) === 0);
  r = await sami('GET', 'state');
  check('other users unaffected', r.status === 200 && r.json.state.apps.length === 1);

  console.log(`\n${passed}/${passed + failed} passed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
