const { auth, upstash, redis } = require('./_lib');

// Opportunities saved by the scheduled collectors: GitHub Actions (parcours:opps) and the optional
// PC collector for home-IP-only sources (parcours:opps:home). Merged here into one list.
module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  const u = upstash();
  if (!u) return res.status(501).json({ error: 'Storage is not configured. Add Upstash Redis in Vercel.' });
  res.setHeader('Cache-Control', 'no-store');
  try {
    const out = await redis(u, ['MGET', 'parcours:opps', 'parcours:opps:home']);
    const [cloud, home] = ((out && out.result) || []).map((v) => (v ? JSON.parse(v) : { items: [], runs: [] }));
    const seen = new Set();
    const items = [...cloud.items, ...home.items].filter((x) => !seen.has(x.id) && seen.add(x.id))
      .sort((a, b) => (b.foundAt || 0) - (a.foundAt || 0));
    // One combined "last run": the latest report of each collector.
    const last = [cloud.runs[0], home.runs[0]].filter(Boolean);
    const runs = last.length ? [{
      at: Math.max(...last.map((r) => r.at)), new: last.reduce((n, r) => n + (r.new || 0), 0),
      sources: Object.assign({}, ...last.map((r) => r.sources))
    }] : [];
    res.status(200).json({ updatedAt: Math.max(cloud.updatedAt || 0, home.updatedAt || 0), runs, items });
  } catch (e) {
    res.status(502).json({ error: 'Storage is unavailable right now.' });
  }
};
