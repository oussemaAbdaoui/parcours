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

-- Interview stories per company and role (Glassdoor, Reddit), mirrored from the Redis cache parcours:insights.
create table if not exists insights (
  key        text    primary key,                 -- insights.key(company, role)
  company_id integer references companies (id),
  role       text    not null default '',
  data       jsonb   not null,
  updated_at bigint  not null
);
create index if not exists insights_company on insights (company_id);
