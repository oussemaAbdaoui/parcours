const { auth, upstash, redis, isoDate } = require('./_lib');
const { KEY, missing, getConn, startUrl, accessToken, gmail, bodyText } = require('./_gmail');
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
      return res.status(200).json({ configured: true, connected: !!conn, email: conn ? conn.email : '' });
    }
    if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed.' });
    const action = (req.body || {}).action;
    if (action === 'start') return res.status(200).json({ url: await startUrl(req, u) });
    if (action === 'scan') return res.status(200).json(await scan(req, u));
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
