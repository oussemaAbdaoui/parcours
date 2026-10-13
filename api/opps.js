const crypto = require('crypto');
const { auth, upstash, redis } = require('./_lib');

// The app keeps a copy of each dataset and sends back the version tag it got; when nothing changed since, a 304
// replaces the whole payload (offers are over a megabyte).
function notModified(req, res, parts) {
  const tag = 'W/"' + crypto.createHash('md5').update(parts.map(String).join('|')).digest('hex').slice(0, 20) + '"';
  res.setHeader('ETag', tag);
  if ((req.headers['if-none-match'] || '') === tag) { res.status(304).end(); return true; }
  return false;
}
const version = async (u, cmds) => (await Promise.all(cmds.map((c) => redis(u, c).catch(() => null)))).map((r) => (r && r.result) || '');

// Collected data from Neon Postgres (api/_offerspg.js, api/_polipg.js), written by the collectors (collector/pg.py);
// the run reports (parcours:*:meta) are in Redis.
const pgsets = require('./_offerspg');
module.exports = async (req, res) => {
  if (!(await auth(req, res))) return;
  const u = upstash();
  if (!u) return res.status(501).json({ error: 'Storage is not configured. Add Upstash Redis in Vercel.' });
  res.setHeader('Cache-Control', 'no-store');
  if (req.method === 'POST' && (req.query || {}).act === 'delete') {
    // Delete an offer for good (api/_offerspg.js deleteOffer): gone from the list, and never collected again.
    const id = String((req.body || {}).id || '');
    if (!id || id.length > 300) return res.status(400).json({ error: 'Which offer? The id is missing.' });
    try {
      const existed = await pgsets.deleteOffer(id);
      if (existed === null) return res.status(501).json({ error: 'The database is not configured.' });
      return res.status(200).json({ ok: true, existed });
    } catch (e) {
      return res.status(502).json({ error: 'The database is unavailable right now.' });
    }
  }
  if ((req.query || {}).set === 'masters') {
    try {
      if (notModified(req, res, ['m', ...await version(u, [['GET', 'parcours:masters:meta']]), await pgsets.datasetVersion(['masters'])])) return;
      return await masters(u, res);
    } catch (e) {
      return res.status(502).json({ error: 'Storage is unavailable right now.' });
    }
  }
  if ((req.query || {}).set === 'history') {
    // Hiring log (collector/history.py): per company, the date and kind of every offer seen. Sent compact:
    // [[key, name, [[day, kind], ...]], ...]
    try {
      return res.status(200).json({ companies: (await pgsets.history()) || [] });
    } catch (e) {
      return res.status(502).json({ error: 'Storage is unavailable right now.' });
    }
  }
  if ((req.query || {}).set === 'poli-live') return require('./_poli')(req, res); // live Poli (api/_poli.js)
  if ((req.query || {}).set === 'academia') {
    // Schools and professors (collector/academia.py), refreshed weekly.
    try {
      if (notModified(req, res, ['a', ...await version(u, [['GET', 'parcours:academia:meta']]), await pgsets.datasetVersion(['academia-schools', 'academia-people'])])) return;
      const [schools, people, meta] = await Promise.all([pgsets.dataset('academia-schools'), pgsets.dataset('academia-people'),
        redis(u, ['GET', 'parcours:academia:meta'])]);
      return res.status(200).json({ ...(meta && meta.result ? JSON.parse(meta.result) : { at: 0 }), schools: schools || [], people: people || [] });
    } catch (e) {
      return res.status(502).json({ error: 'Storage is unavailable right now.' });
    }
  }
  if ((req.query || {}).set === 'tunisia') {
    // Tunisian employers to write to directly (collector/tn_startups.py): the APII startup catalogue and the
    // partner companies directory.
    try {
      if (notModified(req, res, ['t', await pgsets.datasetVersion(['tn-startups', 'tn-companies'])])) return;
      const [startups, companies] = await Promise.all([pgsets.dataset('tn-startups'), pgsets.dataset('tn-companies')]);
      if (!startups) return res.status(501).json({ error: 'The database is not configured.' });
      return res.status(200).json({ startups, companies: companies || [] });
    } catch (e) {
      return res.status(502).json({ error: 'Storage is unavailable right now.' });
    }
  }
  if ((req.query || {}).set === 'poli-people') {
    try { return await require('./_polipg').people(req, res); } catch (e) { return res.status(502).json({ error: 'The database is unavailable right now.' }); }
  }
  if ((req.query || {}).set === 'poli') {
    // Poli (collector/poli.py): from Postgres (api/_polipg.js), with the run report from Redis.
    try {
      const meta = await redis(u, ['GET', 'parcours:poli:meta']).catch(() => null);
      const report = meta && meta.result ? JSON.parse(meta.result) : {};
      if (await require('./_polipg').directory(req, res, notModified, { stats: report.stats, sources: report.sources, refreshedAt: report.at })) return;
      return res.status(501).json({ error: 'The database is not configured.' });
    } catch (e) {
      return res.status(502).json({ error: 'Storage is unavailable right now.' });
    }
  }
  if ((req.query || {}).set === 'companies') {
    // Daily company refresh (collector/companies.py): ratings, open offers, last refresh, keyed by normalised name.
    try {
      const r = await redis(u, ['GET', 'parcours:companies:meta']);
      return res.status(200).json(r && r.result ? JSON.parse(r.result) : { at: 0, companies: {} });
    } catch (e) {
      return res.status(502).json({ error: 'Storage is unavailable right now.' });
    }
  }
  try {
    // Offers from Postgres (api/_offerspg.js), with the run reports from Redis.
    const pg = await pgsets.offers();
    if (!pg) return res.status(501).json({ error: 'The database is not configured.' });
    if (notModified(req, res, ['o', ...await version(u, [['GET', 'parcours:opps:meta']]), pg.version])) return;
    const [items, metaRaw] = await Promise.all([pg.load(), redis(u, ['GET', 'parcours:opps:meta'])]);
    const runsByOrigin = (metaRaw && metaRaw.result ? JSON.parse(metaRaw.result) : {}).runs || {};
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

// Master's programmes and scholarships saved by the collector (Postgres datasets set "masters"), with its run report.
// Served from this function (?set=masters) to stay within the Hobby plan's 12 functions.
async function masters(u, res) {
  const [items, metaRaw] = await Promise.all([pgsets.dataset('masters'), redis(u, ['GET', 'parcours:masters:meta'])]);
  const meta = metaRaw && metaRaw.result ? JSON.parse(metaRaw.result) : {};
  res.status(200).json({ updatedAt: meta.at || 0, sources: meta.sources || {}, fields: meta.fields || [], items: items || [] });
}
