-- =====================================================================
-- 냄새 나침반 · 공기청정기 사전 작동(C안) 테이블  (2026-10-27)
-- Supabase 대시보드 > SQL Editor 에 전체를 붙여넣고 Run.
-- 서버 정기 작업(service_role)이 예보로 가동 일정을 계산해 device_plan 에 쓰고,
-- 기기(ESP32/우노 연결기)와 휴대폰 화면은 publishable 키 + 기기 토큰으로 아래 함수만 호출한다.
-- 테이블을 직접 읽고 쓰는 권한은 anon/authenticated 에 주지 않는다.
-- =====================================================================
create extension if not exists pgcrypto with schema extensions;

create table if not exists public.devices (
  device_id     text primary key,
  name          text not null default '우리 집 공기청정기',
  zone_id       text not null default 'U01' check (zone_id in ('U01','U02','U03')),
  lead_min      int  not null default 40 check (lead_min between 0 and 180),   -- 미리 켤 시간
  tail_min      int  not null default 30 check (tail_min between 0 and 180),   -- 냄새 구간 끝난 뒤 더 돌릴 시간
  trigger_level text not null default '높음' check (trigger_level in ('보통','높음')),
  mode          text not null default 'auto' check (mode in ('auto','on','off')),
  manual_until  timestamptz,                    -- 수동(on/off) 자동 복귀 시각
  token_hash    text not null,                  -- sha256(기기 토큰). 토큰 원문은 저장하지 않는다
  created_at    timestamptz not null default now()
);

create table if not exists public.device_plan (       -- 서버가 계산한 최신 가동 일정 (기기당 1행)
  device_id     text primary key references public.devices(device_id) on delete cascade,
  computed_at   timestamptz not null,
  basis         text not null,                  -- kma(기상청 예보) / demo(시연)
  issued        text,                           -- 예보 발표 시각 문자열
  action        text not null check (action in ('ON','OFF','HOLD')),
  state         text not null,                  -- pre_run / running / standby / hold
  reason        text not null,
  next_on_at    timestamptz, next_odor_at timestamptz, next_off_at timestamptz,
  episodes      jsonb not null default '[]'     -- 앞으로의 가동 구간 전체(기기가 인터넷 끊겨도 따라갈 수 있게)
);

create table if not exists public.device_status (     -- 기기가 마지막으로 보고한 상태
  device_id   text primary key references public.devices(device_id) on delete cascade,
  seen_at     timestamptz not null default now(),
  fan_on      boolean, mode text, fw text, rssi int, indoor_idx real, note text
);

create table if not exists public.device_log (
  id bigint generated always as identity primary key,
  device_id text not null references public.devices(device_id) on delete cascade,
  ts timestamptz not null default now(),
  kind text not null,                           -- plan / on / off / override / report / settings
  detail text
);

alter table public.devices       enable row level security;
alter table public.device_plan   enable row level security;
alter table public.device_status enable row level security;
alter table public.device_log    enable row level security;
revoke all on public.devices, public.device_plan, public.device_status, public.device_log from anon, authenticated;
grant  all on public.devices, public.device_plan, public.device_status, public.device_log to service_role;

-- 토큰 확인
create or replace function public._device_ok(p_device text, p_token text) returns boolean
language sql stable security definer set search_path = public, extensions as $$
  select exists(select 1 from devices where device_id = p_device
                and token_hash = encode(extensions.digest(p_token, 'sha256'), 'hex'));
$$;

-- 기기·휴대폰: 지금 해야 할 일 + 일정 + 설정
create or replace function public.device_get(p_device text, p_token text) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare d devices; p device_plan; eff text; src text;
begin
  if not _device_ok(p_device, p_token) then raise exception 'unauthorized'; end if;
  select * into d from devices where device_id = p_device;
  select * into p from device_plan where device_id = p_device;
  if d.mode <> 'auto' and d.manual_until is not null and d.manual_until < now() then
    update devices set mode = 'auto', manual_until = null where device_id = p_device;
    insert into device_log(device_id, kind, detail) values (p_device, 'settings', '수동 시간 종료 · 자동 복귀');
    d.mode := 'auto';
  end if;
  if d.mode = 'on' then eff := 'ON'; src := 'manual';
  elsif d.mode = 'off' then eff := 'OFF'; src := 'manual';
  else eff := coalesce(p.action, 'HOLD'); src := 'plan'; end if;
  return jsonb_build_object(
    'now', now(), 'command', eff, 'source', src,
    'settings', jsonb_build_object('name', d.name, 'zone_id', d.zone_id, 'lead_min', d.lead_min, 'tail_min', d.tail_min,
                                   'trigger_level', d.trigger_level, 'mode', d.mode, 'manual_until', d.manual_until),
    'plan', case when p.device_id is null then null else jsonb_build_object(
       'computed_at', p.computed_at, 'basis', p.basis, 'issued', p.issued, 'action', p.action, 'state', p.state,
       'reason', p.reason, 'next_on_at', p.next_on_at, 'next_odor_at', p.next_odor_at, 'next_off_at', p.next_off_at,
       'episodes', p.episodes) end,
    'status', (select to_jsonb(s) - 'device_id' from device_status s where s.device_id = p_device));
end; $$;

-- 기기: 상태 보고 (팬, 모드, 실내 지수 등)
create or replace function public.device_report(p_device text, p_token text, p_fan boolean, p_mode text,
    p_fw text default null, p_rssi int default null, p_indoor real default null, p_note text default null) returns void
language plpgsql security definer set search_path = public, extensions as $$
declare prev boolean;
begin
  if not _device_ok(p_device, p_token) then raise exception 'unauthorized'; end if;
  select fan_on into prev from device_status where device_id = p_device;
  insert into device_status(device_id, seen_at, fan_on, mode, fw, rssi, indoor_idx, note)
  values (p_device, now(), p_fan, p_mode, p_fw, p_rssi, p_indoor, p_note)
  on conflict (device_id) do update set seen_at = now(), fan_on = excluded.fan_on, mode = excluded.mode,
    fw = excluded.fw, rssi = excluded.rssi, indoor_idx = excluded.indoor_idx, note = excluded.note;
  if prev is distinct from p_fan then
    insert into device_log(device_id, kind, detail) values (p_device, case when p_fan then 'on' else 'off' end, p_note);
  end if;
end; $$;

-- 휴대폰: 설정 변경. mode 를 on/off 로 바꾸면 manual_hours 뒤 자동 복귀
create or replace function public.device_set(p_device text, p_token text, p_zone text default null,
    p_lead int default null, p_trigger text default null, p_mode text default null, p_manual_hours int default 2)
returns void language plpgsql security definer set search_path = public, extensions as $$
begin
  if not _device_ok(p_device, p_token) then raise exception 'unauthorized'; end if;
  update devices set
    zone_id = coalesce(p_zone, zone_id), lead_min = coalesce(p_lead, lead_min),
    trigger_level = coalesce(p_trigger, trigger_level), mode = coalesce(p_mode, mode),
    manual_until = case when p_mode in ('on','off') then now() + make_interval(hours => p_manual_hours)
                        when p_mode = 'auto' then null else manual_until end
  where device_id = p_device;
  insert into device_log(device_id, kind, detail)
  values (p_device, 'settings', concat_ws(' ', 'zone='||p_zone, 'lead='||p_lead, 'trigger='||p_trigger, 'mode='||p_mode));
end; $$;

revoke all on function public._device_ok(text,text) from public, anon, authenticated;
grant execute on function public.device_get(text,text) to anon, authenticated;
grant execute on function public.device_report(text,text,boolean,text,text,int,real,text) to anon, authenticated;
grant execute on function public.device_set(text,text,text,int,text,text,int) to anon, authenticated;

-- 기기 1대 등록 (토큰 원문은 저장소 .streamlit/secrets.toml [device] 에만 있음)
insert into public.devices(device_id, zone_id, token_hash)
values ('AP01', 'U01', '5cdccbc8cd6387f86be0fa5d816b84367dab9371f05a20da8e8818a5801024b3')
on conflict (device_id) do nothing;

select device_id, zone_id, lead_min, mode from public.devices;

-- =====================================================================
-- 2026-10-28: device_get 의 command 를 저장된 action 이 아니라 '지금 시각이 가동 구간 안인지' 로 정한다.
-- 일정은 15분마다만 다시 계산되므로, 그 사이 on_at 이 지나도 action 이 OFF 로 남는 문제를 막는다. SQL Editor 에서 다시 실행.
-- =====================================================================
create or replace function public.device_get(p_device text, p_token text) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare d devices; p device_plan; eff text; src text; active boolean;
begin
  if not _device_ok(p_device, p_token) then raise exception 'unauthorized'; end if;
  select * into d from devices where device_id = p_device;
  select * into p from device_plan where device_id = p_device;
  if d.mode <> 'auto' and d.manual_until is not null and d.manual_until < now() then
    update devices set mode = 'auto', manual_until = null where device_id = p_device;
    insert into device_log(device_id, kind, detail) values (p_device, 'settings', '수동 시간 종료 · 자동 복귀');
    d.mode := 'auto';
  end if;
  if d.mode = 'on' then eff := 'ON'; src := 'manual';
  elsif d.mode = 'off' then eff := 'OFF'; src := 'manual';
  elsif p.device_id is null or p.state = 'hold' then eff := 'HOLD'; src := 'plan';
  else
    select exists(select 1 from jsonb_array_elements(coalesce(p.episodes, '[]'::jsonb)) e
                  where (e->>'on_at')::timestamptz <= now() and now() < (e->>'off_at')::timestamptz) into active;
    eff := case when active then 'ON' else 'OFF' end; src := 'plan';
  end if;
  return jsonb_build_object(
    'now', now(), 'command', eff, 'source', src,
    'settings', jsonb_build_object('name', d.name, 'zone_id', d.zone_id, 'lead_min', d.lead_min, 'tail_min', d.tail_min,
                                   'trigger_level', d.trigger_level, 'mode', d.mode, 'manual_until', d.manual_until),
    'plan', case when p.device_id is null then null else jsonb_build_object(
       'computed_at', p.computed_at, 'basis', p.basis, 'issued', p.issued, 'action', p.action, 'state', p.state,
       'reason', p.reason, 'next_on_at', p.next_on_at, 'next_odor_at', p.next_odor_at, 'next_off_at', p.next_off_at,
       'episodes', p.episodes) end,
    'status', (select to_jsonb(s) - 'device_id' from device_status s where s.device_id = p_device));
end; $$;

-- =====================================================================
-- 2026-10-28: 시연 가상 예보를 배포본(Streamlit Cloud)도 보게 하는 표. run_demo_prep 이 쓰고 run_demo_off 가 지운다. 서버 키만 접근.
-- =====================================================================
create table if not exists public.demo_forecast (
 id int primary key default 1 check (id = 1),
 rows jsonb not null,
 created_at timestamptz not null default now()
);
alter table public.demo_forecast enable row level security;
revoke all on public.demo_forecast from anon, authenticated;
grant all on public.demo_forecast to service_role;
