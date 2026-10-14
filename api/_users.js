// Accounts for the login page (index.html): email + password, a session cookie, and each public user's own data.
// The admin account (users.role = 'admin') also gets the admin pass cookie (api/_lib.js), which opens the admin app's
// API; public users never reach the admin tables. Tables: users, sessions, user_items, user_settings (db/schema.sql).
const crypto = require('crypto');
const { upstash, redis, adminToken, ADMIN_COOKIE, ADMIN_DAYS } = require('./_lib');

const COOKIE = 'psid';
const SESSION_DAYS = 30, RENEW_DAYS = 15;   // a session used in its last 15 days is extended to 30 again
const DAY = 86400000;
const LISTS = ['apps', 'saved', 'queue'];  // tracker, saved offers, letters to send
const SETTINGS = ['profile', 'path', 'status', 'seen'];
const MAX_ITEMS = 3000;                    // per user, all lists together
const MAX_BODY = 1_000_000;
const EMAIL = /^[^\s@]{1,64}@[^\s@]{1,190}\.[a-z]{2,24}$/i;

// ---------- Passwords: scrypt, random salt, constant-time compare ----------
const scrypt = (pw, salt) => new Promise((ok, ko) => crypto.scrypt(pw, salt, 64, { N: 16384, r: 8, p: 1 }, (e, k) => (e ? ko(e) : ok(k))));
async function hashPassword(pw) {
  const salt = crypto.randomBytes(16);
  return `scrypt$${salt.toString('base64')}$${(await scrypt(pw, salt)).toString('base64')}`;
}
async function checkPassword(pw, stored) {
  const [kind, salt, hash] = String(stored || '').split('$');
  if (kind !== 'scrypt' || !salt || !hash) return false;
  const want = Buffer.from(hash, 'base64'), got = await scrypt(pw, Buffer.from(salt, 'base64'));
  return want.length === got.length && crypto.timingSafeEqual(want, got);
}
// Compared against when the email is unknown, so a wrong email takes as long as a wrong password.
let dummy = null;
const dummyHash = async () => dummy || (dummy = await hashPassword(crypto.randomBytes(12).toString('hex')));

// ---------- Sessions: random token in an HttpOnly cookie, its sha256 in the database ----------
const sha = (t) => crypto.createHash('sha256').update(t).digest('hex');
function readCookie(req) {
  const m = String(req.headers.cookie || '').match(new RegExp(`(?:^|;\\s*)${COOKIE}=([A-Za-z0-9_-]{20,100})`));
  return m ? m[1] : null;
}
// Every cookie set on this response, so the session and the admin pass can go out together.
function addCookie(res, name, value, maxAgeS) {
  res._cookies = (res._cookies || []).filter((c) => !c.startsWith(name + '=')).concat(`${name}=${value}; Path=/api; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAgeS}`);
  res.setHeader('Set-Cookie', res._cookies);
}
const setCookie = (res, token, maxAgeS) => addCookie(res, COOKIE, token, maxAgeS);
// The admin account also gets the admin pass (api/_lib.js), which opens the admin app's API.
function adminPass(res, user, now) {
  const token = user.role === 'admin' && adminToken(user.id, now + ADMIN_DAYS * DAY);
  if (token) addCookie(res, ADMIN_COOKIE, token, ADMIN_DAYS * 86400);
}
async function startSession(pool, res, userId, now) {
  const token = crypto.randomBytes(32).toString('base64url');
  await pool.query('insert into sessions (token, user_id, created_at, expires_at) values ($1, $2, $3, $4)',
    [sha(token), userId, now, now + SESSION_DAYS * DAY]);
  setCookie(res, token, SESSION_DAYS * 86400);
}
// The signed-in user, or null. Extends a session in its last days; drops an expired one.
async function currentUser(pool, req, res, now) {
  const token = readCookie(req);
  if (!token) return null;
  const { rows } = await pool.query(
    `select u.id, u.email, u.name, u.role, u.plan, u.plan_until, u.created_at, s.expires_at
       from sessions s join users u on u.id = s.user_id where s.token = $1`, [sha(token)]);
  const r = rows[0];
  if (!r) return null;
  if (Number(r.expires_at) <= now) {
    await pool.query('delete from sessions where token = $1', [sha(token)]);
    return null;
  }
  if (Number(r.expires_at) - now < RENEW_DAYS * DAY) {
    await pool.query('update sessions set expires_at = $2 where token = $1', [sha(token), now + SESSION_DAYS * DAY]);
    setCookie(res, token, SESSION_DAYS * 86400);
  }
  return r;
}
const publicUser = (u) => ({ id: u.id, email: u.email, name: u.name, role: u.role === 'admin' ? 'admin' : 'user', plan: u.plan === 'paid' && Number(u.plan_until) > Date.now() ? 'paid' : 'free',
  planUntil: u.plan_until == null ? null : Number(u.plan_until), createdAt: Number(u.created_at) });

// ---------- Brute-force guard: 10 failures per address (or email) in 15 minutes, counted in Redis ----------
const LOCK_AFTER = 10, LOCK_SECONDS = 900;
const clientIp = (req) => String(req.headers['x-forwarded-for'] || req.headers['x-real-ip'] || '').split(',')[0].trim() || 'unknown';
async function locked(keys) {
  const u = upstash();
  if (!u) return false;
  for (const k of keys) {
    const n = await redis(u, ['GET', 'parcours:ufail:' + k]).catch(() => null);
    if (n && +n.result >= LOCK_AFTER) return true;
  }
  return false;
}
async function failed(keys) {
  const u = upstash();
  if (!u) return;
  for (const k of keys) {
    await redis(u, ['INCR', 'parcours:ufail:' + k]).catch(() => {});
    await redis(u, ['EXPIRE', 'parcours:ufail:' + k, String(LOCK_SECONDS), 'NX']).catch(() => {});
  }
}

// ---------- Each user's data (same rules as api/state.js: the newest edit of each item wins) ----------
async function loadState(pool, uid) {
  const [items, settings] = await Promise.all([
    pool.query('select collection, data, created_at, updated_at from user_items where user_id = $1 and not deleted order by created_at', [uid]),
    pool.query('select key, data, updated_at from user_settings where user_id = $1', [uid]),
  ]);
  const state = { updatedAt: 0 };
  for (const c of LISTS) state[c] = [];
  for (const r of items.rows) state[r.collection] && state[r.collection].push(r.data);
  for (const r of settings.rows) state[r.key] = r.data;
  for (const r of [...items.rows, ...settings.rows]) state.updatedAt = Math.max(state.updatedAt, Number(r.updated_at));
  return state;
}
async function saveChanges(pool, uid, changes) {
  const items = (changes.items || []).filter((it) => it && LISTS.includes(it.c) && it.id && String(it.id).length <= 100 && Number.isFinite(it.ts));
  const settings = (changes.settings || []).filter((s) => s && SETTINGS.includes(s.k) && Number.isFinite(s.ts));
  const adds = items.filter((it) => it.data != null).length;
  if (adds) {
    const n = Number((await pool.query('select count(*) as n from user_items where user_id = $1 and not deleted', [uid])).rows[0].n);
    if (n + adds > MAX_ITEMS) return `Limit reached: ${MAX_ITEMS} items per account.`;
  }
  const client = await pool.connect();
  try {
    await client.query('begin');
    for (const it of items) {
      await client.query(
        `insert into user_items (user_id, collection, id, data, created_at, updated_at, deleted) values ($1, $2, $3, $4, $5, $5, $6)
         on conflict (user_id, collection, id) do update set data = excluded.data, updated_at = excluded.updated_at, deleted = excluded.deleted
         where user_items.updated_at < excluded.updated_at`,
        [uid, it.c, String(it.id), JSON.stringify(it.data == null ? {} : it.data), it.ts, it.data == null]);
    }
    for (const s of settings) {
      await client.query(
        `insert into user_settings (user_id, key, data, updated_at) values ($1, $2, $3, $4)
         on conflict (user_id, key) do update set data = excluded.data, updated_at = excluded.updated_at where user_settings.updated_at < excluded.updated_at`,
        [uid, s.k, JSON.stringify(s.data ?? null), s.ts]);
    }
    await client.query('commit');
  } catch (e) {
    await client.query('rollback');
    throw e;
  } finally {
    client.release();
  }
  return null;
}

// ---------- The endpoint: /api/u?a=signup|login|logout|me|state|delete ----------
async function handle(pool, req, res, now = Date.now()) {
  res.setHeader('Cache-Control', 'no-store');
  const a = String((req.query && req.query.a) || '');
  const body = req.body && typeof req.body === 'object' ? req.body : {};
  // Every write carries x-parcours: 1. Another site cannot add that header without a CORS preflight, which this
  // API never answers, so a form or script on another site cannot sign a user in, out, or change their data.
  if (req.method !== 'GET' && req.headers['x-parcours'] !== '1') return res.status(403).json({ error: 'Missing request header.' });
  if (JSON.stringify(body).length > MAX_BODY) return res.status(413).json({ error: 'Too much data at once.' });

  if (a === 'signup' && req.method === 'POST') {
    const email = String(body.email || '').trim().toLowerCase(), password = String(body.password || ''), name = String(body.name || '').trim().slice(0, 80);
    if (!EMAIL.test(email)) return res.status(400).json({ error: 'Enter a valid email address.' });
    if (password.length < 8) return res.status(400).json({ error: 'Choose a password of at least 8 characters.' });
    if (password.length > 200) return res.status(400).json({ error: 'That password is too long.' });
    if (await locked(['ip:' + clientIp(req)])) return res.status(429).json({ error: 'Too many attempts. Try again in 15 minutes.' });
    const id = crypto.randomUUID();
    const r = await pool.query(
      'insert into users (id, email, name, pass, created_at, seen_at) values ($1, $2, $3, $4, $5, $5) on conflict (email) do nothing returning id',
      [id, email, name, await hashPassword(password), now]);
    if (!r.rows.length) {
      await failed(['ip:' + clientIp(req)]);
      return res.status(409).json({ error: 'An account already uses this email. Sign in instead.' });
    }
    await startSession(pool, res, id, now);
    return res.status(201).json({ user: publicUser({ id, email, name, plan: 'free', plan_until: null, created_at: now }) });
  }

  if (a === 'login' && req.method === 'POST') {
    const email = String(body.email || '').trim().toLowerCase(), password = String(body.password || '');
    const keys = ['ip:' + clientIp(req), 'email:' + email];
    if (await locked(keys)) return res.status(429).json({ error: 'Too many wrong passwords. Try again in 15 minutes.' });
    const u = (await pool.query('select * from users where email = $1', [email])).rows[0];
    const ok = await checkPassword(password.slice(0, 200), u ? u.pass : await dummyHash());
    if (!u || !ok) {
      await failed(keys);
      return res.status(401).json({ error: 'Wrong email or password.' });
    }
    await pool.query('update users set seen_at = $2 where id = $1', [u.id, now]);
    await pool.query('delete from sessions where user_id = $1 and expires_at <= $2', [u.id, now]);
    await startSession(pool, res, u.id, now);
    adminPass(res, u, now);
    return res.status(200).json({ user: publicUser(u) });
  }

  if (a === 'logout' && req.method === 'POST') {
    const token = readCookie(req);
    if (token) await pool.query('delete from sessions where token = $1', [sha(token)]);
    setCookie(res, '', 0);
    addCookie(res, ADMIN_COOKIE, '', 0);
    return res.status(200).json({ ok: true });
  }

  const user = await currentUser(pool, req, res, now);
  if (!user) return res.status(401).json({ error: 'Not signed in.' });

  // Opening the app renews the admin pass (it expires 30 days after it was last renewed).
  if (a === 'me' && req.method === 'GET') {
    adminPass(res, user, now);
    return res.status(200).json({ user: publicUser(user) });
  }

  if (a === 'state') {
    if (req.method === 'GET') {
      const state = await loadState(pool, user.id);
      return res.status(200).json({ state, version: state.updatedAt });
    }
    if (req.method === 'PUT') {
      if (!body.changes || typeof body.changes !== 'object') return res.status(400).json({ error: 'Invalid data.' });
      const refused = await saveChanges(pool, user.id, body.changes);
      if (refused) return res.status(409).json({ error: refused });
      return res.status(200).json({ ok: true, version: (await loadState(pool, user.id)).updatedAt });
    }
  }

  // Deleting the account (and, by cascade, every session and saved item) needs the password again.
  if (a === 'delete' && req.method === 'POST') {
    const row = (await pool.query('select pass from users where id = $1', [user.id])).rows[0];
    if (!row || !(await checkPassword(String(body.password || '').slice(0, 200), row.pass))) return res.status(401).json({ error: 'Wrong password.' });
    if (user.role === 'admin') return res.status(403).json({ error: 'The admin account cannot be deleted here.' });
    await pool.query('delete from users where id = $1', [user.id]);
    setCookie(res, '', 0);
    return res.status(200).json({ ok: true });
  }

  return res.status(404).json({ error: 'Unknown request.' });
}

module.exports = { handle, hashPassword, checkPassword, LISTS, SETTINGS, MAX_ITEMS };
