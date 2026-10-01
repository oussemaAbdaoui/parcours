const { auth, upstash, redis } = require('./_lib');

// Master's programmes and scholarships (Germany, France, Italy, Erasmus Mundus) saved by the collector
// in the hash parcours:masters:items, plus the last refresh report in parcours:masters:meta.
module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  const u = upstash();
  if (!u) return res.status(501).json({ error: 'Storage is not configured. Add Upstash Redis in Vercel.' });
  res.setHeader('Cache-Control', 'no-store');
  try {
    const [flat, metaRaw] = await Promise.all([redis(u, ['HGETALL', 'parcours:masters:items']), redis(u, ['GET', 'parcours:masters:meta'])]);
    const arr = (flat && flat.result) || [];
    const items = [];
    for (let i = 1; i < arr.length; i += 2) { try { items.push(JSON.parse(arr[i])); } catch (e) { /* skip a bad record */ } }
    const meta = metaRaw && metaRaw.result ? JSON.parse(metaRaw.result) : {};
    res.status(200).json({ updatedAt: meta.at || 0, sources: meta.sources || {}, fields: meta.fields || [], items });
  } catch (e) {
    res.status(502).json({ error: 'Storage is unavailable right now.' });
  }
};
