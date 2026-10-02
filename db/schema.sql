-- Parcours user data in Neon Postgres. Applied by db/migrate.js (direct, unpooled connection).
-- Offers, caches and job queues stay in Upstash Redis.

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
