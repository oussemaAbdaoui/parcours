// Neon Postgres pool for the API functions (pooled DATABASE_URL), attached to Vercel Fluid compute so idle
// connections close cleanly when an instance is suspended.
const { Pool } = require('pg');
const { attachDatabasePool } = require('@vercel/functions');

let pool = null;
function db() {
  if (!process.env.DATABASE_URL) return null;
  if (!pool) {
    pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 5, idleTimeoutMillis: 10000 });
    attachDatabasePool(pool);
  }
  return pool;
}

module.exports = { db };
