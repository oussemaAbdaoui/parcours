const { auth, claude } = require('./_lib');

// Thin proxy to the Anthropic Messages API so your key never reaches the browser.
module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed.' });
  const { prompt, tier } = req.body || {};
  if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > 60000) return res.status(400).json({ error: 'Invalid prompt.' });
  try {
    res.status(200).json({ text: await claude(prompt, { req, tier }) });
  } catch (e) {
    res.status(e.status || 502).json({ error: e.message || 'Claude request failed.' });
  }
};
