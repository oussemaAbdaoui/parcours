const crypto = require('crypto');

function safeEq(a, b) {
  const A = Buffer.from(String(a));
  const B = Buffer.from(String(b));
  if (A.length !== B.length) { crypto.timingSafeEqual(A, A); return false; }
  return crypto.timingSafeEqual(A, B);
}

// Every endpoint requires the shared password. Without APP_PASSWORD the API stays closed,
// so nobody can use your keys or read your data. Wrong passwords are counted per address in Redis: after
// LOCK_AFTER of them within LOCK_SECONDS, that address is refused (even with the right password) until the window ends.
const LOCK_AFTER = 10, LOCK_SECONDS = 900;
const clientIp = (req) => String(req.headers['x-forwarded-for'] || req.headers['x-real-ip'] || '').split(',')[0].trim() || 'unknown';
async function auth(req, res) {
  const pw = process.env.APP_PASSWORD;
  if (!pw) {
    res.status(503).json({ error: 'APP_PASSWORD is not set on the server. Add it in Vercel, then redeploy.' });
    return false;
  }
  const u = upstash(), key = 'parcours:authfail:' + clientIp(req);
  if (u) {
    const n = await redis(u, ['GET', key]).catch(() => null);
    if (n && +n.result >= LOCK_AFTER) {
      res.status(429).json({ error: 'Too many wrong passwords from this connection. Try again in 15 minutes.' });
      return false;
    }
  }
  if (!safeEq(req.headers['x-app-password'] || '', pw)) {
    if (u) {
      await redis(u, ['INCR', key]).catch(() => {});
      await redis(u, ['EXPIRE', key, String(LOCK_SECONDS), 'NX']).catch(() => {});
    }
    res.status(401).json({ error: 'Wrong or missing password.' });
    return false;
  }
  return true;
}

async function fetchJson(url, opts = {}, ms = 9000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { ...opts, signal: ctl.signal });
    const text = await r.text();
    let json = null;
    if (text) { try { json = JSON.parse(text); } catch (e) { /* not JSON */ } }
    if (!r.ok) { const err = new Error('HTTP ' + r.status); err.status = r.status; throw err; }
    return { status: r.status, json, text };
  } catch (e) {
    if (e.name === 'AbortError') { const err = new Error('Timed out'); err.status = 504; throw err; }
    throw e;
  } finally { clearTimeout(t); }
}

const isoDate = (v) => {
  if (!v && v !== 0) return '';
  const d = typeof v === 'number' ? new Date(v * (v < 1e12 ? 1000 : 1)) : new Date(v);
  return isNaN(d) ? '' : d.toISOString().slice(0, 10);
};

const clean = (s) => String(s == null ? '' : s).replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();

function upstash() {
  const e = process.env;
  const url = e.UPSTASH_REDIS_REST_URL || e.KV_REST_API_URL;
  const token = e.UPSTASH_REDIS_REST_TOKEN || e.KV_REST_API_TOKEN;
  return url && token ? { url, token } : null;
}

async function redis(u, args) {
  const r = await fetch(u.url, {
    method: 'POST', headers: { Authorization: 'Bearer ' + u.token, 'Content-Type': 'application/json' },
    body: JSON.stringify(args)
  });
  if (!r.ok) throw new Error('Storage answered HTTP ' + r.status);
  return r.json();
}

const aiOn = () => !!process.env.ANTHROPIC_API_KEY;

// Calls the Anthropic Messages API. Throws { status, message } on failure.
// Current models think before they answer, and the thinking counts against max_tokens: leave room for both, and
// keep quick tasks (letter rewrites) at low effort so they think briefly.
async function claude(prompt, { tier, maxTokens = 16000, ms = 55000 } = {}) {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) throw { status: 503, message: 'Claude features are off. Add ANTHROPIC_API_KEY in Vercel.' };
  const quick = tier === 'quick';
  const model = quick
    ? (process.env.ANTHROPIC_MODEL_FAST || 'claude-haiku-5-5')
    : (process.env.ANTHROPIC_MODEL || 'claude-sonnet-5-5');
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST', signal: ctl.signal,
      headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
      body: JSON.stringify({ model, max_tokens: maxTokens, output_config: { effort: quick ? 'low' : 'medium' },
        messages: [{ role: 'user', content: prompt }] })
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw { status: 502, message: (j.error && j.error.message) || 'Claude request failed (HTTP ' + r.status + ').' };
    const text = (j.content || []).filter((b) => b.type === 'text').map((b) => b.text).join('\n').trim();
    if (j.stop_reason === 'refusal') throw { status: 502, message: 'Claude declined this request. Try rewording it.' };
    if (!text && j.stop_reason === 'max_tokens') throw { status: 502, message: 'Claude ran out of room before answering. Try again with a shorter offer or CV.' };
    if (!text) throw { status: 502, message: 'Claude returned an empty answer.' };
    return text;
  } catch (e) {
    if (e.name === 'AbortError') throw { status: 502, message: 'Claude took too long. Try a shorter text.' };
    if (e.status) throw e;
    throw { status: 502, message: 'Could not reach Claude.' };
  } finally { clearTimeout(t); }
}

module.exports = { auth, fetchJson, isoDate, clean, safeEq, upstash, redis, claude, aiOn };
