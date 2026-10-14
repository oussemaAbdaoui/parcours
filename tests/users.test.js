// Public accounts (api/_users.js), sandboxed: a real Postgres in memory (PGlite) with the user tables from
// db/schema.sql, and the real handler. Nothing reaches Neon or Redis. Run: node tests/users.test.js
const fs = require('fs');
const path = require('path');
const { PGlite } = require('@electric-sql/pglite');
delete process.env.UPSTASH_REDIS_REST_URL; delete process.env.KV_REST_API_URL;   // no rate-limit store in the sandbox
process.env.APP_PASSWORD = 'sandbox-app-password';
const { execFileSync } = require('child_process');
const { handle, MAX_ITEMS } = require('../api/_users');
const { auth } = require('../api/_lib');
const fixtures = require('./fixtures');

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

// A browser: keeps its cookies between calls, like the real one (Path=/api, HttpOnly).
function browser(pool) {
  const jar = {};
  const cookieHeader = () => Object.entries(jar).map(([k, v]) => k + '=' + v).join('; ');
  return async function call(method, a, body, { header = true, now } = {}) {
    const req = { method, query: { a }, body: body || {}, headers: Object.assign({ 'x-forwarded-for': '10.0.0.1' }, header ? { 'x-parcours': '1' } : {}, cookieHeader() ? { cookie: cookieHeader() } : {}) };
    const out = { status: 0, json: null, headers: {} };
    const res = {
      setHeader(k, v) { out.headers[k.toLowerCase()] = v; },
      status(s) { out.status = s; return this; },
      json(j) { out.json = j; return this; },
    };
    await handle(pool, req, res, now || Date.now());
    const set = [].concat(out.headers['set-cookie'] || []);
    for (const c of set) { const m = c.match(/^([a-z]+)=([^;]*)/); if (m) { if (m[2]) jar[m[1]] = m[2]; else delete jar[m[1]]; } }
    out.setCookie = set.join(' | ');
    out.jar = jar;
    return out;
  };
}
// What the admin endpoints (api/_lib.js auth) answer for these cookies.
async function adminAuth(cookie) {
  const out = { status: 200 };
  const res = { status(s) { out.status = s; return this; }, json() { return this; } };
  return (await auth({ headers: cookie ? { cookie } : {} }, res)) ? 200 : out.status;
}
// The Python check in api/boards.py, run as written there (its function, without the rest of the file).
function pythonAccepts(cookie) {
  const src = fs.readFileSync(path.join(__dirname, '..', 'api', 'boards.py'), 'utf8');
  const fn = src.match(/ {4}def _admin_cookie_ok\(self, pw\):[\s\S]*?return hmac\.compare_digest\(sig, m\.group\(3\)\)\r?\n/)[0];
  const code = 'import base64, hashlib, hmac, re, sys, time\nclass H:\n    def __init__(self, c): self.headers = {"cookie": c}\n' + fn +
    'print(H(sys.argv[1])._admin_cookie_ok(sys.argv[2]))';
  return execFileSync(process.platform === 'win32' ? 'python' : 'python3', ['-c', code, cookie, process.env.APP_PASSWORD], { encoding: 'utf8' }).trim() === 'True';
}

(async () => {
  const pg = new PGlite();
  await pg.exec(userTables);
  await fixtures.load(pg);
  const pool = poolOf(pg);
  const amel = browser(pool), sami = browser(pool), stranger = browser(pool);
  const day = 86400000;

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
  r = await amel('GET', 'me', null, { now: Date.now() + 20 * day });
  check('session used after 20 days is renewed', r.status === 200 && /Max-Age=2592000/.test(r.setCookie || ''), r.setCookie);
  r = await amel('GET', 'me', null, { now: Date.now() + 80 * day });
  check('session unused for 30+ days expires', r.status === 401);

  // The admin account: same login page, plus the admin pass that opens the admin app's API
  r = await sami('POST', 'login', { email: 'sami@example.tn', password: 'long-enough-2' });
  check('a public user gets no admin pass', !r.jar.padm && r.json.user.role === 'user', r.setCookie);
  check('a public user is refused by the admin API', (await adminAuth('psid=' + r.jar.psid)) === 401);
  const boss = browser(pool);
  await boss('POST', 'signup', { email: 'boss@example.tn', password: 'admin-pass-123', name: 'Boss' });
  await pg.query("update users set role = 'admin' where email = 'boss@example.tn'");
  r = await boss('POST', 'login', { email: 'boss@example.tn', password: 'admin-pass-123' });
  check('the admin account signs in with role admin', r.status === 200 && r.json.user.role === 'admin', r.json);
  check('and gets the admin pass (HttpOnly, Secure, path /api)', !!r.jar.padm && /padm=[^;]+; Path=\/api; HttpOnly; Secure; SameSite=Lax/.test(r.setCookie), r.setCookie);
  const pass = 'padm=' + r.jar.padm;
  check('the admin API accepts the pass', (await adminAuth(pass)) === 200);
  check('the Python function (api/boards.py) accepts the same pass', pythonAccepts(pass));
  const forged = pass.replace(/\.(\d+)\./, (m, e) => '.' + (Number(e) + 1) + '.');
  check('a pass with a changed expiry is refused (Node)', (await adminAuth(forged)) === 401);
  check('a pass with a changed expiry is refused (Python)', !pythonAccepts(forged));
  const other = pass.replace(/^padm=[^.]+/, 'padm=' + (await pg.query("select id from users where email = 'sami@example.tn'")).rows[0].id);
  check('a pass moved to another user is refused', (await adminAuth(other)) === 401 && !pythonAccepts(other));
  process.env.APP_PASSWORD = 'changed';
  check('changing APP_PASSWORD signs every admin out', (await adminAuth(pass)) === 401 && !pythonAccepts(pass));
  process.env.APP_PASSWORD = 'sandbox-app-password';
  r = await boss('GET', 'me', null, { now: Date.now() + 10 * day });
  check('opening the app renews the admin pass', !!r.jar.padm && 'padm=' + r.jar.padm !== pass);
  r = await boss('POST', 'delete', { password: 'admin-pass-123' });
  check('the admin account cannot be deleted from the app', r.status === 403);
  r = await boss('POST', 'logout');
  check('sign-out removes the admin pass too', !r.jar.padm && !r.jar.psid && /padm=; Path=\/api.*Max-Age=0/.test(r.setCookie), r.setCookie);

  // Discover: what the collectors gathered, by category (asked as a signed-in user)
  const reader = browser(pool);
  await reader('POST', 'login', { email: 'sami@example.tn', password: 'long-enough-2' });
  const readerCookie = 'psid=' + (await reader('GET', 'me')).jar.psid;
  const ask = async (params) => {
    const out = {};
    const res = { setHeader() {}, status(x) { out.status = x; return this; }, json(j) { out.json = j; return this; } };
    await handle(pool, { method: 'GET', query: { a: 'discover', ...params }, body: {}, headers: { cookie: readerCookie } }, res);
    return out;
  };
  const names = (o) => o.json.items.map((i) => i.title).sort().join(' | ');
  let d = await ask({ cat: 'jobs' });
  check('jobs: graduate jobs only', d.status === 200 && names(d) === 'Data Engineer | Développeur Full stack | Ingénieur en Apprentissage Automatique', names(d));
  d = await ask({ cat: 'internships' });
  check('internships: by title (stage, PFE) and by contract type', names(d) === 'Software Engineer | Stage PFE Data Science', names(d));
  d = await ask({ cat: 'alternance' });
  check('alternance: "apprentissage automatique" (machine learning) is not an apprenticeship', names(d) === 'Développeur web en alternance', names(d));
  d = await ask({ cat: 'phd' });
  check('PhD offers', names(d) === 'PhD in NLP');
  d = await ask({ cat: 'masters' });
  check("master's programmes, not scholarships", names(d) === 'MSc Data Science | Master IA', names(d));
  d = await ask({ cat: 'scholarships' });
  check('scholarships', names(d) === 'Eiffel Scholarship');
  d = await ask({ cat: 'schools' });
  check('schools: universities only, not labs', names(d) === 'University of Carthage', names(d));
  d = await ask({ cat: 'professors' });
  check('professors with their university', d.json.items[0].title === 'Prof Amira Test' && d.json.items[0].org === 'University of Carthage', d.json.items[0]);
  check('professor emails never leave the database', !JSON.stringify(d.json).includes('amira@example.tn'));
  d = await ask({ cat: 'jobs' });
  check('offers: no full text or scoring details sent', !JSON.stringify(d.json).includes('secret scoring detail') && d.json.items.every((i) => i.text.length <= 240));
  check('country counts for the filter', d.json.countries.length === 3 && d.json.countries.every((x) => x.n === 1), d.json.countries);
  d = await ask({ cat: 'jobs', c: 'tn' });
  check('country filter', names(d) === 'Développeur Full stack' && d.json.total === 1, names(d));
  d = await ask({ cat: 'jobs', q: 'engineer' });
  check('search', names(d) === 'Data Engineer', names(d));
  d = await ask({ cat: 'jobs', q: "x'; drop table offers; --" });
  check('search text is not SQL', d.status === 200 && Number((await pg.query('select count(*) n from offers')).rows[0].n) === fixtures.OFFERS.length);
  r = await stranger('GET', 'discover');
  check('discover needs an account', r.status === 401);

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
