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
  licensed   boolean not null default false,
  data       jsonb   not null,
  seen_at    bigint  not null
);
create index if not exists poli_companies_norm on poli_companies (norm);

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
