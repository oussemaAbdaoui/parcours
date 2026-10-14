const { db } = require('./_db');
const { handle } = require('./_users');

// Accounts (sign-up, sign-in, the admin pass) and each public user's data, for the login page and public app (index.html).
module.exports = async (req, res) => {
  const pool = db();
  if (!pool) return res.status(501).json({ error: 'Accounts are not configured.' });
  try {
    await handle(pool, req, res);
  } catch (e) {
    res.status(502).json({ error: 'Accounts are unavailable right now. Try again in a moment.' });
  }
};
