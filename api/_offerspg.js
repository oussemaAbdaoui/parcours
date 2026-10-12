// Collected offers from Neon Postgres (table offers, written by every collector run: collector/pg.py). Each offer
// is sent as the collector stored it, plus companyId (companies.id), sponsorId (the company's Poli sponsor
// record) and, for UK offers, ukSponsor (the employer is on the UK register of licensed sponsors, which score.js uses).
const { db } = require('./_db');

// Returns { version, items } or null when no database is configured (the caller then reads Redis).
async function offers() {
  const pool = db();
  if (!pool) return null;
  const v = await pool.query('select coalesce(max(updated_at), 0) m, count(*) n from offers');
  const version = v.rows[0].m + ':' + v.rows[0].n;
  return {
    version,
    load: async () => (await pool.query(
      'select o.data, o.company_id, c.poli_id, c.uk_sponsor, o.country from offers o left join companies c on c.id = o.company_id order by o.found_at desc nulls last'
    )).rows.map((r) => ({ ...r.data, ...(r.company_id ? { companyId: r.company_id } : {}), ...(r.poli_id ? { sponsorId: r.poli_id } : {}),
      ...(r.country === 'uk' && r.uk_sponsor != null ? { ukSponsor: r.uk_sponsor } : {}) })),
  };
}

module.exports = { offers };

// Hiring log for company pages, compact like the Redis version: [[norm, name, [[day, kind, src], ...]], ...].
// Keys are the current normalised names, so they match coNorm in the app.
async function history() {
  const pool = db();
  if (!pool) return null;
  const r = await pool.query(`select c.norm, c.name, json_agg(json_build_array(to_char(s.day, 'YYYY-MM-DD'), s.kind, s.src) order by s.day) seen
    from company_seen s join companies c on c.id = s.company_id group by c.id`);
  return r.rows.map((x) => [x.norm, x.name, x.seen]);
}

module.exports.history = history;

// Master's programmes and academia (collector/masters.py, collector/academia.py): table datasets, one set each.
async function dataset(name) {
  const pool = db();
  if (!pool) return null;
  return (await pool.query('select data from datasets where set = $1', [name])).rows.map((r) => r.data);
}

async function datasetVersion(names) {
  const pool = db();
  if (!pool) return '';
  const v = (await pool.query('select coalesce(max(updated_at), 0) m, count(*) n from datasets where set = any($1)', [names])).rows[0];
  return v.m + ':' + v.n;
}

// Interview stories for one company and role (collector/insights.py), or null.
async function insight(key) {
  const pool = db();
  if (!pool) return null;
  const r = await pool.query('select data from insights where key = $1', [key]);
  return r.rows[0] ? r.rows[0].data : null;
}

Object.assign(module.exports, { dataset, datasetVersion, insight });
