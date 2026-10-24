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
 record_origin text not null check (record_origin in ('resident','device_button')),
 idempotency_key uuid not null unique
);
alter table public.observations enable row level security;
revoke all on public.observations from anon, authenticated;
grant all on public.observations to service_role;
create index if not exists observations_participant on public.observations(participant_id, observed_at desc);
-- 기존 테이블이 있으면 한 번 실행: 공기질 관리 기기 버튼 제보(record_origin='device_button') 허용
alter table public.observations drop constraint if exists observations_record_origin_check;
alter table public.observations add constraint observations_record_origin_check check (record_origin in ('resident','device_button'));

-- =====================================================================
-- 센서 기반 수집 (2026-10-22, 최종설계 v2). Supabase SQL Editor에서 실행.
-- 노드(ESP32)는 anon 키로 sensor_readings 에 INSERT 만 할 수 있다. 읽기·집계는 서버(service_role)만.
-- =====================================================================
create table if not exists public.sensor_sites (
 site_id text primary key check (site_id in ('S1','S2','S3')),
 name text not null,
 role text not null,                       -- frontline | inland | source_candidate
 lat double precision, lon double precision,
 floor_m double precision,
 installed_at timestamptz,
 note text
);
insert into public.sensor_sites(site_id,name,role) values
 ('S1','운양 북측(한강변)','frontline'),('S2','운양 남측(모담산 인근)','inland'),('S3','하성면','source_candidate')
on conflict (site_id) do nothing;

create table if not exists public.sensor_readings (
 id bigint generated always as identity primary key,
 site_id text not null references public.sensor_sites(site_id),
 ts timestamptz not null,
 adc_mq137 integer,                        -- 0..4095 (분압 후 ESP32 ADC)
 voc_index integer,                        -- SGP40 VOC index 0..500
 humidity_pct real, temperature_c real,
 heater_sec integer,                       -- 전원 인가 후 경과 초(예열 판정)
 rssi integer, fw_version text,
 received_at timestamptz not null default now(),
 unique (site_id, ts)
);
create index if not exists sensor_readings_site_ts on public.sensor_readings(site_id, ts desc);
alter table public.sensor_readings enable row level security;
revoke all on public.sensor_readings from anon, authenticated;
grant insert on public.sensor_readings to anon;          -- 노드 전송용(INSERT 만)
grant all on public.sensor_readings to service_role;
drop policy if exists sensor_readings_node_insert on public.sensor_readings;
create policy sensor_readings_node_insert on public.sensor_readings for insert to anon
 with check (site_id in ('S1','S2','S3') and ts > now() - interval '7 days' and ts < now() + interval '1 hour');

create table if not exists public.sensor_index_10min (
 site_id text not null references public.sensor_sites(site_id),
 ts timestamptz not null,                  -- 10분 창 시작
 n integer not null,
 mq_rs_mean real, mq_rs_min real, voc_mean real, voc_max real,
 humidity_pct real, temperature_c real,
 mq_baseline real, mq_index real,          -- (baseline - rs)/baseline, 습도·기온 보정 후
 voc_baseline real, voc_index_rel real,
 thr_mq real, thr_voc real,
 event_mq boolean, event_voc boolean,
 event_grade text,                         -- none | local | sure | inflow
 quality_flag text,                        -- ok | preheat | gap | rh_high | event
 primary key (site_id, ts)
);
alter table public.sensor_index_10min enable row level security;
revoke all on public.sensor_index_10min from anon, authenticated;
grant all on public.sensor_index_10min to service_role;

create table if not exists public.sensor_calibration (
 site_id text primary key references public.sensor_sites(site_id),
 run_id text not null, started_at timestamptz, ended_at timestamptz,
 mq_gain real not null default 1, mq_offset real not null default 0,
 voc_gain real not null default 1, voc_offset real not null default 0,
 rh_coef real default 0, temp_coef real default 0,   -- 습도·기온 보정 회귀계수
 note text
);
alter table public.sensor_calibration enable row level security;
revoke all on public.sensor_calibration from anon, authenticated;
grant all on public.sensor_calibration to service_role;

create table if not exists public.site_events (
 id bigint generated always as identity primary key,
 site_id text not null references public.sensor_sites(site_id),
 start_ts timestamptz not null, end_ts timestamptz,
 event_type text not null check (event_type in ('cooking','window_closed','power_off','rain_direct','construction','sensor_moved','other')),
 note text, created_at timestamptz not null default now()
);
alter table public.site_events enable row level security;
revoke all on public.site_events from anon, authenticated;
grant all on public.site_events to service_role;

create table if not exists public.weather_fcst (
 id bigint generated always as identity primary key,
 kind text not null check (kind in ('ncst','ultra_fcst','vilage_fcst')),
 nx integer not null, ny integer not null,
 base_dt timestamptz not null,             -- 발표시각
 fcst_dt timestamptz not null,             -- 대상시각(실황은 base와 동일)
 wind_dir_deg real, wind_speed_ms real, temperature_c real, humidity_pct real,
 rain_1h_mm real, pop_pct real, sky text, pty text,
 received_at timestamptz not null default now(),
 unique (kind, nx, ny, base_dt, fcst_dt)
);
alter table public.weather_fcst enable row level security;
revoke all on public.weather_fcst from anon, authenticated;
grant all on public.weather_fcst to service_role;

create table if not exists public.weather_obs (
 station_id text not null, ts timestamptz not null,
 wind_dir_deg real, wind_speed_ms real, temperature_c real, humidity_pct real, rain_1h_mm real, pressure_hpa real,
 source text not null default 'kma_aws',
 primary key (station_id, ts)
);
alter table public.weather_obs enable row level security;
revoke all on public.weather_obs from anon, authenticated;
grant all on public.weather_obs to service_role;

-- =====================================================================
-- 주민 제보 GPS 교차검증 (2026-10-24). 기존 observations 에 위치 열 추가. SQL Editor에서 한 번 실행.
-- lat/lon 은 앱이 소수 3자리(약 100 m)로 반올림해 보낸다. location_check='rejected' 는 분석에서 제외.
-- =====================================================================
alter table public.observations add column if not exists lat double precision;
alter table public.observations add column if not exists lon double precision;
alter table public.observations add column if not exists accuracy_m integer;
alter table public.observations add column if not exists location_check text not null default 'unverified'
  check (location_check in ('verified','rejected','unverified'));
create index if not exists observations_location_check on public.observations(location_check);
