// Sandbox server for the public app: serves the site's files and /api/u (the real handler) over an in-memory
// Postgres (PGlite). Nothing reaches Neon or Redis. Used by tests/public_app_test.py; run by hand to try the page:
//   node tests/public_server.js 4173   ->  http://localhost:4173
const fs = require('fs');
const http = require('http');
const path = require('path');
const { PGlite } = require('@electric-sql/pglite');
delete process.env.UPSTASH_REDIS_REST_URL; delete process.env.KV_REST_API_URL;
process.env.APP_PASSWORD = 'sandbox-app-password';
const { handle } = require('../api/_users');
const { auth } = require('../api/_lib');

const ROOT = path.join(__dirname, '..');
const TYPES = { '.html': 'text/html; charset=utf-8', '.png': 'image/png', '.ico': 'image/x-icon', '.js': 'text/javascript', '.json': 'application/json' };

(async () => {
  const pg = new PGlite();
  const schema = fs.readFileSync(path.join(ROOT, 'db', 'schema.sql'), 'utf8');
  await pg.exec(schema.slice(schema.indexOf('-- ---------- Public users')));
  const query = (t, p) => pg.query(t, p);
  const pool = { query, connect: async () => ({ query, release() {} }) };

  http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    // Sandbox only: make an account the admin (on the real site this is a database update).
    if (url.pathname === '/__test/promote') {
      await pg.query("update users set role = 'admin' where email = $1", [url.searchParams.get('email')]);
      return res.end('ok');
    }
    // The admin API, behind the real check (api/_lib.js auth): an empty admin state, enough for admin.html to start.
    if (url.pathname.startsWith('/api/') && url.pathname !== '/api/u') {
      const out = { status(s) { res.statusCode = s; return this; }, json(j) { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(j)); return this; } };
      if (!(await auth({ headers: req.headers }, out))) return;
      return out.status(200).json(url.searchParams.get('ping') ? { ok: true, sources: {}, sync: true, ai: false, gmail: false } : { state: null, version: 0 });
    }
    if (url.pathname === '/api/u') {
      let raw = '';
      for await (const c of req) raw += c;
      let body = {};
      try { body = raw ? JSON.parse(raw) : {}; } catch (e) { /* bad JSON: empty body */ }
      const r = { method: req.method, query: Object.fromEntries(url.searchParams), body, headers: req.headers };
      const out = {
        setHeader: (k, v) => res.setHeader(k, v),
        status(s) { res.statusCode = s; return this; },
        json(j) { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(j)); return this; },
      };
      try { await handle(pool, r, out); } catch (e) { console.error(e); res.statusCode = 500; res.end('{}'); }
      return;
    }
    const file = path.join(ROOT, url.pathname === '/' ? 'index.html' : url.pathname === '/admin' ? 'admin.html' : path.normalize(decodeURIComponent(url.pathname)).replace(/^[/\\]+/, ''));
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.statusCode = 404; return res.end(); }
    res.setHeader('content-type', TYPES[path.extname(file)] || 'application/octet-stream');
    fs.createReadStream(file).pipe(res);
  }).listen(Number(process.argv[2] || 4173), () => console.log('ready'));
})();
