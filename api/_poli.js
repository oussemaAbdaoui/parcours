const { upstash, redis } = require('./_lib');

// Live Poli (withpoli.com) inside the app: signs in with POLI_EMAIL / POLI_PASSWORD (Vercel environment) and relays
// a fixed list of Poli API calls the Poli web app makes: the jobs feed and its paging, applied jobs, filter options,
// any company's open jobs and sponsored employees, the network. The only writes are the feed preferences and sort
// order, which is how the Poli feed is filtered. The Poli session cookie is kept in Redis (about an hour), so the
// app does not sign in on every request. Served by api/opps.js (?set=poli-live: the Hobby plan allows 12 functions).
// Collector side: collector/poli.py.
const BASE = 'https://app.withpoli.com/api/';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36';
const SESSION_KEY = 'parcours:poli:session';
let memo = null; // cookie cached in this instance

const num = (v) => (Number.isInteger(v) && v >= 0 ? v : 0);
const ids = (a) => (Array.isArray(a) ? a.filter((v) => Number.isInteger(v)).slice(0, 80) : []);

// action -> [method, path, body from the request]
const ACTIONS = {
  feed: (b) => ['POST', 'jobs/', { initialFetch: !!b.initialFetch }],
  applied: (b) => ['POST', 'jobs/applied', { initialFetch: !!b.initialFetch }],
  preferences: () => ['GET', 'jobs/preferences'],
  categories: () => ['GET', 'jobs/categories'],
  types: () => ['GET', 'jobs/types'],
  seniorities: () => ['GET', 'jobs/seniorities'],
  locations: () => ['GET', 'jobs/locations'],
  stats: () => ['GET', 'stats/sponsored-jobs'],
  companyJobs: (b) => ['POST', 'company/jobs', { companyId: num(b.companyId), offset: num(b.offset) }],
  companyEmployees: (b) => ['POST', 'company/employees', { companyId: num(b.companyId), offset: num(b.offset) }],
  network: (b) => ['POST', 'employees/network', { initialFetch: !!b.initialFetch }],
  savePreferences: (b) => ['POST', 'jobs/preferences', {
    jobTypes: ids(b.jobTypes), jobCategories: ids(b.jobCategories), jobSeniorities: ids(b.jobSeniorities),
    jobLocations: ids(b.jobLocations), immediateSponsorshipRequired: !!b.immediateSponsorshipRequired
  }],
  sort: (b) => ['POST', 'jobs/sort-preference', { sortBy: b.sortBy === 'date_added' ? 'date_added' : 'relevance' }]
};

// Keeps the name=value part of every Set-Cookie, merged over the cookies we already had.
function mergeCookies(cookie, res) {
  const jar = new Map((cookie || '').split('; ').filter(Boolean).map((c) => [c.split('=')[0], c]));
  const set = typeof res.headers.getSetCookie === 'function' ? res.headers.getSetCookie() : [];
  set.forEach((c) => { const nv = c.split(';')[0]; const name = nv.split('=')[0]; if (/=$/.test(nv) || /Max-Age=0/i.test(c)) jar.delete(name); else jar.set(name, nv); });
  return [...jar.values()].join('; ');
}

async function signIn(u) {
  const email = process.env.POLI_EMAIL, password = process.env.POLI_PASSWORD;
  if (!email || !password) throw { status: 501, message: 'Add POLI_EMAIL and POLI_PASSWORD in Vercel, then redeploy.' };
  const r = await fetch(BASE + 'auth/sign-in', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'User-Agent': UA },
    body: JSON.stringify({ emailAddress: email, password })
  });
  const j = await r.json().catch(() => ({}));
  const cookie = mergeCookies('', r);
  if (!r.ok || j.error || !cookie) throw { status: 502, message: 'Poli sign-in failed: ' + ((j.error && j.error.message) || r.status) };
  await save(u, cookie);
  return cookie;
}

async function save(u, cookie) {
  memo = cookie;
  if (u) await redis(u, ['SET', SESSION_KEY, cookie, 'EX', '3300']).catch(() => {});
}

async function cookieFor(u) {
  if (memo) return memo;
  if (u) { const r = await redis(u, ['GET', SESSION_KEY]).catch(() => null); if (r && r.result) return (memo = r.result); }
  return signIn(u);
}

async function call(u, method, path, body, retried) {
  const cookie = await cookieFor(u);
  const r = await fetch(BASE + path, {
    method, headers: { 'Content-Type': 'application/json', 'User-Agent': UA, Cookie: cookie },
    ...(method === 'POST' ? { body: JSON.stringify(body || {}) } : {})
  });
  const j = await r.json().catch(() => ({}));
  const unauth = r.status === 401 || /unauthori[sz]ed|not authenticated|sign in/i.test((j.error && j.error.message) || '');
  if (unauth && !retried) { memo = null; await signIn(u); return call(u, method, path, body, true); }
  if (!r.ok || j.error) throw { status: r.status >= 400 ? r.status : 502, message: 'Poli: ' + ((j.error && j.error.message) || 'HTTP ' + r.status) };
  const next = mergeCookies(cookie, r);
  if (next !== cookie) await save(u, next); // Poli refreshed the session
  return j.data;
}

module.exports = async (req, res) => {
  const b = (req.method === 'POST' ? req.body : req.query) || {};
  const list = Array.isArray(b.actions) ? b.actions : [b];
  if (!list.length || list.length > 8 || list.some((a) => !ACTIONS[a && a.action])) return res.status(400).json({ error: 'Unknown Poli action.' });
  const u = upstash();
  try {
    // Several actions in one request run one after the other: the feed's paging lives in the Poli session.
    const out = [];
    for (const a of list) { const [m, p, body] = ACTIONS[a.action](a); out.push(await call(u, m, p, body)); }
    res.status(200).json(Array.isArray(b.actions) ? { results: out } : { data: out[0] });
  } catch (e) {
    res.status(e.status && e.status < 600 ? e.status : 502).json({ error: e.message || 'Poli is unavailable right now.' });
  }
};
