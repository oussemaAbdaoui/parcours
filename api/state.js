const { auth, upstash, redis } = require('./_lib');

const KEY = 'parcours:state';

// Optional cloud copy of your data (Upstash Redis). Without it the app keeps data on the device only.
module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  const u = upstash();
  if (!u) return res.status(501).json({ error: 'Sync is not configured.' });
  res.setHeader('Cache-Control', 'no-store');
  try {
    if (req.method === 'GET') {
      const out = await redis(u, ['GET', KEY]);
      return res.status(200).json({ state: out && out.result ? JSON.parse(out.result) : null });
    }
    if (req.method === 'PUT') {
      const state = req.body && req.body.state;
      if (!state || !Array.isArray(state.apps)) return res.status(400).json({ error: 'Invalid data.' });
      const s = JSON.stringify(state);
      if (s.length > 900000) return res.status(413).json({ error: 'Data is too large to sync.' });
      await redis(u, ['SET', KEY, s]);
      return res.status(200).json({ ok: true });
    }
    res.status(405).json({ error: 'Method not allowed.' });
  } catch (e) {
    res.status(502).json({ error: 'Sync storage is unavailable right now.' });
  }
};
