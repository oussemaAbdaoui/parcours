const { db } = require('./_db');
const { handle } = require('./_users');

// Public user accounts and data for app.html (see api/_users.js). The admin app does not use this endpoint.
module.exports = async (req, res) => {
  const pool = db();
  if (!pool) return res.status(501).json({ error: 'Accounts are not configured.' });
  try {
    await handle(pool, req, res);
  } catch (e) {
    res.status(502).json({ error: 'Accounts are unavailable right now. Try again in a moment.' });
  }
};
