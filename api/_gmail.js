const crypto = require('crypto');
const { upstash, redis } = require('./_lib');

// Gmail connection: read-only access, refresh token kept in Upstash only (never sent to the browser).
const KEY = 'parcours:gmail';
const NONCE = 'parcours:gmail:nonce:';
const SCOPE = 'https://www.googleapis.com/auth/gmail.readonly';

function missing(req) {
  const e = process.env, m = [];
  if (!e.GOOGLE_CLIENT_ID || !e.GOOGLE_CLIENT_SECRET) m.push('GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET');
  if (!upstash()) m.push('Upstash Redis');
  return m;
}

const origin = (req) => 'https://' + (req.headers['x-forwarded-host'] || req.headers.host);

async function getConn(u) {
  const out = await redis(u, ['GET', KEY]);
  return out && out.result ? JSON.parse(out.result) : null;
}

// Starts the Google consent flow. The nonce is single-use and remembers the exact redirect URI.
async function startUrl(req, u) {
  const nonce = crypto.randomBytes(24).toString('hex');
  const redirectUri = origin(req) + '/api/gmail-callback';
  await redis(u, ['SET', NONCE + nonce, redirectUri, 'EX', 600]);
  const p = new URLSearchParams({
    client_id: process.env.GOOGLE_CLIENT_ID, redirect_uri: redirectUri, response_type: 'code',
    scope: SCOPE, access_type: 'offline', prompt: 'consent', include_granted_scopes: 'true', state: nonce
  });
  return 'https://accounts.google.com/o/oauth2/v2/auth?' + p.toString();
}

async function tokenCall(params) {
  const r = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams(Object.assign({ client_id: process.env.GOOGLE_CLIENT_ID, client_secret: process.env.GOOGLE_CLIENT_SECRET }, params)).toString()
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw { status: r.status, google: j.error || 'token_error', message: j.error_description || j.error || 'Google sign-in failed.' };
  return j;
}

async function accessToken(u) {
  const conn = await getConn(u);
  if (!conn) throw { status: 409, code: 'not_connected', message: 'Gmail is not connected.' };
  try {
    return (await tokenCall({ grant_type: 'refresh_token', refresh_token: conn.refresh_token })).access_token;
  } catch (e) {
    if (e.google === 'invalid_grant') {
      await redis(u, ['DEL', KEY]);
      throw { status: 409, code: 'reconnect', message: 'Gmail access expired or was revoked. Connect again.' };
    }
    throw { status: 502, message: 'Could not refresh Gmail access.' };
  }
}

async function gmail(token, path) {
  const r = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/' + path, { headers: { Authorization: 'Bearer ' + token } });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw { status: 502, message: 'Gmail answered HTTP ' + r.status + ((j.error && j.error.message) ? ': ' + j.error.message : '') };
  return j;
}

const b64 = (s) => Buffer.from(String(s || '').replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8');

function htmlToText(h) {
  return h.replace(/<(style|script)[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<a\s[^>]*href="(https?:[^"]{1,200})"[^>]*>([\s\S]*?)<\/a>/gi, '$2 ($1)')
    .replace(/<br\s*\/?>|<\/p>|<\/div>|<\/tr>/gi, '\n').replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#39;|&apos;/g, "'").replace(/&quot;/g, '"');
}

function bodyText(payload) {
  let plain = '', html = '';
  (function walk(p) {
    if (!p) return;
    if (p.mimeType === 'text/plain' && p.body && p.body.data && !plain) plain = b64(p.body.data);
    else if (p.mimeType === 'text/html' && p.body && p.body.data && !html) html = b64(p.body.data);
    (p.parts || []).forEach(walk);
  })(payload);
  return (plain || htmlToText(html)).replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim();
}

module.exports = { KEY, NONCE, missing, origin, getConn, startUrl, tokenCall, accessToken, gmail, bodyText };
