// Applies db/schema.sql over the direct (unpooled) Neon connection.
// Usage: node db/migrate.js   (reads DATABASE_URL_UNPOOLED from the environment or .env.local)
const fs = require('fs');
const path = require('path');
const { Client } = require('pg');

function envFromFile(file) {
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^"|"$/g, '');
  }
}

(async () => {
  envFromFile(path.join(__dirname, '..', '.env.local'));
  const url = process.env.DATABASE_URL_UNPOOLED || process.env.DATABASE_URL;
  if (!url) throw new Error('DATABASE_URL_UNPOOLED is not set.');
  const client = new Client({ connectionString: url });
  await client.connect();
  await client.query(fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf8'));
  const { rows } = await client.query("select table_name from information_schema.tables where table_schema = 'public' order by 1");
  console.log('schema applied; tables:', rows.map((r) => r.table_name).join(', '));
  await client.end();
})().catch((e) => { console.error(e.message); process.exit(1); });
