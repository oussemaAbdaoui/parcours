const { upstash, redis } = require('./_lib');
const { KEY, NONCE, missing, origin, tokenCall, gmail } = require('./_gmail');

// Google redirects here after consent. No password header is possible on a redirect,
// so the single-use nonce created by /api/gmail (which does require the password) is the check.
module.exports = async (req, res) => {
  const back = (q) => { res.setHeader('Cache-Control', 'no-store'); res.redirect(302, origin(req) + '/#/apps?' + q); };
  const fail = (m) => back('gmail=error&m=' + encodeURIComponent(m));
  const { code, state, error } = req.query || {};
  if (error) return fail(error === 'access_denied' ? 'You declined Gmail access.' : 'Google returned: ' + error);
  if (missing(req).length) return fail('Gmail is not configured on the server.');
  if (!code || !state || !/^[a-f0-9]{48}$/.test(state)) return fail('Invalid sign-in response.');
  const u = upstash();
  try {
    const out = await redis(u, ['GETDEL', NONCE + state]);
    const redirectUri = out && out.result;
    if (!redirectUri) return fail('This sign-in link expired. Try connecting again.');
    const tok = await tokenCall({ grant_type: 'authorization_code', code, redirect_uri: redirectUri });
    if (!tok.refresh_token) return fail('Google did not grant offline access. Try connecting again.');
    if (!String(tok.scope || '').includes('gmail.readonly')) return fail('Gmail read access was not granted.');
    const prof = await gmail(tok.access_token, 'profile');
    await redis(u, ['SET', KEY, JSON.stringify({ refresh_token: tok.refresh_token, email: prof.emailAddress || '', scope: tok.scope || '', connectedAt: Date.now() })]);
    back('gmail=ok');
  } catch (e) {
    fail(e.message || 'Could not connect Gmail.');
  }
};
