-- =====================================================================
-- 냄새 나침반 · 기기 연결 코드 + 휴대폰/웹 전용 토큰 (2026-10-27)
-- device.sql 다음에 실행. Supabase > SQL Editor 에 전체를 붙여넣고 Run.
--  - 기기(ESP32/우노 연결기)는 기기 토큰, 웹·휴대폰은 연결 코드로 받은 '클라이언트 토큰'을 쓴다.
--  - 클라이언트 토큰은 조회(device_get)·설정(device_set)만 가능. 상태 보고·코드 발급은 기기 토큰만.
--  - 집 주소·좌표는 서버에 저장하지 않는다(브라우저에만). 서버에는 구역(zone_id)만.
-- =====================================================================
create table if not exists public.device_clients (
  id bigint generated always as identity primary key,
  device_id  text not null references public.devices(device_id) on delete cascade,
  token_hash text not null unique,
  created_at timestamptz not null default now(),
  last_used  timestamptz
);
alter table public.device_clients enable row level security;
revoke all on public.device_clients from anon, authenticated;
grant all on public.device_clients to service_role;

alter table public.devices add column if not exists pair_code_hash text;
alter table public.devices add column if not exists pair_expires timestamptz;
alter table public.devices add column if not exists pair_tries int not null default 0;

create or replace function public._sha(p text) returns text
language sql immutable set search_path = public, extensions as $$
  select encode(extensions.digest(p, 'sha256'), 'hex');
$$;

-- 기기 토큰만
create or replace function public._device_master_ok(p_device text, p_token text) returns boolean
language sql stable security definer set search_path = public, extensions as $$
  select exists(select 1 from devices where device_id = p_device and token_hash = _sha(p_token));
$$;

-- 기기 토큰 또는 연결된 클라이언트 토큰
create or replace function public._device_ok(p_device text, p_token text) returns boolean
language plpgsql security definer set search_path = public, extensions as $$
begin
  if _device_master_ok(p_device, p_token) then return true; end if;
  update device_clients set last_used = now() where device_id = p_device and token_hash = _sha(p_token);
  return found;
end; $$;

-- 상태 보고는 기기만
create or replace function public.device_report(p_device text, p_token text, p_fan boolean, p_mode text,
    p_fw text default null, p_rssi int default null, p_indoor real default null, p_note text default null) returns void
language plpgsql security definer set search_path = public, extensions as $$
declare prev boolean;
begin
  if not _device_master_ok(p_device, p_token) then raise exception 'unauthorized'; end if;
  select fan_on into prev from device_status where device_id = p_device;
  insert into device_status(device_id, seen_at, fan_on, mode, fw, rssi, indoor_idx, note)
  values (p_device, now(), p_fan, p_mode, p_fw, p_rssi, p_indoor, p_note)
  on conflict (device_id) do update set seen_at = now(), fan_on = excluded.fan_on, mode = excluded.mode,
    fw = excluded.fw, rssi = excluded.rssi, indoor_idx = excluded.indoor_idx, note = excluded.note;
  if prev is distinct from p_fan then
    insert into device_log(device_id, kind, detail) values (p_device, case when p_fan then 'on' else 'off' end, p_note);
  end if;
end; $$;

-- 기기(또는 운영자)가 6자리 연결 코드를 만든다. 10분 유효, 5번 틀리면 무효
create or replace function public.device_new_pair_code(p_device text, p_token text) returns text
language plpgsql security definer set search_path = public, extensions as $$
declare code text;
begin
  if not _device_master_ok(p_device, p_token) then raise exception 'unauthorized'; end if;
  code := lpad((abs(('x' || encode(extensions.gen_random_bytes(4), 'hex'))::bit(32)::int) % 1000000)::text, 6, '0');
  update devices set pair_code_hash = _sha(p_device || ':' || code), pair_expires = now() + interval '10 minutes', pair_tries = 0
  where device_id = p_device;
  insert into device_log(device_id, kind, detail) values (p_device, 'settings', '연결 코드 발급');
  return code;
end; $$;

-- 웹·휴대폰: 기기 번호 + 코드 → 클라이언트 토큰 (한 번만 보여줌)
create or replace function public.device_pair(p_device text, p_code text) returns text
language plpgsql security definer set search_path = public, extensions as $$
declare d devices; tok text;
begin
  select * into d from devices where device_id = upper(trim(p_device));
  if d.device_id is null or d.pair_code_hash is null or d.pair_expires < now() or d.pair_tries >= 5 then
    raise exception 'code expired';
  end if;
  if d.pair_code_hash <> _sha(d.device_id || ':' || trim(p_code)) then
    update devices set pair_tries = pair_tries + 1 where device_id = d.device_id;
    raise exception 'invalid code';
  end if;
  tok := encode(extensions.gen_random_bytes(24), 'hex');
  insert into device_clients(device_id, token_hash) values (d.device_id, _sha(tok));
  update devices set pair_code_hash = null, pair_expires = null, pair_tries = 0 where device_id = d.device_id;
  insert into device_log(device_id, kind, detail) values (d.device_id, 'settings', '새 기기 연결');
  return tok;
end; $$;

create or replace function public.device_unpair(p_device text, p_token text) returns void
language sql security definer set search_path = public, extensions as $$
  delete from device_clients where device_id = p_device and token_hash = _sha(p_token);
$$;

-- 설정: 이름 추가 (기존 시그니처 교체)
drop function if exists public.device_set(text,text,text,int,text,text,int);
create or replace function public.device_set(p_device text, p_token text, p_zone text default null,
    p_lead int default null, p_trigger text default null, p_mode text default null, p_manual_hours int default 2,
    p_name text default null)
returns void language plpgsql security definer set search_path = public, extensions as $$
begin
  if not _device_ok(p_device, p_token) then raise exception 'unauthorized'; end if;
  update devices set
    name = coalesce(nullif(trim(p_name), ''), name),
    zone_id = coalesce(p_zone, zone_id), lead_min = coalesce(p_lead, lead_min),
    trigger_level = coalesce(p_trigger, trigger_level), mode = coalesce(p_mode, mode),
    manual_until = case when p_mode in ('on','off') then now() + make_interval(hours => p_manual_hours)
                        when p_mode = 'auto' then null else manual_until end
  where device_id = p_device;
  insert into device_log(device_id, kind, detail)
  values (p_device, 'settings', concat_ws(' ', 'zone='||p_zone, 'lead='||p_lead, 'trigger='||p_trigger, 'mode='||p_mode));
end; $$;

revoke all on function public._sha(text) from public, anon, authenticated;
revoke all on function public._device_master_ok(text,text) from public, anon, authenticated;
revoke all on function public._device_ok(text,text) from public, anon, authenticated;
revoke all on function public.device_new_pair_code(text,text) from public, anon, authenticated;
grant execute on function public.device_new_pair_code(text,text) to anon, authenticated;   -- 기기 토큰 필요
grant execute on function public.device_pair(text,text) to anon, authenticated;
grant execute on function public.device_unpair(text,text) to anon, authenticated;
grant execute on function public.device_set(text,text,text,int,text,text,int,text) to anon, authenticated;

select 'ok' as device_pair_migration;
