// Reads {profile, targets, items} on stdin and prints the ids of offers that hit a dealbreaker for this profile
// (too senior, required language missing, work-permit restriction, internship after graduation, degree too low,
// your exclusion words, deadline passed). Same rules as the app, because it is the app's own score.js.
const S = require('../score.js');
let raw = '';
process.stdin.on('data', (d) => (raw += d)).on('end', () => {
  const { profile, targets, items } = JSON.parse(raw);
  const p = Object.assign({ countries: ['fr', 'de', 'ca', 'ch', 'gl', 'tn'], visa: { fr: true, de: true, ca: true, ch: true } }, profile || {}, { targets: targets || [] });
  const out = {};
  for (const x of items) {
    const m = S.score(x, p);
    if (m.blockers.length) out[x.id] = m.blockers;
  }
  process.stdout.write(JSON.stringify(out));
});
