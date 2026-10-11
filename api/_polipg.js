// Poli (UK visa sponsors) from Neon Postgres, where collector/poli.py writes it (tables poli_companies, poli_people,
// poli_jobs in db/schema.sql). Two reads:
// - directory(): every company, and the people most useful to contact (likely or possibly sponsored), for the
//   Sponsors page, company panels and the global search. Small enough to send whole.
// - people(): the search over all people (about 20,000, too many to send), 50 at a time.
const { db } = require('./_db');

// People worth contacting first: they went through (or face) the visa route themselves.
const USEFUL = ['Likely sponsored', 'May need future sponsorship'];
const slim = (d) => { const { avatar, ...rest } = d || {}; return rest; };

async function directory(req, res, notModified, report = {}) {
  const pool = db();
  if (!pool) return null; // no database: the caller falls back to Redis
  const v = await pool.query('select (select max(seen_at) from poli_companies) a, (select max(seen_at) from poli_people) b, (select count(*) from poli_people) n');
  const { a, b, n } = v.rows[0];
  if (notModified(req, res, ['pp', a, b, n, report.refreshedAt || ''])) return true;
  const [co, pe] = await Promise.all([
    pool.query('select data from poli_companies order by name'),
    pool.query('select data from poli_people where sponsorship = any($1) order by name', [USEFUL]),
  ]);
  res.status(200).json({ ...report, at: Number(a || b || 0), companies: co.rows.map((r) => r.data), people: pe.rows.map((r) => slim(r.data)), peopleTotal: Number(n) });
  return true;
}

// ?set=poli-people&q=words&filter=all|useful|notcontacted&company=<id>&offset=0
async function people(req, res) {
  const pool = db();
  if (!pool) return res.status(501).json({ error: 'The database is not configured.' });
  const q = req.query || {};
  const words = String(q.q || '').toLowerCase().split(/\s+/).filter(Boolean).slice(0, 6);
  const where = [], args = [];
  for (const w of words) { args.push('%' + w.replace(/[%_\\]/g, (m) => '\\' + m) + '%'); where.push(`search like $${args.length}`); }
  if (q.filter === 'useful') { args.push(USEFUL); where.push(`sponsorship = any($${args.length})`); }
  if (q.filter === 'notcontacted') where.push("coalesce((data->>'contacted')::boolean, false) = false");
  if (/^\d+$/.test(q.company || '')) { args.push(Number(q.company)); where.push(`company_id = $${args.length}`); }
  const w = where.length ? 'where ' + where.join(' and ') : '';
  const offset = Math.min(Math.max(parseInt(q.offset, 10) || 0, 0), 50000);
  const [rows, total] = await Promise.all([
    pool.query(`select data from poli_people ${w} order by (sponsorship = any($${args.length + 1})) desc, data->>'company', name limit 50 offset ${offset}`, [...args, USEFUL]),
    pool.query(`select count(*) n from poli_people ${w}`, args),
  ]);
  return res.status(200).json({ total: Number(total.rows[0].n), offset, people: rows.rows.map((r) => slim(r.data)) });
}

module.exports = { directory, people };
