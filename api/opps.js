const { auth, upstash, redis } = require('./_lib');

// Offers saved by the collectors (GitHub Actions and the optional PC collector) in the hash
// parcours:opps:items (id -> offer JSON), plus run reports in parcours:opps:meta.
// Falls back to the older one-blob keys until the collector has migrated them.
module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  const u = upstash();
  if (!u) return res.status(501).json({ error: 'Storage is not configured. Add Upstash Redis in Vercel.' });
  res.setHeader('Cache-Control', 'no-store');
  if ((req.query || {}).set === 'masters') return masters(u, res);
  try {
    const [flat, metaRaw] = await Promise.all([redis(u, ['HGETALL', 'parcours:opps:items']), redis(u, ['GET', 'parcours:opps:meta'])]);
    const arr = (flat && flat.result) || [];
    let items = [];
    for (let i = 1; i < arr.length; i += 2) { try { items.push(JSON.parse(arr[i])); } catch (e) { /* skip a bad record */ } }
    let runsByOrigin = {};
    if (items.length) {
      const meta = metaRaw && metaRaw.result ? JSON.parse(metaRaw.result) : {};
      runsByOrigin = meta.runs || {};
    } else {
      const old = await redis(u, ['MGET', 'parcours:opps', 'parcours:opps:home']);
      const [cloud, home] = ((old && old.result) || []).map((v) => (v ? JSON.parse(v) : { items: [], runs: [] }));
      items = [...cloud.items, ...home.items];
      runsByOrigin = { cloud: cloud.runs, home: home.runs };
    }
    items.sort((a, b) => (b.foundAt || 0) - (a.foundAt || 0));
    // One combined "last run": the latest report of each collector.
    const last = Object.values(runsByOrigin).map((r) => (r || [])[0]).filter(Boolean);
    const runs = last.length ? [{
      at: Math.max(...last.map((r) => r.at)), new: last.reduce((n, r) => n + (r.new || 0), 0),
      sources: Object.assign({}, ...last.map((r) => r.sources))
    }] : [];
    res.status(200).json({ updatedAt: runs[0] ? runs[0].at : 0, runs, items });
  } catch (e) {
    res.status(502).json({ error: 'Storage is unavailable right now.' });
  }
};

// Master's programmes and scholarships (Germany, France, Italy, Erasmus Mundus) saved by the collector in
// parcours:masters:items. Served from this function (?set=masters) to stay within the Hobby plan's 12 functions.
async function masters(u, res) {
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
}
