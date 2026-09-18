-- Run manually in your own Supabase SQL editor. Never expose the service role key.
create table if not exists public.observations (
 observation_id uuid primary key,
 participant_id text not null,
 zone_id text not null check (zone_id in ('Z1','Z2','Z3')),
 observed_at timestamptz not null,
 received_at timestamptz not null,
 context text not null check (context in ('indoor','outdoor')),
 odor_detected boolean,
 intensity integer check (intensity between 0 and 5),
 odor_type text not null,
 collection_mode text not null check (collection_mode in ('scheduled','spontaneous','followup')),
 prediction_seen boolean not null default false,
 window_id text not null,
 record_origin text not null check (record_origin='resident'),
 idempotency_key uuid not null unique
);
alter table public.observations enable row level security;
revoke all on public.observations from anon, authenticated;
grant all on public.observations to service_role;
create index if not exists observations_participant on public.observations(participant_id, observed_at desc);
