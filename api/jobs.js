const { auth, fetchJson, isoDate, clean } = require('./_lib');

const e = process.env;
const cache = new Map();
async function cached(key, ttlMs, fn) {
  const hit = cache.get(key);
  if (hit && Date.now() - hit.t < ttlMs) return hit.v;
  const v = await fn();
  cache.set(key, { t: Date.now(), v });
  if (cache.size > 60) cache.delete(cache.keys().next().value);
  return v;
}
const isRemote = (q) => q.c === 'gl' || /remote|télétravail|teletravail|homeoffice|home office/i.test(q.loc || '');
const tokens = (s) => String(s).toLowerCase().split(/[^\p{L}\p{N}+#]+/u).filter((t) => t.length > 1);
function matcher(q) {
  const t = tokens(q.q);
  return (text) => {
    const h = String(text).toLowerCase();
    return t.length === 0 || t.every((w) => h.includes(w)) || t.some((w) => w.length > 3 && h.includes(w));
  };
}

/* ---------- Adzuna (official API, free key) ---------- */
async function adzuna(q) {
  const cc = { fr: 'fr', de: 'de', ca: 'ca', ch: 'ch' }[q.c];
  if (!cc) throw new Error('Not available for this country');
  const p = new URLSearchParams({
    app_id: e.ADZUNA_APP_ID, app_key: e.ADZUNA_APP_KEY, results_per_page: '20',
    'content-type': 'application/json', what: q.type === 'internship' ? q.q + ' internship' : q.q
  });
  if (q.loc && !isRemote(q)) p.set('where', q.loc);
  if (q.type === 'fulltime') p.set('full_time', '1');
  if (q.type === 'parttime') p.set('part_time', '1');
  if (q.type === 'contract') p.set('contract', '1');
  const { json } = await fetchJson(`https://api.adzuna.com/v1/api/jobs/${cc}/search/1?${p}`);
  return ((json && json.results) || []).map((r) => ({
    id: 'adzuna:' + r.id, title: clean(r.title), company: clean((r.company || {}).display_name),
    location: clean((r.location || {}).display_name), posted: isoDate(r.created),
    type: [r.contract_time, r.contract_type].filter(Boolean).join(' ').replace(/_/g, '-'),
    url: r.redirect_url, source: 'adzuna'
  }));
}

/* ---------- France Travail (official API, free key) ---------- */
let ftTok = { v: '', exp: 0 };
async function ftToken() {
  if (ftTok.v && Date.now() < ftTok.exp - 30000) return ftTok.v;
  const body = new URLSearchParams({
    grant_type: 'client_credentials', client_id: e.FRANCE_TRAVAIL_ID,
    client_secret: e.FRANCE_TRAVAIL_SECRET, scope: 'api_offresdemploiv2 o2dsoffre'
  });
  const { json } = await fetchJson('https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire', {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: body.toString()
  });
  if (!json || !json.access_token) throw new Error('Token request failed');
  ftTok = { v: json.access_token, exp: Date.now() + (json.expires_in || 1200) * 1000 };
  return ftTok.v;
}
const DEPT = { paris: '75', lyon: '69', toulouse: '31', marseille: '13', lille: '59', nantes: '44', bordeaux: '33', nice: '06', grenoble: '38', strasbourg: '67', rennes: '35', montpellier: '34', 'sophia antipolis': '06', antibes: '06', 'saint-denis': '93', nanterre: '92' };
async function francetravail(q) {
  if (q.c !== 'fr') throw new Error('Only covers France');
  const token = await ftToken();
  const p = new URLSearchParams({ motsCles: q.type === 'internship' ? q.q + ' stage' : q.q, range: '0-19' });
  const loc = (q.loc || '').trim().toLowerCase();
  if (/^\d{2}$/.test(loc)) p.set('departement', loc);
  else if (DEPT[loc]) p.set('departement', DEPT[loc]);
  if (q.type === 'contract') p.set('typeContrat', 'CDD');
  const r = await fetchJson(`https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search?${p}`, {
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/json' }
  });
  const list = (r.json && r.json.resultats) || []; // 204 (no results) returns an empty body
  return list.map((o) => ({
    id: 'ft:' + o.id, title: clean(o.intitule), company: clean((o.entreprise || {}).nom),
    location: clean((o.lieuTravail || {}).libelle), posted: isoDate(o.dateCreation),
    type: clean(o.typeContratLibelle || o.typeContrat),
    url: 'https://candidat.francetravail.fr/offres/recherche/detail/' + o.id, source: 'francetravail'
  }));
}

/* ---------- Arbeitsagentur (public but unofficial API, no key) ---------- */
async function arbeitsagentur(q) {
  if (q.c !== 'de') throw new Error('Only covers Germany');
  const p = new URLSearchParams({ was: q.q, size: '20', page: '1', angebotsart: '1' });
  if (q.loc && !isRemote(q)) p.set('wo', q.loc);
  const headers = { 'X-API-Key': 'jobboerse-jobsuche', Accept: 'application/json' };
  let r;
  try { r = await fetchJson('https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?' + p, { headers }); }
  catch (err) { r = await fetchJson('https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs?' + p, { headers }); }
  return ((r.json && r.json.stellenangebote) || []).map((s) => ({
    id: 'ba:' + s.refnr, title: clean(s.titel || s.beruf), company: clean(s.arbeitgeber),
    location: [s.arbeitsort && s.arbeitsort.ort, s.arbeitsort && s.arbeitsort.region].filter(Boolean).join(', '),
    posted: isoDate(s.aktuelleVeroeffentlichungsdatum || s.modifikationsTimestamp), type: '',
    url: 'https://www.arbeitsagentur.de/jobsuche/jobdetail/' + s.refnr, source: 'arbeitsagentur'
  }));
}

/* ---------- Arbeitnow (public, no key, Germany/Europe, visa filter) ---------- */
async function arbeitnow(q) {
  if (!['de', 'ch', 'gl'].includes(q.c)) throw new Error('Only covers Germany, Switzerland and remote');
  const visa = q.visa ? '&visa_sponsorship=true' : '';
  const pages = await cached('an:' + visa, 30 * 60 * 1000, async () => {
    const out = [];
    for (const n of [1, 2]) {
      try { const r = await fetchJson(`https://www.arbeitnow.com/api/job-board-api?page=${n}${visa}`); out.push(...((r.json && r.json.data) || [])); }
      catch (err) { if (n === 1) throw err; }
    }
    return out;
  });
  const ok = matcher(q);
  return pages.filter((j) => ok([j.title, (j.tags || []).join(' '), j.company_name].join(' ')))
    .filter((j) => (q.c === 'ch' ? /z[üu]rich|switzerland|schweiz|basel|bern|gen[eè]v|lausanne/i.test(j.location || '') : true))
    .filter((j) => (isRemote(q) ? j.remote : true))
    .slice(0, 25).map((j) => ({
      id: 'an:' + j.slug, title: clean(j.title), company: clean(j.company_name), location: clean(j.location) + (j.remote ? ' (remote)' : ''),
      posted: isoDate(j.created_at), type: (j.job_types || []).join(', '), url: j.url, source: 'arbeitnow'
    }));
}

/* ---------- Jooble (free key on request, many countries) ---------- */
async function jooble(q) {
  const r = await fetchJson('https://jooble.org/api/' + encodeURIComponent(e.JOOBLE_KEY), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keywords: q.type === 'internship' ? q.q + ' internship' : q.q, location: isRemote(q) ? '' : q.loc, page: 1 })
  });
  return ((r.json && r.json.jobs) || []).slice(0, 25).map((j) => ({
    id: 'jb:' + j.id, title: clean(j.title), company: clean(j.company), location: clean(j.location),
    posted: isoDate(j.updated), type: clean(j.type), url: j.link, source: 'jooble'
  }));
}

/* ---------- Remotive (public, remote jobs, please keep calls low) ---------- */
async function remotive(q) {
  if (!isRemote(q)) throw new Error('Remote searches only');
  const r = await cached('rm:' + q.q, 6 * 3600 * 1000, () => fetchJson('https://remotive.com/api/remote-jobs?limit=25&search=' + encodeURIComponent(q.q)));
  return ((r.json && r.json.jobs) || []).map((j) => ({
    id: 'rm:' + j.id, title: clean(j.title), company: clean(j.company_name),
    location: clean(j.candidate_required_location) + ' (remote)', posted: isoDate(j.publication_date),
    type: clean(j.job_type).replace(/_/g, '-'), url: j.url, source: 'remotive'
  }));
}

/* ---------- RemoteOK (public, remote jobs; links must point back to RemoteOK) ---------- */
async function remoteok(q) {
  if (!isRemote(q)) throw new Error('Remote searches only');
  const r = await cached('rok', 3 * 3600 * 1000, () => fetchJson('https://remoteok.com/api', { headers: { 'User-Agent': 'parcours-personal-search-app', Accept: 'application/json' } }));
  const ok = matcher(q);
  return (Array.isArray(r.json) ? r.json.slice(1) : []).filter((j) => ok([j.position, (j.tags || []).join(' '), j.company].join(' ')))
    .slice(0, 25).map((j) => ({
      id: 'rok:' + j.id, title: clean(j.position), company: clean(j.company), location: clean(j.location || 'Worldwide') + ' (remote)',
      posted: isoDate(j.date), type: '', url: j.url || 'https://remoteok.com/remote-jobs/' + j.slug, source: 'remoteok'
    }));
}

const SOURCES = {
  adzuna: { fn: adzuna, on: () => e.ADZUNA_APP_ID && e.ADZUNA_APP_KEY },
  francetravail: { fn: francetravail, on: () => e.FRANCE_TRAVAIL_ID && e.FRANCE_TRAVAIL_SECRET },
  arbeitsagentur: { fn: arbeitsagentur, on: () => true },
  arbeitnow: { fn: arbeitnow, on: () => true },
  jooble: { fn: jooble, on: () => e.JOOBLE_KEY },
  remotive: { fn: remotive, on: () => true },
  remoteok: { fn: remoteok, on: () => true }
};

module.exports = async (req, res) => {
  if (!auth(req, res)) return;
  const b = req.query || {};
  const q = {
    q: String(b.q || '').trim().slice(0, 100), c: String(b.c || 'fr'), loc: String(b.loc || '').trim().slice(0, 80),
    type: String(b.type || ''), visa: b.visa === '1'
  };
  if (!q.q) return res.status(400).json({ error: 'Add keywords.' });
  const wanted = String(b.sources || '').split(',').filter((s) => SOURCES[s]);
  const ids = wanted.length ? wanted : Object.keys(SOURCES);
  const status = {};
  const results = await Promise.allSettled(ids.map(async (id) => {
    if (!SOURCES[id].on()) throw new Error('Not configured on the server');
    return SOURCES[id].fn(q);
  }));
  const merged = new Map();
  results.forEach((r, i) => {
    const id = ids[i];
    if (r.status === 'fulfilled') {
      status[id] = { ok: true, count: r.value.length };
      r.value.filter((j) => j.title && j.url).forEach((j) => {
        const key = (j.title + '|' + j.company).toLowerCase().replace(/\s+/g, ' ');
        if (merged.has(key)) merged.get(key).sources.push(id);
        else merged.set(key, { ...j, c: q.c, sources: [id] });
      });
    } else {
      status[id] = { ok: false, error: String((r.reason && r.reason.message) || 'Failed') };
    }
  });
  const jobs = [...merged.values()].sort((a, c) => String(c.posted).localeCompare(String(a.posted)));
  res.setHeader('Cache-Control', 'no-store');
  res.status(200).json({ jobs, sources: status });
};

module.exports._test = { tokens, matcher, isRemote };
