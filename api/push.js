const webpush = require('web-push');
const { auth, upstash, redis } = require('./_lib');

// Phone and desktop notifications (standard Web Push, no third-party service).
// Subscriptions live in the Redis hash parcours:push:subs (endpoint -> {subscription, threshold, digest}).
// The collectors send "new strong match" and weekly digest notifications; this endpoint subscribes and tests.
const SUBS = 'parcours:push:subs';

function vapid() {
  const e = process.env;
  if (!e.VAPID_PUBLIC_KEY || !e.VAPID_PRIVATE_KEY) return null;
  webpush.setVapidDetails(e.VAPID_SUBJECT || 'https://parcours-swart.vercel.app', e.VAPID_PUBLIC_KEY, e.VAPID_PRIVATE_KEY);
  return e.VAPID_PUBLIC_KEY;
}

module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  res.setHeader('Cache-Control', 'no-store');
  const pub = vapid(), u = upstash();
  if (!pub || !u) return res.status(501).json({ error: 'Notifications are not configured on the server.' });
  try {
    if (req.method === 'GET') {
      const n = await redis(u, ['HLEN', SUBS]);
      return res.status(200).json({ publicKey: pub, devices: (n && n.result) || 0 });
    }
    const b = req.body || {};
    const sub = b.subscription;
    if (b.action === 'subscribe') {
      if (!sub || !/^https:\/\//.test(sub.endpoint || '') || !sub.keys) return res.status(400).json({ error: 'Invalid subscription.' });
      const rec = { subscription: sub, threshold: Math.min(95, Math.max(60, +b.threshold || 80)), digest: b.digest !== false, at: Date.now(), device: String(b.device || '').slice(0, 80) };
      await redis(u, ['HSET', SUBS, sub.endpoint, JSON.stringify(rec)]);
      return res.status(200).json({ ok: true });
    }
    if (b.action === 'unsubscribe') {
      if (sub && sub.endpoint) await redis(u, ['HDEL', SUBS, sub.endpoint]);
      return res.status(200).json({ ok: true });
    }
    if (b.action === 'test') {
      if (!sub || !sub.endpoint) return res.status(400).json({ error: 'Enable notifications on this device first.' });
      try {
        await webpush.sendNotification(sub, JSON.stringify({ title: 'Parcours', body: 'Notifications work on this device. You will hear about strong new matches.', url: '/#/opps' }));
      } catch (e) {
        if (e.statusCode === 404 || e.statusCode === 410) await redis(u, ['HDEL', SUBS, sub.endpoint]);
        return res.status(502).json({ error: 'The push service refused the test (' + (e.statusCode || 'error') + '). Enable notifications again.' });
      }
      return res.status(200).json({ ok: true });
    }
    res.status(400).json({ error: 'Unknown action.' });
  } catch (e) {
    res.status(502).json({ error: 'Storage is unavailable right now.' });
  }
};
