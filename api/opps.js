const { auth, upstash, redis } = require('./_lib');

// Opportunities saved by the scheduled collector (collector/collect.py on GitHub Actions).
module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  const u = upstash();
  if (!u) return res.status(501).json({ error: 'Storage is not configured. Add Upstash Redis in Vercel.' });
  res.setHeader('Cache-Control', 'no-store');
  try {
    const out = await redis(u, ['GET', 'parcours:opps']);
    const data = out && out.result ? JSON.parse(out.result) : null;
    res.status(200).json(data || { updatedAt: 0, runs: [], items: [] });
  } catch (e) {
    res.status(502).json({ error: 'Storage is unavailable right now.' });
  }
};
