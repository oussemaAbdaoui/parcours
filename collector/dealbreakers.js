// Reads {profile, targets, items} on stdin and prints {blocked: {id: [reasons]}, exp: {id: {min, max, label}}}.
// blocked: offers that hit a dealbreaker for this profile (too senior, required language missing, work-permit
// restriction, internship after graduation, degree too low, your exclusion words, deadline passed).
// exp: the experience each offer asks for, read from its title and description.
// Same rules as the app, because it is the app's own score.js.
const S = require('../score.js');
let raw = '';
process.stdin.on('data', (d) => (raw += d)).on('end', () => {
  const { profile, targets, items } = JSON.parse(raw);
  const hasProfile = profile && Object.keys(profile).length;
  const p = Object.assign({ countries: ['fr', 'de', 'ca', 'ch', 'gl', 'tn'], visa: { fr: true, de: true, ca: true, ch: true } }, profile || {}, { targets: targets || [] });
  const blocked = {}, exp = {}, scores = {};
  const ctx = { idf: hasProfile ? S.buildIdf(items, p.cv) : null }; // CV similarity, as in the app
  for (const x of items) {
    const e = S.offerYears((x.title || '') + ' . ' + (x.desc || ''));
    if (e) exp[x.id] = e;
    if (!hasProfile) continue;
    const m = S.score(x, p, Date.now(), ctx);
    scores[x.id] = m.score;
    if (m.blockers.length) blocked[x.id] = m.blockers;
  }
  process.stdout.write(JSON.stringify({ blocked, exp, scores }));
});
