const crypto = require('crypto');
const { auth, upstash, redis } = require('./_lib');

// PhD supervisor finder: who publishes on a topic lately, and where.
// OpenAlex (free, worldwide, author institutions and countries); HAL (French open archive) as fallback for France.
// Researchers are ranked by recent papers on the topic; last-author papers count double (usually the supervisor).
// Results are cached for a day in Redis. Optional OPENALEX_API_KEY avoids OpenAlex's anonymous rate limit.
const COUNTRY = { fr: 'FR', de: 'DE', ca: 'CA', ch: 'CH', tn: 'TN' };
const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));

async function getJson(url, retry = true) {
  const r = await fetch(url, { headers: { 'User-Agent': 'parcours-personal-app' } });
  const j = await r.json().catch(() => ({}));
  if (r.status === 429 && retry && (j.retryAfter || 0) <= 40) { await sleep(((j.retryAfter || 20) + 1) * 1000); return getJson(url, false); }
  if (!r.ok) { const e = new Error(r.status === 429 ? 'OpenAlex is rate-limiting right now. Try again in a minute.' : 'Source answered HTTP ' + r.status); e.status = r.status; throw e; }
  return j;
}

async function openAlex(q, c, years) {
  const since = new Date(Date.now() - years * 365 * 864e5).toISOString().slice(0, 10);
  // Computer science only (OpenAlex field 17), most relevant first.
  const f = [`from_publication_date:${since}`, 'type:article|preprint|proceedings-article', 'primary_topic.field.id:fields/17'];
  if (COUNTRY[c]) f.push(`institutions.country_code:${COUNTRY[c]}`);
  const p = new URLSearchParams({ search: q, filter: f.join(','), 'per-page': '200', select: 'id,title,publication_date,doi,authorships' });
  if (process.env.OPENALEX_API_KEY) p.set('api_key', process.env.OPENALEX_API_KEY);
  const j = await getJson('https://api.openalex.org/works?' + p);
  const people = new Map(), labs = new Map();
  for (const w of j.results || []) {
    const n = w.authorships.length;
    w.authorships.forEach((a, i) => {
      const inst = (a.institutions || [])[0];
      if (!a.author || !a.author.id || !inst || (COUNTRY[c] && inst.country_code !== COUNTRY[c])) return;
      const last = i === n - 1 && n > 1;
      const key = a.author.id;
      const pe = people.get(key) || { name: a.author.display_name, inst: inst.display_name, country: inst.country_code, papers: 0, lastAuthor: 0, weight: 0,
        latest: null, openalex: key.replace('https://openalex.org/', 'https://openalex.org/authors/') };
      pe.papers++; pe.weight += last ? 2 : 1; if (last) pe.lastAuthor++;
      if (!pe.latest) pe.latest = { title: w.title, year: (w.publication_date || '').slice(0, 4), url: w.doi || w.id };
      people.set(key, pe);
      const lb = labs.get(inst.display_name) || { name: inst.display_name, country: inst.country_code, papers: new Set(), people: new Set() };
      lb.papers.add(w.id); lb.people.add(key); labs.set(inst.display_name, lb);
    });
  }
  return {
    source: 'OpenAlex', total: j.meta ? j.meta.count : 0, scanned: (j.results || []).length,
    people: [...people.values()].sort((a, b) => b.weight - a.weight || b.papers - a.papers).slice(0, 40),
    labs: [...labs.values()].map((l) => ({ name: l.name, country: l.country, papers: l.papers.size, people: l.people.size })).sort((a, b) => b.papers - a.papers).slice(0, 15),
  };
}

async function hal(q, years) {
  const y = new Date().getFullYear();
  const p = new URLSearchParams({ q, fq: `producedDateY_i:[${y - years} TO ${y}]`, rows: '200', wt: 'json', sort: 'producedDate_tdate desc',
    fl: 'title_s,authFullName_s,labStructName_s,labStructAcronym_s,producedDate_s,uri_s' });
  const j = await getJson('https://api.archives-ouvertes.fr/search/?' + p, false);
  const people = new Map(), labs = new Map();
  for (const d of (j.response && j.response.docs) || []) {
    const authors = d.authFullName_s || [], lab = (d.labStructAcronym_s || d.labStructName_s || [])[0] || '';
    authors.forEach((name, i) => {
      const last = i === authors.length - 1 && authors.length > 1;
      const pe = people.get(name) || { name, inst: lab, country: 'FR', papers: 0, lastAuthor: 0, weight: 0, latest: null, openalex: '' };
      pe.papers++; pe.weight += last ? 2 : 1; if (last) pe.lastAuthor++;
      if (!pe.latest) pe.latest = { title: (d.title_s || [''])[0], year: (d.producedDate_s || '').slice(0, 4), url: d.uri_s };
      people.set(name, pe);
    });
    (d.labStructName_s || []).slice(0, 3).forEach((l) => { const lb = labs.get(l) || { name: l, country: 'FR', papers: 0, people: 0 }; lb.papers++; lb.people += authors.length; labs.set(l, lb); });
  }
  return {
    source: 'HAL', total: (j.response && j.response.numFound) || 0, scanned: ((j.response && j.response.docs) || []).length,
    people: [...people.values()].sort((a, b) => b.weight - a.weight).slice(0, 40), labs: [...labs.values()].sort((a, b) => b.papers - a.papers).slice(0, 15),
  };
}

module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  const q = String((req.query || {}).q || '').trim().slice(0, 120), c = String((req.query || {}).c || 'any');
  const years = Math.min(5, Math.max(1, +((req.query || {}).years) || 2));
  if (q.length < 2) return res.status(400).json({ error: 'Add a research topic.' });
  res.setHeader('Cache-Control', 'no-store');
  const u = upstash(), key = 'parcours:labs:' + crypto.createHash('sha1').update(`${q.toLowerCase()}|${c}|${years}`).digest('hex').slice(0, 16);
  try {
    if (u) { const hit = await redis(u, ['GET', key]); if (hit && hit.result) return res.status(200).json(Object.assign(JSON.parse(hit.result), { cached: true })); }
    let out;
    try { out = await openAlex(q, c, years); }
    catch (e) { if (c === 'fr' || c === 'any') out = Object.assign(await hal(q, years), { note: e.message }); else throw e; }
    if (u && out.people.length) await redis(u, ['SET', key, JSON.stringify(out), 'EX', 86400]);
    res.status(200).json(out);
  } catch (e) {
    res.status(502).json({ error: e.message || 'Could not reach the paper databases.' });
  }
};
