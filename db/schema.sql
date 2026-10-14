-- Parcours user data in Neon Postgres. Applied by db/migrate.js (direct, unpooled connection).
-- Collected data moves here from Upstash Redis one store at a time (Poli first); caches and counters stay in Redis.

-- One row per list item: applications, saved jobs, journal notes, saved searches, feeds.
-- updated_at is the time of the edit (ms, from the device that made it): the newest edit of each item wins,
-- so edits to different items on different devices never overwrite each other. Deletions are kept as
-- tombstones (deleted = true) so a stale device cannot bring an item back.
create table if not exists items (
  collection text   not null,
  id         text   not null,
  data       jsonb  not null,
  created_at bigint not null,
  updated_at bigint not null,
  deleted    boolean not null default false,
  primary key (collection, id)
);
create index if not exists items_updated_at on items (updated_at);

-- Single values: profile, statuses, route notes, company notes, read markers...
create table if not exists settings (
  key        text   primary key,
  data       jsonb  not null,
  updated_at bigint not null
);

-- ---------- Collected data (written by the collectors, read by the API) ----------
-- Poli (UK visa sponsors). Merged, never deleted: a record Poli stops showing keeps what was stored, and an empty
-- field never blanks a stored one (the collector strips empty values; data = old || new). seen_at: last listed.
create extension if not exists pg_trgm;

create table if not exists poli_companies (
  id         integer primary key,
  name       text    not null,
  norm       text    not null,           -- company key shared with offers (enrich._norm: no legal forms, no country words)
  legal_norm text    not null default '',  -- the same for the registered name ("ASOS.com Ltd" for ASOS)
  licensed   boolean not null default false,
  data       jsonb   not null,
  seen_at    bigint  not null
);
alter table poli_companies add column if not exists legal_norm text not null default '';
create index if not exists poli_companies_norm on poli_companies (norm);
create index if not exists poli_companies_legal_norm on poli_companies (legal_norm);

create table if not exists poli_people (
  id          integer primary key,
  company_id  integer,
  name        text    not null default '',
  title       text    not null default '',
  sponsorship text    not null default '',
  network     boolean not null default false,
  search      text    not null default '',  -- lower-case name, title, company and expertise, for the people search
  data        jsonb   not null,
  seen_at     bigint  not null
);
create index if not exists poli_people_company on poli_people (company_id);
create index if not exists poli_people_sponsorship on poli_people (sponsorship);
create index if not exists poli_people_search on poli_people using gin (search gin_trgm_ops);

create table if not exists poli_jobs (
  id         text    primary key,
  company_id integer,
  data       jsonb   not null,
  seen_at    bigint  not null
);

-- Offers and companies (phase 2). One row per company, keyed by the normalised name every store already uses
-- (enrich._norm); offers, ratings, the hiring log, interview stories and the Poli sponsor link point to its id.
create table if not exists companies (
  id         serial  primary key,
  norm       text    not null unique,
  name       text    not null,
  rating     jsonb,                      -- {rating, count, source, url, at}: Indeed reviews, "not found" included
  rating_at  bigint,
  poli_id    integer,                    -- poli_companies.id when the company is a UK visa sponsor
  updated_at bigint  not null
);

-- Collected offers, written by every collector run (the same set as the Redis hash parcours:opps:items).
create table if not exists offers (
  id         text    primary key,
  company_id integer references companies (id),
  origin     text    not null default 'cloud',   -- cloud (GitHub Actions) or home (the PC)
  source     text    not null default '',
  country    text    not null default '',
  kind       text    not null default 'job',
  title      text    not null default '',
  found_at   bigint,
  data       jsonb   not null,                   -- the offer as the app receives it
  updated_at bigint  not null
);
create index if not exists offers_company on offers (company_id);

-- Hiring log: each offer a company was seen posting (kept after the offer itself ages out).
create table if not exists company_seen (
  company_id integer not null references companies (id),
  offer_id   text    not null,
  day        date    not null,
  kind       text    not null default 'job',
  src        text    not null default 's',      -- p: posted date, s: day first seen, b: backfilled
  primary key (company_id, offer_id)
);

-- Interview stories per company and role (Glassdoor, Reddit), fetched by the PC collector (collector/insights.py).
create table if not exists insights (
  key        text    primary key,                 -- insights.key(company, role)
  company_id integer references companies (id),
  role       text    not null default '',
  data       jsonb   not null,
  updated_at bigint  not null
);
create index if not exists insights_company on insights (company_id);

-- Phase 3: the other collected sets, each a keyed list the collector refreshes (upserts, and drops entries a source
-- no longer lists): masters (collector/masters.py), academia-schools and academia-people (collector/academia.py).
create table if not exists datasets (
  set        text    not null,
  id         text    not null,
  data       jsonb   not null,
  updated_at bigint  not null,
  primary key (set, id)
);

-- UK register of licensed sponsors (Home Office, Skilled Worker route), refreshed weekly by collector/uk_register.py.
-- norm: the registered or trading ("t/a") name normalised; base: the same without generic endings (technologies,
-- group, operations...), so "Wayve Technologies Ltd" matches the offers' "Wayve".
create table if not exists uk_sponsors (
  norm       text    primary key,
  base       text    not null,
  name       text    not null,
  town       text    not null default '',
  updated_at bigint  not null
);
create index if not exists uk_sponsors_base on uk_sponsors (base);
create index if not exists uk_sponsors_squash on uk_sponsors (replace(base, ' ', ''));
create index if not exists uk_sponsors_squash_norm on uk_sponsors (replace(norm, ' ', ''));
alter table companies add column if not exists uk_sponsor boolean;   -- on the UK register (null: not checked yet)

-- Offers dropped as dealbreakers after their text was read, with a fingerprint of the profile that judged them: a
-- run skips them when found again (no page, proxy or Claude reading spent twice) until the profile changes.
create table if not exists offers_dropped (
  id         text    primary key,
  reasons    text[]  not null,
  profile    text    not null,
  dropped_at bigint  not null
);

-- Official register facts (collector/fr_register.py: INSEE SIRENE for companies with offers in France): staff band,
-- founding year, sector, size category, active or closed. {"none": true} when no exact name match. Lists the company
-- belongs to ("Next40", "French Tech 120").
alter table companies add column if not exists register jsonb;
alter table companies add column if not exists lists text[];

-- ---------- Public users (the public app, app.html) ----------
-- The admin (you) keeps APP_PASSWORD and every table above; public users never read or write them. Each user's
-- tracker, saved offers and profile live in user_items / user_settings, the same newest-edit-wins rows as items /
-- settings with the owner's id in the key. Deleting a user deletes their sessions and data (on delete cascade).
create table if not exists users (
  id         text    primary key,              -- random UUID
  email      text    not null unique,          -- lower-case
  name       text    not null default '',
  pass       text    not null,                 -- scrypt$salt$hash (base64)
  plan       text    not null default 'free',  -- free or paid
  plan_until bigint,                           -- paid plan end (ms); null on free
  created_at bigint  not null,
  seen_at    bigint
);

-- Signed-in devices: the sha256 of the cookie's random token, never the token itself.
create table if not exists sessions (
  token      text    primary key,
  user_id    text    not null references users (id) on delete cascade,
  created_at bigint  not null,
  expires_at bigint  not null
);
create index if not exists sessions_user on sessions (user_id);

create table if not exists user_items (
  user_id    text    not null references users (id) on delete cascade,
  collection text    not null,
  id         text    not null,
  data       jsonb   not null,
  created_at bigint  not null,
  updated_at bigint  not null,
  deleted    boolean not null default false,
  primary key (user_id, collection, id)
);

create table if not exists user_settings (
  user_id    text    not null references users (id) on delete cascade,
  key        text    not null,
  data       jsonb   not null,
  updated_at bigint  not null,
  primary key (user_id, key)
);
