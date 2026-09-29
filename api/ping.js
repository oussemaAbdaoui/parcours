const { auth, upstash, aiOn } = require('./_lib');

// Login check + tells the app which optional sources and features are configured.
module.exports = (req, res) => {
  if (!auth(req, res)) return;
  const e = process.env;
  res.status(200).json({
    ok: true,
    sources: {
      adzuna: !!(e.ADZUNA_APP_ID && e.ADZUNA_APP_KEY),
      francetravail: !!(e.FRANCE_TRAVAIL_ID && e.FRANCE_TRAVAIL_SECRET),
      arbeitsagentur: true,
      arbeitnow: true,
      jooble: !!e.JOOBLE_KEY,
      remotive: true,
      remoteok: true,
      indeed: true,
      linkedin: true,
      glassdoor: true
    },
    sync: !!upstash(),
    ai: aiOn(req),
    gmail: !!(e.GOOGLE_CLIENT_ID && e.GOOGLE_CLIENT_SECRET && upstash())
  });
};
