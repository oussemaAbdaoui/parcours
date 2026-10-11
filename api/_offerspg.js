// Collected offers from Neon Postgres (table offers, written by every collector run: collector/pg.py). Each offer
// is sent as the collector stored it, plus companyId (companies.id) and sponsorId (the company's Poli sponsor
// record), so the app can link an offer to its company without matching names.
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
      'select o.data, o.company_id, c.poli_id from offers o left join companies c on c.id = o.company_id order by o.found_at desc nulls last'
    )).rows.map((r) => ({ ...r.data, ...(r.company_id ? { companyId: r.company_id } : {}), ...(r.poli_id ? { sponsorId: r.poli_id } : {}) })),
  };
}

module.exports = { offers };
