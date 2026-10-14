// Sandbox data for the Discover tests: the offers and datasets tables (as in db/schema.sql) with a few made-up rows
// of each kind. Used by tests/users.test.js and tests/public_server.js.
const SCHEMA = `
create table if not exists offers (id text primary key, company_id integer, origin text not null default 'cloud', source text not null default '',
  country text not null default '', kind text not null default 'job', title text not null default '', found_at bigint, data jsonb not null, updated_at bigint not null);
create table if not exists datasets (set text not null, id text not null, data jsonb not null, updated_at bigint not null, primary key (set, id));`;

const now = Date.now();
const offer = (id, kind, c, title, org, extra = {}) => ({ id, kind, c, title, org, url: 'https://example.org/' + id, location: 'Paris', desc: 'Long description of ' + title + '. '.repeat(50),
  foundAt: now - id.length * 1000, posted: '2026-10-10', type: '', req: { required_skills: ['Python', 'SQL'], evidence: 'secret scoring detail' }, ...extra });
const OFFERS = [
  offer('j1', 'job', 'fr', 'Data Engineer', 'Acme France'),
  offer('j2', 'job', 'tn', 'Développeur Full stack', 'Tunis Soft'),
  offer('j3', 'job', 'de', 'Ingénieur en Apprentissage Automatique', 'ML GmbH'),
  offer('i1', 'job', 'fr', 'Stage PFE Data Science', 'Acme France'),
  offer('i2', 'job', 'tn', 'Software Engineer', 'Tunis Soft', { type: 'Internship' }),
  offer('a1', 'job', 'fr', 'Développeur web en alternance', 'Alt Corp'),
  offer('p1', 'phd', 'fr', 'PhD in NLP', 'Université Paris'),
];
const DATASETS = [
  ['masters', 'm1', { id: 'm1', title: 'MSc Data Science', org: 'TU Example', country: 'de', city: 'Berlin', type: 'program', lang: 'English', deadline: '2027-01-15', url: 'https://example.org/m1', desc: 'Programme', terms: ['x'] }],
  ['masters', 'm2', { id: 'm2', title: 'Master IA', org: 'Université Lyon', country: 'fr', city: 'Lyon', type: 'program', lang: 'French', url: 'https://example.org/m2' }],
  ['masters', 's1', { id: 's1', title: 'Eiffel Scholarship', org: 'Campus France', country: 'fr', type: 'scholarship', deadline: '2027-01-08', url: 'https://example.org/s1' }],
  ['academia-schools', 'r1', { id: 'r1', name: 'University of Carthage', c: 'tn', city: 'Tunis', types: ['education'], website: 'https://ucar.rnu.tn' }],
  ['academia-schools', 'r2', { id: 'r2', name: 'Some Research Lab', c: 'fr', city: 'Paris', types: ['facility'] }],
  ['academia-people', 'A1', { id: 'A1', name: 'Prof Amira Test', c: 'tn', ror: 'r1', score: 70, fields: ['Machine learning', 'NLP'], works: 40, cited: 900,
    emails: [{ email: 'amira@example.tn' }], orcid: '0000-0000-0000-0001', recent: [{ title: 'A paper', year: 2026 }, { title: 'Another', year: 2025 }] }],
];

async function load(pg) {
  await pg.exec(SCHEMA);
  for (const o of OFFERS) {
    await pg.query('insert into offers (id, country, kind, title, found_at, data, updated_at) values ($1, $2, $3, $4, $5, $6, $5) on conflict do nothing',
      [o.id, o.c, o.kind, o.title, o.foundAt, JSON.stringify(o)]);
  }
  for (const [set, id, d] of DATASETS) await pg.query('insert into datasets values ($1, $2, $3, $4) on conflict do nothing', [set, id, JSON.stringify(d), now]);
}

module.exports = { load, OFFERS, DATASETS };
