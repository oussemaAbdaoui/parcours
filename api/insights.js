const { auth, upstash, redis } = require('./_lib');

// Interview stories for a company and role (Glassdoor interview reviews, Reddit threads).
// Those sites block datacenter IPs, so the PC collector fetches them (collector/insights.py, every 30 minutes);
// this endpoint returns what is stored and queues new requests.
const QUEUE = 'parcours:insights:queue', STORE = 'parcours:insights';
const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
const key = (c, r) => norm(c).replace(/ /g, '-') + '|' + norm(r).replace(/ /g, '-');

module.exports = async (req, res) => {
  if (!(await auth(req, res))) return;
  const u = upstash();
  if (!u) return res.status(501).json({ error: 'Storage is not configured.' });
  res.setHeader('Cache-Control', 'no-store');
  const src = req.method === 'GET' ? (req.query || {}) : (req.body || {});
  const company = String(src.company || '').trim().slice(0, 100), role = String(src.role || '').trim().slice(0, 100);
  if (!company) return res.status(400).json({ error: 'Name a company.' });
  const k = key(company, role);
  try {
    if (req.method === 'GET') {
      const [hit, pending] = await Promise.all([redis(u, ['HGET', STORE, k]), redis(u, ['SISMEMBER', QUEUE + ':pending', k])]);
      return res.status(200).json({ data: hit && hit.result ? JSON.parse(hit.result) : null, pending: !!(pending && pending.result) });
    }
    if (req.method === 'POST') {
      const added = await redis(u, ['SADD', QUEUE + ':pending', k]);
      if (added && added.result) await redis(u, ['LPUSH', QUEUE, JSON.stringify({ company, role })]);
      return res.status(200).json({ ok: true, pending: true });
    }
    res.status(405).json({ error: 'Method not allowed.' });
  } catch (e) {
    res.status(502).json({ error: 'Storage is unavailable right now.' });
  }
};
