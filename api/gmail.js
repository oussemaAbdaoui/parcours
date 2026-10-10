const { auth, upstash, redis, isoDate } = require('./_lib');
const { KEY, SEND, missing, getConn, startUrl, accessToken, gmail, bodyText, sendRaw } = require('./_gmail');
const { classify } = require('./_classify');

// Words that show up in application, recruiting and admissions emails (EN, FR, DE).
const WORDS = ['application', 'applied', 'candidature', 'candidacy', 'interview', 'entretien', 'offer', 'offre', 'position', 'poste',
  'unfortunately', 'malheureusement', 'regret', 'recruiter', 'recrutement', 'recruiting', 'hiring', 'internship', 'PhD', 'thèse', 'doctorat',
  'doctoral', 'master', 'admission', 'admitted', '"job alert"', 'bewerbung', 'vorstellungsgespräch', 'stellenangebot', 'absage', 'zusage',
  'opportunity', 'opportunité'];
// Sorting is local and free, so a scan can read more emails than the old AI version.
const PER_SCAN = 80;

async function scan(req, u) {
  const body = req.body || {};
  const days = [7, 30, 90].includes(+body.days) ? +body.days : 30;
  const seen = new Set((Array.isArray(body.seen) ? body.seen : []).slice(-3000).map(String));
  const token = await accessToken(u);

  const q = `newer_than:${days}d -in:sent -in:drafts -in:chats {${WORDS.join(' ')}}`;
  const list = await gmail(token, 'messages?maxResults=200&q=' + encodeURIComponent(q));
  const all = (list.messages || []).map((m) => m.id);
  const fresh = all.filter((id) => !seen.has(id));
  const ids = fresh.slice(0, PER_SCAN);
  const more = fresh.length > PER_SCAN || !!list.nextPageToken;
  if (!ids.length) return { emails: [], scanned: 0, skipped: all.length - fresh.length, more: false };

  const emails = [];
  for (let i = 0; i < ids.length; i += 10) {
    const chunk = await Promise.all(ids.slice(i, i + 10).map((id) => gmail(token, 'messages/' + id + '?format=full').catch(() => null)));
    chunk.forEach((m) => {
      if (!m) return;
      // Headers are plain text (not HTML), so only collapse whitespace: clean() would drop "<name@host>".
      const h = (n) => String((((m.payload && m.payload.headers) || []).find((x) => x.name.toLowerCase() === n) || {}).value || '').replace(/s+/g, ' ').trim();
      const e = { id: m.id, from: h('from').slice(0, 160), subject: h('subject').slice(0, 200), date: isoDate(Number(m.internalDate)) };
      emails.push(Object.assign(e, classify({ from: e.from, subject: e.subject, text: (bodyText(m.payload) || m.snippet || '').slice(0, 6000) })));
    });
  }
  return { emails, scanned: emails.length, skipped: all.length - fresh.length, more };
}

/* Sends one application email you approved in the apply queue: your letter as the body, your CV and recommendation
   letters attached (from your documents, api/state.js ?doc=). One recipient, at most 5 attachments, 15 MB in all. */
const EMAIL = /^[^\s@<>()",;]+@[^\s@<>()",;]+\.[a-z]{2,}$/i;
const hdr = (s) => (/^[\x20-\x7e]*$/.test(s) ? s : '=?UTF-8?B?' + Buffer.from(s, 'utf8').toString('base64') + '?=');
const wrap = (b64) => b64.replace(/.{76}/g, '$&\r\n');
async function send(req, u) {
  const { to, toName, subject, text, attachments } = req.body || {};
  if (!EMAIL.test(String(to || ''))) throw { status: 400, message: 'The recipient email is not valid.' };
  if (!String(subject || '').trim() || String(text || '').trim().length < 50) throw { status: 400, message: 'The email needs a subject and a letter.' };
  const conn = await getConn(u);
  if (!conn) throw { status: 409, code: 'not_connected', message: 'Connect Gmail first (Applications, Scan Gmail).' };
  if (!String(conn.scope || '').includes(SEND)) throw { status: 409, code: 'need_send', message: 'Reconnect Gmail and allow sending emails.' };
  const ids = (Array.isArray(attachments) ? attachments : []).map(String).filter((x) => /^[\w-]{1,64}$/.test(x)).slice(0, 5);
  const files = [];
  if (ids.length) {
    const pool = require('./_db').db();
    if (!pool) throw { status: 501, message: 'Attachments need the Neon database.' };
    const r = await pool.query('select id, name, type, data from docs where id = any($1)', [ids]);
    files.push(...r.rows);
    if (files.reduce((n, f) => n + f.data.length * 3 / 4, 0) > 15 * 1024 * 1024) throw { status: 413, message: 'The attachments are over 15 MB.' };
  }
  const boundary = 'parcours-' + require('crypto').randomBytes(12).toString('hex');
  const from = conn.email ? conn.email : 'me';
  const lines = [
    `From: ${from}`, `To: ${toName ? hdr(String(toName).replace(/[<>"]/g, '')) + ' ' : ''}<${to}>`, `Subject: ${hdr(String(subject).slice(0, 200))}`,
    'MIME-Version: 1.0', `Content-Type: multipart/mixed; boundary="${boundary}"`, '',
    `--${boundary}`, 'Content-Type: text/plain; charset="UTF-8"', 'Content-Transfer-Encoding: base64', '',
    wrap(Buffer.from(String(text), 'utf8').toString('base64')),
  ];
  for (const f of files) {
    lines.push(`--${boundary}`, `Content-Type: ${f.type}; name="${hdr(f.name)}"`, `Content-Disposition: attachment; filename="${hdr(f.name)}"`,
      'Content-Transfer-Encoding: base64', '', wrap(f.data));
  }
  lines.push(`--${boundary}--`, '');
  const raw = Buffer.from(lines.join('\r\n'), 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const out = await sendRaw(await accessToken(u), raw);
  return { ok: true, id: out.id, threadId: out.threadId, attached: files.map((f) => f.name) };
}

module.exports = async (req, res) => {
  if (!(await auth(req, res))) return;
  res.setHeader('Cache-Control', 'no-store');
  const miss = missing(req);
  if (req.method === 'GET' && miss.length) return res.status(200).json({ configured: false, missing: miss });
  if (miss.length) return res.status(503).json({ error: 'Gmail is not configured. Missing: ' + miss.join(', ') + '.' });
  const u = upstash();
  try {
    if (req.method === 'GET') {
      const conn = await getConn(u);
      return res.status(200).json({ configured: true, connected: !!conn, email: conn ? conn.email : '', canSend: !!conn && String(conn.scope || '').includes(SEND) });
    }
    if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed.' });
    const action = (req.body || {}).action;
    if (action === 'start') return res.status(200).json({ url: await startUrl(req, u) });
    if (action === 'scan') return res.status(200).json(await scan(req, u));
    if (action === 'send') return res.status(200).json(await send(req, u));
    if (action === 'disconnect') {
      const conn = await getConn(u);
      if (conn) {
        await fetch('https://oauth2.googleapis.com/revoke?token=' + encodeURIComponent(conn.refresh_token), { method: 'POST' }).catch(() => {});
        await redis(u, ['DEL', KEY]);
      }
      return res.status(200).json({ ok: true });
    }
    res.status(400).json({ error: 'Unknown action.' });
  } catch (e) {
    res.status(e.status || 502).json({ error: e.message || 'Gmail request failed.', code: e.code });
  }
};
